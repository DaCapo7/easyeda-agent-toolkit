# -*- coding: utf-8 -*-
# [来源] 本工具产出于一个真实 PCB 工程的 AI 自动化画板实践, 已脱敏后开源 — easyeda-agent-toolkit
"""间距违例微挪器: 只平移 Track(不旋转、不加拐点), 端点连同"精确共享端点"的邻接段一起动以保连接;
端点落在 焊盘/过孔/圆弧 上的段判 fixed 不挪; 挪之前先查背后有没有空间, 不够就分摊或跳过;
同一轮里对动过的段加锁, 防止连锁把别处挤崩。

这是"不改拓扑只改几何"的第一道手术, 通常先跑它, 剩下的硬骨头再交给 width_cut / neck_sink。

用法: python gap_nudge.py <parentBoardName> [maxrounds=4] [目标间距mil=4.4094] [背后空间下限mil=4.34]
单位说明: 图元坐标内部单位 = mil; 4.4094mil = 0.112mm(即 0.11mm 规则 + 2µm 余量)。"""
import json, io, os, sys, subprocess, math, time

# 中文 Windows 控制台默认 GBK, 打印中文/✓✗ 会抛 UnicodeEncodeError 直接崩脚本
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
S = os.path.dirname(os.path.abspath(__file__))
os.makedirs(os.path.join(S, "eda_jobs"), exist_ok=True)
if len(sys.argv) < 2:
    print(__doc__); sys.exit(1)
BOARD = sys.argv[1]
MAXROUNDS = int(sys.argv[2]) if len(sys.argv) > 2 else 4
TARGET = float(sys.argv[3]) if len(sys.argv) > 3 else 4.4094   # mil, 0.112mm
SAFE   = float(sys.argv[4]) if len(sys.argv) > 4 else 4.3400   # mil, 背后空间判定下限(略高于规则值)
EPS    = 1e-6

def run_js(js, timeout_s=600):
    p = os.path.join(S, "eda_jobs", "_gn_tmp.js")
    io.open(p, "w", encoding="utf-8").write(js)
    r = subprocess.run([sys.executable, os.path.join(S, "eda_bridge.py"), "run", p],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_s)
    v = json.loads((r.stdout or "").strip())
    if isinstance(v, str): v = json.loads(v)
    return v

OPEN = ('const pcbs=await eda.dmt_Pcb.getAllPcbsInfo()||[];'
        'const hit=pcbs.find(p=>p.parentBoardName==="%s");'
        'if(!hit)return JSON.stringify({err:"nf"});'
        'let t=await eda.dmt_EditorControl.openDocument(hit.uuid);'
        'await eda.dmt_EditorControl.activateDocument(t);'
        'await new Promise(r=>setTimeout(r,2500));' % BOARD)

def dump_board():
    js = OPEN + '''
const L=await eda.pcb_PrimitiveLine.getAll()||[];
const V=await eda.pcb_PrimitiveVia.getAll()||[];
const P=await eda.pcb_PrimitivePad.getAll()||[];
const A=await eda.pcb_PrimitiveArc.getAll()||[];
return JSON.stringify({
 lines:L.map(o=>({id:o.primitiveId,l:o.layer,n:o.net||"",w:o.lineWidth,x1:o.startX,y1:o.startY,x2:o.endX,y2:o.endY})),
 vias:V.map(o=>({id:o.primitiveId,n:o.net||"",x:o.x,y:o.y,d:o.diameter||o.viaDiameter||16})),
 pads:P.map(o=>({id:o.primitiveId,l:o.layer,n:o.net||"",x:o.x,y:o.y,th:o.hole!==null,
   sh:(Array.isArray(o.pad)?String(o.pad[0]):"RECT"),
   w:(Array.isArray(o.pad)&&o.pad.length>2)?(Number(o.pad[1])||20):20,
   h:(Array.isArray(o.pad)&&o.pad.length>2)?(Number(o.pad[2])||20):20,
   rot:o.rotation||0})),
 arcs:A.map(o=>({id:o.primitiveId,l:o.layer}))});'''
    return run_js(js)

