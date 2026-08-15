# -*- coding: utf-8 -*-
# [来源] 本工具产出于一个真实 PCB 工程的 AI 自动化画板实践, 已脱敏后开源 — easyeda-agent-toolkit
"""拥堵段干线下沉内层: 违例段 -> 同网络连通链 -> 在出口开阔处打双 via 断点(优先借用既有 via)
   -> 用内层规整 H/V 直线替代表层拥堵段, 把表层挤出净空.

适用场景: 多层板上某条走廊(常见于板中缝/颈部)表层塞满、平移已经挪无可挪时的最后一招。
事务性: 每个网络动手前备份到 _ns_backup_<board>.json, 失败可整网恢复; 双 via 并联保载流; 不留 stub。

用法: python neck_sink.py <parentBoardName> [--dry] [--nets A,B] [--prefix PFX] [--limit N]
  --dry     只推演不落板
  --nets    只处理这些网络(逗号分隔)
  --prefix  只处理网名以此前缀开头的网络(不传 = 全部)
  --limit   最多处理几个网络(按违例数降序)"""
import json, io, os, sys, subprocess, math

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
DRY = "--dry" in sys.argv
ONLY = None
PREFIX = ""
LIMIT = 99
for i, a in enumerate(sys.argv):
    if a in ("--nets", "--prefix", "--limit") and i + 1 >= len(sys.argv):
        print(f"[ERR] {a} 后面缺参数"); sys.exit(1)
    if a == "--nets": ONLY = set(sys.argv[i+1].split(","))
    if a == "--prefix": PREFIX = sys.argv[i+1]
    if a == "--limit": LIMIT = int(sys.argv[i+1])
M = 39.3701
IN1 = 15
VIA_OD, VIA_ID = 16.1417, 11.811
VIA_GAP = 25.6          # 双via中心距(0.65mm)
SPOT_R = VIA_OD/2+6.2   # via落点净空半径
LINE_CLR = 4.45         # 内层线净空
EPS = 1e-6
BK = os.path.join(S, f"_ns_backup_{BOARD}.json")
_bi = 1
while os.path.exists(BK):
    _bi += 1
    BK = os.path.join(S, f"_ns_backup_{BOARD}_{_bi}.json")

def run_js(js, timeout_s=600):
    p = os.path.join(S, "eda_jobs", "_ns_tmp.js")
    io.open(p, "w", encoding="utf-8").write(js)
    r = subprocess.run([sys.executable, os.path.join(S, "eda_bridge.py"), "run", p],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_s)
    raw = (r.stdout or "").strip()
    try:
        v = json.loads(raw)
        if isinstance(v, str): v = json.loads(v)
        return v
    except Exception:
        return {"err": "rawfail", "raw": raw[:400]}

OPEN = ('const pcbs=await eda.dmt_Pcb.getAllPcbsInfo()||[];'
        'const hit=pcbs.find(p=>p.parentBoardName==="%s");'
        'if(!hit)return JSON.stringify({err:"nf"});'
        'let t=await eda.dmt_EditorControl.openDocument(hit.uuid);'
        'await eda.dmt_EditorControl.activateDocument(t);'
        'await new Promise(r=>setTimeout(r,2500));' % BOARD)

def key(x, y): return (round(x*1000), round(y*1000))

def seg_pt(px, py, ax, ay, bx, by):
    dx, dy = bx-ax, by-ay
    L2 = dx*dx+dy*dy
    if L2 < EPS: return ax, ay
    t = max(0.0, min(1.0, ((px-ax)*dx+(py-ay)*dy)/L2))
    return ax+t*dx, ay+t*dy

