# -*- coding: utf-8 -*-
# [来源] 本工具产出于一个真实 PCB 工程的 AI 自动化画板实践, 已脱敏后开源 — easyeda-agent-toolkit
"""修复下沉落点缺陷: 违例via重定位(板框距/孔孔距/线距强化检查, 沿轴向优先, delete+create+端点跟随).
用法: python fix_sink.py <board>"""
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
M = 39.3701
VIA_OD, VIA_ID = 16.1417, 11.811
VR = VIA_OD/2
EPS = 1e-6

def run_js(js, timeout_s=600):
    p = os.path.join(S, "eda_jobs", "_fs_tmp.js")
    io.open(p, "w", encoding="utf-8").write(js)
    r = subprocess.run([sys.executable, os.path.join(S, "eda_bridge.py"), "run", p],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_s)
    raw = (r.stdout or "").strip()
    try:
        v = json.loads(raw)
        if isinstance(v, str): v = json.loads(v)
        return v
    except Exception:
        return {"err": "rawfail", "raw": raw[:300]}

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
    d = run_js(OPEN + '''
const L=await eda.pcb_PrimitiveLine.getAll()||[];
const V=await eda.pcb_PrimitiveVia.getAll()||[];
const P=await eda.pcb_PrimitivePad.getAll()||[];
const PL=await eda.pcb_PrimitivePolyline.getAll()||[];
const drc=await eda.pcb_Drc.check(false,false,true);
const viol=[];
for(const cat of (drc||[]))for(const g of (cat.list||[]))for(const e of (g.list||[])){
  const ed=e.explanation&&e.explanation.errData; if(!ed)continue;
  viol.push({o1:ed.obj1||"",t1:ed.obj1Type||"",o2:ed.obj2||"",t2:ed.obj2Type||""});
}
const bo=PL.find(o=>o.layer===11);
return JSON.stringify({
 lines:L.map(o=>({id:o.primitiveId,l:o.layer,n:o.net||"",w:o.lineWidth,x1:o.startX,y1:o.startY,x2:o.endX,y2:o.endY})),
 vias:V.map(o=>({id:o.primitiveId,n:o.net||"",x:o.x,y:o.y,d:o.diameter,hd:o.holeDiameter})),
 pads:P.map(o=>({id:o.primitiveId,l:o.layer,n:o.net||"",x:o.x,y:o.y,th:o.hole!==null,
   w:(Array.isArray(o.pad)&&o.pad.length>2)?(Number(o.pad[1])||20):20,
   h:(Array.isArray(o.pad)&&o.pad.length>2)?(Number(o.pad[2])||20):20})),
 outline:bo?bo.polygon.polygon:null,
 viol:viol});''')
    if not isinstance(d, dict) or "lines" not in d:
        print("[ABORT] 取板数据失败(板名对不对? 桥通不通? 嘉立创开着吗):", str(d)[:200]); sys.exit(1)
    lines = {o["id"]: o for o in d["lines"]}
    vias_by_id = {v["id"]: v for v in d["vias"]}
    pads, viol = d["pads"], d["viol"]

    # 板框折线段列表
    edges = []
    raw = d["outline"] or []
    pts = []
    i = 0
    while i < len(raw):
        if isinstance(raw[i], str): i += 1; continue
        pts.append((raw[i], raw[i+1])); i += 2
    for i in range(len(pts)):
        a, b = pts[i], pts[(i+1) % len(pts)]
        edges.append((a[0], a[1], b[0], b[1]))
    print(f"[dump] lines={len(lines)} vias={len(d['vias'])} 板框边={len(edges)} viol={len(viol)}")

    # 坏via = 违例对中 type∈{Via,Hole} 且 id 是 via 的; Copper Region 类交给重灌, 不挪
    via_at_pt = {key(v["x"], v["y"]): v["id"] for v in d["vias"]}
    bad = {}
    for v in viol:
        if "Copper Region" in v["t1"] or "Copper Region" in v["t2"]: continue
        for (o, t) in ((v["o1"], v["t1"]), (v["o2"], v["t2"])):
            if t in ("Via", "Hole") and o in vias_by_id:
                bad[o] = bad.get(o, 0) + 1
        # 贴板边的线: 其两端 via 一并重定位(spot_ok 板框检查会把它们引向板内)
        if "Board Outline" in (v["t1"], v["t2"]):
            trk = v["o1"] if v["t1"] == "Track" else (v["o2"] if v["t2"] == "Track" else None)
            if trk and trk in lines:
                o = lines[trk]
                for (x, y) in ((o["x1"], o["y1"]), (o["x2"], o["y2"])):
                    vid2 = via_at_pt.get(key(x, y))
                    if vid2: bad[vid2] = bad.get(vid2, 0) + 1
    print(f"[bad-via] {len(bad)} 颗: {[vias_by_id[b]['n'] for b in bad]}")
    if not bad: print("无坏via"); return

    def outline_dist(x, y):
        dm = 1e9
        for e in edges:
            cx, cy = seg_pt(x, y, *e)
            dm = min(dm, math.hypot(x-cx, y-cy))
        return dm

    moved = {}   # oldkey -> new (x,y)

    def spot_ok(x, y, net, skip_via):
        if outline_dist(x, y) < VR + 12.5: return False
        for o in lines.values():
            if o["n"] == net: continue
            cx, cy = seg_pt(x, y, o["x1"], o["y1"], o["x2"], o["y2"])
            if math.hypot(x-cx, y-cy) < VR + 6.1 + o["w"]/2: return False
        for v2 in d["vias"]:
            if v2["id"] == skip_via: continue
            nx, ny = moved.get(v2["id"], (v2["x"], v2["y"]))
            if math.hypot(x-nx, y-ny) < 24.6: return False
        for p in pads:
            r = max(p["w"], p["h"])/2
            if p["n"] != net and math.hypot(x-p["x"], y-p["y"]) < VR + 6.1 + r: return False
            if p["th"] and math.hypot(x-p["x"], y-p["y"]) < 24.6: return False
        return True

    ops_all = []
    fixed = skipped = 0
    for vid, cnt in sorted(bad.items(), key=lambda x: -x[1]):
        v = vias_by_id[vid]
        # 相连线段(端点在via中心)
        att = []
        for o in lines.values():
            for ei, (x, y) in enumerate(((o["x1"], o["y1"]), (o["x2"], o["y2"]))):
                if key(x, y) == key(v["x"], v["y"]): att.append((o["id"], ei))
        # 候选方向: 相连线轴向优先, 再八向
        dirs = []
        for (lid, ei) in att:
            o = lines[lid]
            dx, dy = o["x2"]-o["x1"], o["y2"]-o["y1"]
            L = math.hypot(dx, dy)
            if L > 1:
                u = (dx/L, dy/L)
                dirs += [u, (-u[0], -u[1])]
        dirs += [(1, 0), (-1, 0), (0, 1), (0, -1), (0.707, 0.707), (-0.707, 0.707), (0.707, -0.707), (-0.707, -0.707)]
        found = None
        for k_ in range(1, 40):
            for (ux, uy) in dirs:
                nx, ny = v["x"]+ux*k_*8, v["y"]+uy*k_*8
                if spot_ok(nx, ny, v["n"], vid):
                    found = (nx, ny); break
            if found: break
        if not att:
            skipped += 1; print(f"  [skip] {v['n']} via@({v['x']/M:.2f},{v['y']/M:.2f})mm 无跟随线(连接方式不明,不动)"); continue
        if not found:
            skipped += 1; print(f"  [skip] {v['n']} via@({v['x']/M:.2f},{v['y']/M:.2f})mm 无落点"); continue
        nx, ny = found
        moved[vid] = (nx, ny)
        ops = [f'await eda.pcb_PrimitiveVia.delete(["{vid}"]);',
               f'await eda.pcb_PrimitiveVia.create("{v["n"]}",{nx},{ny},{v.get("hd") or VIA_ID},{v["d"]});']
        for (lid, ei) in att:
            o = lines[lid]
            if ei == 0: o["x1"], o["y1"] = nx, ny
            else: o["x2"], o["y2"] = nx, ny
            # 斜线归正: 若因跟随变斜且是内层线, 拆 L 形
            if abs(o["x1"]-o["x2"]) > 1 and abs(o["y1"]-o["y2"]) > 1 and o["l"] in (15, 16):
                ops.append(f'await eda.pcb_PrimitiveLine.delete("{lid}");')   # Line.delete 收字符串(Via.delete 才收数组)
                ox, oy = (o["x2"], o["y2"]) if ei == 0 else (o["x1"], o["y1"])
                ops.append(f'await eda.pcb_PrimitiveLine.create("{o["n"]}",{o["l"]},{nx},{ny},{nx},{oy},{o["w"]},false);')
                ops.append(f'await eda.pcb_PrimitiveLine.create("{o["n"]}",{o["l"]},{nx},{oy},{ox},{oy},{o["w"]},false);')
                lines.pop(lid, None)
            else:
                ops.append(f'await eda.pcb_PrimitiveLine.modify("{lid}",{{startX:{o["x1"]},startY:{o["y1"]},endX:{o["x2"]},endY:{o["y2"]}}});')
        ops_all += ops
        fixed += 1
        print(f"  [fix] {v['n']} ({v['x']/M:.2f},{v['y']/M:.2f})->({nx/M:.2f},{ny/M:.2f})mm 跟随线{len(att)}")

    if ops_all:
        wrapped = "".join(f'try{{{op}}}catch(e){{errs.push((""+e).slice(0,90)+" @@ "+{json.dumps(op[:80])});}}' for op in ops_all)
        js = OPEN + "const errs=[];" + wrapped + 'await eda.pcb_Document.save();return JSON.stringify({done:true,errs:errs.slice(0,8),errN:errs.length});'
        r = run_js(js)
        print(f"[exec] {json.dumps(r, ensure_ascii=False)[:800]}")
    print(f"[done] fixed={fixed} skipped={skipped}")

main()