def dump_drc():
    js = OPEN + '''
const drc=await eda.pcb_Drc.check(false,false,true);
const out=[];
for(const cat of (drc||[]))for(const g of (cat.list||[]))for(const e of (g.list||[])){
  const ed=e.explanation&&e.explanation.errData; if(!ed)continue;
  out.push({g:g.name,o1:ed.obj1,t1:ed.obj1Type,o2:ed.obj2,t2:ed.obj2Type,
    md:ed.minDistance*10,lay:(ed.layerIds&&ed.layerIds[0])||0});
}
return JSON.stringify(out);'''
    return run_js(js)

# ---------- 几何 ----------
def seg_pt(px, py, ax, ay, bx, by):
    """点(p)到线段(ab)最近点"""
    dx, dy = bx-ax, by-ay
    L2 = dx*dx+dy*dy
    if L2 < EPS: return ax, ay
    t = max(0.0, min(1.0, ((px-ax)*dx+(py-ay)*dy)/L2))
    return ax+t*dx, ay+t*dy

def seg_seg(a, b):
    """两段最近距离与最近点对: 返回 (dist, qa, qb) qa在a上 qb在b上"""
    best = None
    for (p, q) in ((a, b), (b, a)):
        for (px, py) in ((p[0], p[1]), (p[2], p[3])):
            cx, cy = seg_pt(px, py, q[0], q[1], q[2], q[3])
            d = math.hypot(px-cx, py-cy)
            if best is None or d < best[0]:
                if p is a: best = (d, (px, py), (cx, cy))
                else:      best = (d, (cx, cy), (px, py))
    return best

def key(x, y):
    return (round(x*1000), round(y*1000))

def pt_pad_edge(px, py, pad):
    """点到焊盘边缘距离(旋转矩形/胶囊精确, 其他形状外接圆保守)"""
    dx, dy = px-pad["x"], py-pad["y"]
    cr, sr = math.cos(pad["rot"]), math.sin(pad["rot"])
    lx, ly = dx*cr+dy*sr, -dx*sr+dy*cr
    w2, h2 = pad["w"]/2.0, pad["h"]/2.0
    sh = pad.get("sh", "RECT").upper()
    if sh == "RECT":
        ex, ey = max(abs(lx)-w2, 0.0), max(abs(ly)-h2, 0.0)
        return math.hypot(ex, ey)
    if sh == "OVAL":
        if w2 >= h2:
            a, r = w2-h2, h2
            cx = max(-a, min(a, lx))
            return max(math.hypot(lx-cx, ly)-r, 0.0)
        a, r = h2-w2, w2
        cy = max(-a, min(a, ly))
        return max(math.hypot(lx, ly-cy)-r, 0.0)
    if sh == "ELLIPSE" and abs(w2-h2) < EPS:
        return max(math.hypot(lx, ly)-w2, 0.0)
    return max(math.hypot(lx, ly)-max(w2, h2), 0.0)