def main():
    print(f"[neck_sink] {BOARD} dry={DRY}")
    d = run_js(OPEN + '''
const L=await eda.pcb_PrimitiveLine.getAll()||[];
const V=await eda.pcb_PrimitiveVia.getAll()||[];
const P=await eda.pcb_PrimitivePad.getAll()||[];
const drc=await eda.pcb_Drc.check(false,false,true);
const viol=[];
for(const cat of (drc||[]))for(const g of (cat.list||[]))for(const e of (g.list||[])){
  const ed=e.explanation&&e.explanation.errData; if(!ed)continue;
  viol.push({o1:ed.obj1,t1:ed.obj1Type,o2:ed.obj2,t2:ed.obj2Type});
}
return JSON.stringify({
 lines:L.map(o=>({id:o.primitiveId,l:o.layer,n:o.net||"",w:o.lineWidth,x1:o.startX,y1:o.startY,x2:o.endX,y2:o.endY})),
 vias:V.map(o=>({id:o.primitiveId,n:o.net||"",x:o.x,y:o.y,d:o.diameter})),
 pads:P.map(o=>({id:o.primitiveId,l:o.layer,n:o.net||"",x:o.x,y:o.y,th:o.hole!==null,
   w:(Array.isArray(o.pad)&&o.pad.length>2)?(Number(o.pad[1])||20):20,
   h:(Array.isArray(o.pad)&&o.pad.length>2)?(Number(o.pad[2])||20):20})),
 viol:viol});''')
    if not isinstance(d, dict) or "lines" not in d:
        print("[ABORT] 取板数据失败(板名对不对? 桥通不通? 嘉立创开着吗):", str(d)[:200]); sys.exit(1)
    lines = {o["id"]: o for o in d["lines"]}
    vias, pads, viol = d["vias"], d["pads"], d["viol"]
    print(f"[dump] lines={len(lines)} vias={len(vias)} pads={len(pads)} viol={len(viol)}")

    net_viol = {}
    for v in viol:
        if not all(k in v for k in ("o1", "t1", "o2", "t2")): continue
        for (o, t) in ((v["o1"], v["t1"]), (v["o2"], v["t2"])):
            if t == "Track" and o in lines and lines[o]["l"] == 1:
                n = lines[o]["n"]
                if n and n.startswith(PREFIX): net_viol.setdefault(n, set()).add(o)
    cand = sorted(net_viol.items(), key=lambda x: -len(x[1]))
    if ONLY: cand = [(n, s) for (n, s) in cand if n in ONLY]
    cand = cand[:LIMIT]

    ep = {}
    for o in lines.values():
        for (x, y) in ((o["x1"], o["y1"]), (o["x2"], o["y2"])):
            ep.setdefault((o["n"], o["l"])+key(x, y), []).append(o["id"])
    via_at = {key(v["x"], v["y"]): v for v in vias}

    def is_pad_pt(n, l, x, y):
        for p in pads:
            if p["n"] == n and (p["th"] or p["l"] == l):
                r = max(p["w"], p["h"])/2+1
                if abs(x-p["x"]) < r and abs(y-p["y"]) < r and math.hypot(x-p["x"], y-p["y"]) < r:
                    return True
        return False

    new_inner = []   # 本轮已建内层线(避让用)
    new_vias = []    # 本轮已建via

    def spot_free(x, y, net):
        for o in lines.values():
            if o["n"] == net: continue
            cx, cy = seg_pt(x, y, o["x1"], o["y1"], o["x2"], o["y2"])
            if math.hypot(x-cx, y-cy) < SPOT_R + o["w"]/2: return False
        for v in vias:
            if v["n"] == net: continue
            if math.hypot(x-v["x"], y-v["y"]) < SPOT_R + v["d"]/2: return False
        for v in new_vias:
            if v["n"] == net: continue
            if math.hypot(x-v["x"], y-v["y"]) < SPOT_R + VIA_OD/2: return False
        for p in pads:
            if p["n"] == net: continue
            r = max(p["w"], p["h"])/2
            if math.hypot(x-p["x"], y-p["y"]) < SPOT_R + r: return False
        return True

    def inner_clear(x1, y1, x2, y2, net, w):
        ns = (x1, y1, x2, y2)
        for o in list(lines.values()):
            if o["l"] != IN1 or o["n"] == net: continue
            a = seg_pt(o["x1"], o["y1"], *ns); b = seg_pt(o["x2"], o["y2"], *ns)
            dm = min(math.hypot(o["x1"]-a[0], o["y1"]-a[1]), math.hypot(o["x2"]-b[0], o["y2"]-b[1]))
            for (px, py) in ((x1, y1), (x2, y2)):
                c = seg_pt(px, py, o["x1"], o["y1"], o["x2"], o["y2"])
                dm = min(dm, math.hypot(px-c[0], py-c[1]))
            if dm < LINE_CLR + (w+o["w"])/2: return False
        for o in new_inner:
            if o["n"] == net: continue
            a = seg_pt(o["x1"], o["y1"], *ns); b = seg_pt(o["x2"], o["y2"], *ns)
            dm = min(math.hypot(o["x1"]-a[0], o["y1"]-a[1]), math.hypot(o["x2"]-b[0], o["y2"]-b[1]))
            if dm < LINE_CLR + (w+o["w"])/2: return False
        for v in vias:
            if v["n"] == net: continue
            c = seg_pt(v["x"], v["y"], *ns)
            if math.hypot(v["x"]-c[0], v["y"]-c[1]) < 6.2 + w/2 + v["d"]/2: return False
        for p in pads:
            if p["n"] == net or not p["th"]: continue
            c = seg_pt(p["x"], p["y"], *ns)
            if math.hypot(p["x"]-c[0], p["y"]-c[1]) < LINE_CLR + w/2 + max(p["w"], p["h"])/2: return False
        return True

    def ends_of(chain):
        cnt = {}
        for sid in chain:
            o = lines[sid]
            for (x, y) in ((o["x1"], o["y1"]), (o["x2"], o["y2"])):
                k = key(x, y)
                c = cnt.get(k, (0, x, y)); cnt[k] = (c[0]+1, x, y)
        return [(x, y) for (c, x, y) in cnt.values() if c == 1]

    def components(chain, net):
        comps, rest = [], set(chain)
        while rest:
            seed = rest.pop(); comp = {seed}; fr = [seed]
            while fr:
                sid = fr.pop(); o = lines[sid]
                for (x, y) in ((o["x1"], o["y1"]), (o["x2"], o["y2"])):
                    for t in ep.get((net, 1)+key(x, y), []):
                        if t in rest:
                            rest.discard(t); comp.add(t); fr.append(t)
            comps.append(comp)
        return comps

    def find_cut(x, y, hot, net):
        """从热链端点沿链外段走(最多5段/400mil), 每点尝试 via1 原位/侧移, via2 四方向"""
        cur = (x, y); walked = 0.0; prev = None
        chain_path = []
        for _ in range(5):
            outs = [t for t in ep.get((net, 1)+key(cur[0], cur[1]), []) if t not in hot and t != prev]
            if len(outs) != 1: break
            t = outs[0]; o = lines[t]
            ax, ay = (o["x1"], o["y1"]) if key(o["x1"], o["y1"]) == key(cur[0], cur[1]) else (o["x2"], o["y2"])
            bx, by = (o["x2"], o["y2"]) if key(o["x1"], o["y1"]) == key(cur[0], cur[1]) else (o["x1"], o["y1"])
            L = math.hypot(bx-ax, by-ay)
            if L < 1: cur = (bx, by); prev = t; continue
            ux, uy = (bx-ax)/L, (by-ay)/L
            nxv, nyv = -uy, ux
            tpos = 8.0
            while tpos <= L and walked+tpos < 400:
                p = (ax+ux*tpos, ay+uy*tpos)
                for off in (0, 20, -20, 40, -40, 60, -60, 80, -80, 100, -100, 120, -120):
                    v1 = (p[0]+nxv*off, p[1]+nyv*off)
                    if spot_free(v1[0], v1[1], net):
                        return {"mode": "cut", "seg": t, "cutAt": p, "off": off,
                                "p1": v1, "keep": (bx, by),
                                "x": v1[0], "y": v1[1], "chainDel": list(chain_path)}
                tpos += 12
            walked += L
            chain_path.append(t)
            cur = (bx, by); prev = t
        return None

    plans = []
    for (net, seeds) in cand:
        hot_all = set(seeds); frontier = list(seeds)
        xs, ys = [], []
        for s in seeds:
            o = lines[s]; xs += [o["x1"], o["x2"]]; ys += [o["y1"], o["y2"]]
        bx1, bx2 = min(xs)-40, max(xs)+40
        by1, by2 = min(ys)-40, max(ys)+40
        while frontier:
            sid = frontier.pop()
            o = lines[sid]
            for (x, y) in ((o["x1"], o["y1"]), (o["x2"], o["y2"])):
                nb = ep.get((net, 1)+key(x, y), [])
                if len(nb) != 2: continue
                for t in nb:
                    if t in hot_all: continue
                    to = lines[t]
                    if min(to["x1"], to["x2"]) > bx2 or max(to["x1"], to["x2"]) < bx1: continue
                    if min(to["y1"], to["y2"]) > by2 or max(to["y1"], to["y2"]) < by1: continue
                    hot_all.add(t); frontier.append(t)

        for ci, hot in enumerate(components(hot_all, net)):
            tag = f"{net}#{ci}" if ci else net
            for _ in range(30):
                trimmed = False
                for (x, y) in ends_of(hot):
                    if key(x, y) in via_at: continue
                    if is_pad_pt(net, 1, x, y) or len(ep.get((net, 1)+key(x, y), [])) > 2:
                        for sid in list(hot):
                            o = lines[sid]
                            if key(o["x1"], o["y1"]) == key(x, y) or key(o["x2"], o["y2"]) == key(x, y):
                                hot.discard(sid); trimmed = True
                if not trimmed: break
            if not hot:
                plans.append({"net": tag, "skip": "trimmed-empty"}); continue
            ends = ends_of(hot)
            if len(ends) != 2:
                plans.append({"net": tag, "skip": f"ends={len(ends)}"}); continue

            endinfo = []
            ok = True
            for (x, y) in ends:
                if key(x, y) in via_at:
                    endinfo.append({"mode": "oldvia", "x": x, "y": y}); continue
                found = find_cut(x, y, hot, net)
                if found: endinfo.append(found)
                else: ok = False; break
            if not ok:
                plans.append({"net": tag, "skip": "no-via-spot"}); continue
            # cut 途中走过的链段并入删除集
            for e in endinfo:
                if e["mode"] == "cut":
                    for t in e.get("chainDel", []): hot.add(t)

            # 内层路径 A->B: 同y直线 / H-V-H / V-H-V
            A, B = endinfo[0], endinfo[1]
            w = max(lines[s]["w"] for s in hot)
            path = None
            if abs(A["y"]-B["y"]) < 2 and inner_clear(A["x"], A["y"], B["x"], B["y"], net, w):
                path = [(A["x"], A["y"], B["x"], B["y"])]
            if path is None and abs(A["x"]-B["x"]) < 2 and inner_clear(A["x"], A["y"], B["x"], B["y"], net, w):
                path = [(A["x"], A["y"], B["x"], B["y"])]
            if path is None:
                for dm in [i*8 for i in range(0, 60)]:
                    for sgn in (1, -1):
                        xm = (A["x"]+B["x"])/2 + sgn*dm
                        p = [(A["x"], A["y"], xm, A["y"]), (xm, A["y"], xm, B["y"]), (xm, B["y"], B["x"], B["y"])]
                        if all(inner_clear(*seg, net, w) for seg in p):
                            path = p; break
                        ym = (A["y"]+B["y"])/2 + sgn*dm
                        p = [(A["x"], A["y"], A["x"], ym), (A["x"], ym, B["x"], ym), (B["x"], ym, B["x"], B["y"])]
                        if all(inner_clear(*seg, net, w) for seg in p):
                            path = p; break
                    if path: break
            if path is None:
                plans.append({"net": tag, "skip": "no-inner-path"}); continue

            plans.append({"net": tag, "netname": net, "hot": sorted(hot), "ends": endinfo,
                          "path": path, "w": w, "viol": len(seeds)})
            for v_ in endinfo:
                if v_["mode"] == "cut":
                    new_vias.append({"n": net, "x": v_["p1"][0], "y": v_["p1"][1]})
            for seg in path:
                new_inner.append({"n": net, "x1": seg[0], "y1": seg[1], "x2": seg[2], "y2": seg[3], "w": w})

    print(f"\n{'net':10s} {'违例':4s} {'删段':4s} {'新via':5s} {'内层段':5s} 备注")
    for p in plans:
        if "skip" in p:
            print(f"{p['net']:10s} {'-':4s} {'-':4s} {'-':5s} {'-':5s} SKIP:{p['skip']}")
        else:
            nv = sum(1 for e in p["ends"] if e["mode"] == "cut")
            print(f"{p['net']:10s} {p['viol']:4d} {len(p['hot']):4d} {nv:5d} {len(p['path']):5d} ends={','.join(e['mode'] for e in p['ends'])}")
    if DRY: return

    todo = [p for p in plans if "skip" not in p]
    backup = {"board": BOARD, "nets": {}}
    for p in todo:
        backup["nets"][p["net"]] = {"deleted": [dict(lines[s]) for s in p["hot"]],
                                    "cut": [{"id": e["seg"], "orig": dict(lines[e["seg"]])} for e in p["ends"] if e["mode"] == "cut"]}
    io.open(BK, "w", encoding="utf-8").write(json.dumps(backup, ensure_ascii=False))
    print(f"[backup] {BK}")

    for p in todo:
        net = p["netname"]; w = p["w"]
        ops = []
        for s in p["hot"]:
            ops.append(f'await eda.pcb_PrimitiveLine.delete("{s}");')
        for e in p["ends"]:
            if e["mode"] != "cut": continue
            o = lines[e["seg"]]
            kx, ky = e["keep"]
            ca = e["cutAt"]
            if key(o["x1"], o["y1"]) == key(kx, ky):
                ops.append(f'await eda.pcb_PrimitiveLine.modify("{e["seg"]}",{{startX:{kx},startY:{ky},endX:{ca[0]},endY:{ca[1]}}});')
            else:
                ops.append(f'await eda.pcb_PrimitiveLine.modify("{e["seg"]}",{{startX:{ca[0]},startY:{ca[1]},endX:{kx},endY:{ky}}});')
            if e.get("off"):
                ops.append(f'await eda.pcb_PrimitiveLine.create("{net}",1,{ca[0]},{ca[1]},{e["p1"][0]},{e["p1"][1]},{w},false);')
            ops.append(f'await eda.pcb_PrimitiveVia.create("{net}",{e["p1"][0]},{e["p1"][1]},{VIA_ID},{VIA_OD});')
        for seg in p["path"]:
            ops.append(f'await eda.pcb_PrimitiveLine.create("{net}",{IN1},{seg[0]},{seg[1]},{seg[2]},{seg[3]},{w},false);')
        js = OPEN + "".join(ops) + 'await eda.pcb_Document.save();return JSON.stringify({done:true});'
        r = run_js(js)
        print(f"[exec] {p['net']}: {r}")

    print("[done] 执行完毕; 请跑 netcmp + repour + DRC 验证")

main()