def main():
    print(f"[gap_nudge] {BOARD} target={TARGET}mil")
    data = dump_board()
    if not isinstance(data, dict) or "lines" not in data:
        print("[ABORT] 取板数据失败(板名对不对? 桥通不通?):", str(data)[:200]); sys.exit(1)
    lines = {o["id"]: o for o in data["lines"]}
    print(f"[dump] lines={len(lines)} vias={len(data['vias'])} pads={len(data['pads'])} arcs={len(data['arcs'])}")

    # fixed 端点: via中心/pad区域(外接圆+容差, fixed判定保守方向正确)
    via_pts = [(v["x"], v["y"], v.get("d", 20)/2.0) for v in data["vias"]]
    vias_by_id = {v["id"]: v for v in data["vias"]}
    pad_zones = [(p["x"], p["y"], max(p["w"], p["h"])/2.0+3.0, p["l"], p["th"]) for p in data["pads"]]

    def endpoint_fixed(x, y, layer):
        for (vx, vy, vr) in via_pts:
            if abs(x-vx) < vr+1 and abs(y-vy) < vr+1: return True
        for (px, py, pr, pl, th) in pad_zones:
            if (th or pl == layer) and abs(x-px) < pr and abs(y-py) < pr:
                if math.hypot(x-px, y-py) < pr: return True
        return False

    total_moved = 0
    prev_total = None
    for rnd in range(1, MAXROUNDS+1):
        viol = dump_drc()
        viol = [v for v in viol if isinstance(v, dict) and all(k in v for k in ("o1", "t1", "o2", "t2", "md"))]
        if prev_total is not None and len(viol) >= prev_total:
            print(f"[stop] 违例数不再下降({prev_total}->{len(viol)}), 停止")
            break
        prev_total = len(viol)
        tt = [v for v in viol if v["t1"] == "Track" and v["t2"] == "Track"]
        pt = [v for v in viol if ("Pad" in v["t1"]) != ("Pad" in v["t2"])]
        print(f"[round{rnd}] 违例总数={len(viol)} track-track={len(tt)} pad-track={len(pt)}")
        if not viol: break

        # 端点共享索引(按层)
        ep_index = {}
        for o in lines.values():
            for (x, y) in ((o["x1"], o["y1"]), (o["x2"], o["y2"])):
                ep_index.setdefault((o["l"],)+key(x, y), []).append(o["id"])

        def movable(seg_id):
            o = lines.get(seg_id)
            if not o: return False
            for (x, y) in ((o["x1"], o["y1"]), (o["x2"], o["y2"])):
                if endpoint_fixed(x, y, o["l"]): return False
            return True

        def followers(seg_id):
            """返回 {other_id: [端点序号...]} 与被挪段共享端点的邻接段"""
            o = lines[seg_id]; fol = {}
            for (x, y) in ((o["x1"], o["y1"]), (o["x2"], o["y2"])):
                for oid in ep_index.get((o["l"],)+key(x, y), []):
                    if oid == seg_id: continue
                    t = lines[oid]
                    for i, (ex, ey) in enumerate(((t["x1"], t["y1"]), (t["x2"], t["y2"]))):
                        if key(ex, ey) == key(x, y): fol.setdefault(oid, []).append(i)
            return fol

        # 同层空间格网(加速背后空间查询)
        grid = {}
        CELL = 40.0
        for o in lines.values():
            gx1, gy1 = int(min(o["x1"], o["x2"])//CELL), int(min(o["y1"], o["y2"])//CELL)
            gx2, gy2 = int(max(o["x1"], o["x2"])//CELL), int(max(o["y1"], o["y2"])//CELL)
            for gx in range(gx1-1, gx2+2):
                for gy in range(gy1-1, gy2+2):
                    grid.setdefault((o["l"], gx, gy), []).append(o["id"])

        def neighbors(seg, layer, exclude):
            gx1, gy1 = int(min(seg[0], seg[2])//CELL), int(min(seg[1], seg[3])//CELL)
            gx2, gy2 = int(max(seg[0], seg[2])//CELL), int(max(seg[1], seg[3])//CELL)
            ids = set()
            for gx in range(gx1-1, gx2+2):
                for gy in range(gy1-1, gy2+2):
                    ids.update(grid.get((layer, gx, gy), []))
            return ids - exclude

        TOL = 0.05  # mil, 不恶化容差(1.27µm)

        def seg_space_ok(layer, mynet, w, ns, os_, excl):
            """不恶化原则: 新距离达标, 或不比旧距离更近(容差内)"""
            for oid in neighbors(ns, layer, excl):
                t = lines[oid]
                if t["n"] == mynet: continue
                ts = (t["x1"], t["y1"], t["x2"], t["y2"])
                dn, _, _ = seg_seg(ns, ts)
                dn -= (w+t["w"])/2
                if dn >= SAFE: continue
                do, _, _ = seg_seg(os_, ts)
                do -= (w+t["w"])/2
                if dn >= do - TOL: continue
                return False
            for (vx, vy, vr) in via_pts:
                cx, cy = seg_pt(vx, vy, *ns)
                dn = math.hypot(vx-cx, vy-cy) - w/2 - vr
                if dn >= 5.99: continue
                ox, oy = seg_pt(vx, vy, *os_)
                do = math.hypot(vx-ox, vy-oy) - w/2 - vr
                if dn >= do - TOL: continue
                return False
            for p in data["pads"]:
                if not (p["th"] or p["l"] == layer): continue
                bb = max(p["w"], p["h"])/2.0 + 12
                if min(abs(p["x"]-ns[0]), abs(p["x"]-ns[2])) > bb + abs(ns[2]-ns[0]) or \
                   min(abs(p["y"]-ns[1]), abs(p["y"]-ns[3])) > bb + abs(ns[3]-ns[1]): continue
                def pad_min(seg):
                    cx, cy = seg_pt(p["x"], p["y"], *seg)
                    cand = [(cx, cy)] + [(seg[0]+(seg[2]-seg[0])*t_, seg[1]+(seg[3]-seg[1])*t_) for t_ in (0, .25, .5, .75, 1)]
                    return min(pt_pad_edge(px_, py_, p) for (px_, py_) in cand)
                dn = pad_min(ns) - w/2
                if dn >= SAFE: continue
                do = pad_min(os_) - w/2
                if dn >= do - TOL: continue
                return False
            return True

        def space_ok(seg_id, nx1, ny1, nx2, ny2, partner, mynet):
            o = lines[seg_id]
            excl = {seg_id, partner} | set(followers(seg_id).keys())
            return seg_space_ok(o["l"], mynet, o["w"], (nx1, ny1, nx2, ny2),
                                (o["x1"], o["y1"], o["x2"], o["y2"]), excl)

        locked = set()
        batch = {}   # id -> {startX,...}

        def plan_move(seg_id, ux, uy, dist, partner):
            """seg 沿(ux,uy)平移 dist, 生成本段+跟随段更新; 冲突返回 False"""
            o = lines[seg_id]
            fol = followers(seg_id)
            touch = {seg_id} | set(fol.keys())
            if touch & locked: return False
            nx1, ny1 = o["x1"]+ux*dist, o["y1"]+uy*dist
            nx2, ny2 = o["x2"]+ux*dist, o["y2"]+uy*dist
            if not space_ok(seg_id, nx1, ny1, nx2, ny2, partner, o["n"]): return False
            # 先在草稿上算跟随段新几何, 全部过空间检查后才提交
            drafts = {}
            omap = lines[seg_id]
            for oid, idxs in fol.items():
                t = dict(batch.get(oid, lines[oid]))
                for i in idxs:
                    for (oxk, oyk, nxv, nyv) in ((omap["x1"], omap["y1"], nx1, ny1), (omap["x2"], omap["y2"], nx2, ny2)):
                        if i == 0 and key(t["x1"], t["y1"]) == key(oxk, oyk):
                            t["x1"], t["y1"] = nxv, nyv
                        if i == 1 and key(t["x2"], t["y2"]) == key(oxk, oyk):
                            t["x2"], t["y2"] = nxv, nyv
                drafts[oid] = t
            for oid, t in drafts.items():
                excl = touch | {partner}
                old = lines[oid]
                if not seg_space_ok(t["l"], t["n"], t["w"], (t["x1"], t["y1"], t["x2"], t["y2"]),
                                    (old["x1"], old["y1"], old["x2"], old["y2"]), excl):
                    return False
            batch.setdefault(seg_id, dict(o))
            batch[seg_id].update(x1=nx1, y1=ny1, x2=nx2, y2=ny2)
            for oid, t in drafts.items():
                batch[oid] = t
            locked.update(touch)
            return True

        planned = skipped = partial = 0
        why = {"bothFixed": 0, "blockedOrLocked": 0, "geom": 0, "other": 0}
        viol_sorted = sorted(viol, key=lambda v: v["md"])
        for v in viol_sorted:
            need = TARGET - v["md"]
            if need <= 0: continue
            a, b = v["o1"], v["o2"]
            ta, tb = v["t1"], v["t2"]
            if ta == "Track" and tb == "Track":
                if a not in lines or b not in lines: skipped += 1; why["other"] += 1; continue
                oa, ob = lines[a], lines[b]
                d, qa, qb = seg_seg((oa["x1"], oa["y1"], oa["x2"], oa["y2"]),
                                    (ob["x1"], ob["y1"], ob["x2"], ob["y2"]))
                vx, vy = qa[0]-qb[0], qa[1]-qb[1]
                L = math.hypot(vx, vy)
                if L < EPS: skipped += 1; why["geom"] += 1; continue
                ux, uy = vx/L, vy/L
                ma, mb = movable(a), movable(b)
                done = False
                if ma and mb:
                    done = plan_move(a, ux, uy, need/2+0.04, b) and plan_move(b, -ux, -uy, need/2+0.04, a)
                if not done:
                    # 渐进摊开: 全量不行就挪能挪的比例, 多轮迭代整束外扩
                    got = 0.0
                    if ma:
                        for frac in (1.0, 0.5, 0.25):
                            if plan_move(a, ux, uy, (need+0.08)*frac, b): got += (need+0.08)*frac; break
                    if mb and got < need:
                        for frac in (1.0, 0.5, 0.25):
                            if plan_move(b, -ux, -uy, (need+0.08)*frac, a): got += (need+0.08)*frac; break
                    done = got >= need
                    if not done and got > 0: partial += 1
                if done: planned += 1
                elif not (ma or mb):
                    skipped += 1; why["bothFixed"] += 1
                else:
                    skipped += 1; why["blockedOrLocked"] += 1
            elif ("Pad" in ta) != ("Pad" in tb):
                trk = a if ta == "Track" else b
                pad = b if ta == "Track" else a
                if trk not in lines: skipped += 1; why["other"] += 1; continue
                o = lines[trk]
                pz = next(((p["x"], p["y"]) for p in data["pads"] if p["id"] == pad), None)
                if pz is None: skipped += 1; why["other"] += 1; continue
                cx, cy = seg_pt(pz[0], pz[1], o["x1"], o["y1"], o["x2"], o["y2"])
                vx, vy = cx-pz[0], cy-pz[1]
                L = math.hypot(vx, vy)
                if L < EPS: skipped += 1; why["geom"] += 1; continue
                ux, uy = vx/L, vy/L
                if not movable(trk):
                    skipped += 1; why["bothFixed"] += 1
                elif plan_move(trk, ux, uy, need+0.08, pad):
                    planned += 1
                else:
                    skipped += 1; why["blockedOrLocked"] += 1
            elif "Via" in (ta, tb) and "Track" in (ta, tb):
                trk = a if ta == "Track" else b
                vid = b if ta == "Track" else a
                needv = 6.06 - v["md"]
                if needv <= 0: continue
                if trk not in lines: skipped += 1; why["other"] += 1; continue
                o = lines[trk]
                vz = vias_by_id.get(vid)
                if vz is None: skipped += 1; why["other"] += 1; continue
                cx, cy = seg_pt(vz["x"], vz["y"], o["x1"], o["y1"], o["x2"], o["y2"])
                vx_, vy_ = cx-vz["x"], cy-vz["y"]
                L = math.hypot(vx_, vy_)
                if L < EPS: skipped += 1; why["geom"] += 1; continue
                ux, uy = vx_/L, vy_/L
                if not movable(trk):
                    skipped += 1; why["bothFixed"] += 1
                elif plan_move(trk, ux, uy, needv+0.08, vid):
                    planned += 1
                else:
                    skipped += 1; why["blockedOrLocked"] += 1
            else:
                skipped += 1; why["other"] += 1
        print(f"[round{rnd}] 跳过原因: {why}")

        print(f"[round{rnd}] 全量挪动={planned} 部分挪动={partial} 跳过={skipped} 触碰原语={len(batch)}")
        if not batch: break

        # 批量 modify
        items = [{"id": i, "x1": b["x1"], "y1": b["y1"], "x2": b["x2"], "y2": b["y2"]} for i, b in batch.items()]
        CH = 120
        okn = 0
        for c0 in range(0, len(items), CH):
            chunk = items[c0:c0+CH]
            js = OPEN + 'const B=' + json.dumps(chunk) + ''';
let ok=0;
for(const it of B){
  try{const r=await eda.pcb_PrimitiveLine.modify(it.id,{startX:it.x1,startY:it.y1,endX:it.x2,endY:it.y2});if(r)ok++;}catch(e){}
}
return JSON.stringify({ok:ok,n:B.length});'''
            r = run_js(js)
            okn += (r.get("ok", 0) if isinstance(r, dict) else 0)
        print(f"[round{rnd}] modify 成功 {okn}/{len(items)}")
        total_moved += okn
        # 本地缓存同步新坐标
        for i, b in batch.items():
            lines[i].update(x1=b["x1"], y1=b["y1"], x2=b["x2"], y2=b["y2"])
        run_js(OPEN + 'await eda.pcb_Document.save();await new Promise(r=>setTimeout(r,1200));return JSON.stringify({saved:true});')

    print(f"[done] 共 modify {total_moved} 原语次; 收尾请重灌+保存+重启复核")

main()
