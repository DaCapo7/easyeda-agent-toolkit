# -*- coding: utf-8 -*-
# [来源] 本工具产出于一个真实 PCB 工程的 AI 自动化画板实践, 已脱敏后开源 — easyeda-agent-toolkit
"""定点视觉: 选中 (x,y) 半径 r 内的图元 → zoomToSelectedPrimitives → 截图存 PNG。

这是"零信任校验"的眼睛 —— AI 改完板子必须自己看一眼, 别只信 API 的返回值。
输出到 tools/_out/<outname>.png。
环境变量 RA_TIGHT=1 时跳过 Line 扫描(只按 via/pad 定位, 大板上快很多)。

用法: python render_at.py <parentBoardName> <x_mm> <y_mm> <r_mm> <outname>"""
import json, io, os, sys, subprocess, base64

# 中文 Windows 控制台默认 GBK, 打印中文/✓✗ 会抛 UnicodeEncodeError 直接崩脚本
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
S = os.path.dirname(os.path.abspath(__file__))
os.makedirs(os.path.join(S, "eda_jobs"), exist_ok=True)
if len(sys.argv) < 6:
    print(__doc__); sys.exit(1)
BOARD, X, Y, R, OUT = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]), sys.argv[5]
M = 39.3701

def run_js(js, timeout_s=420):
    p = os.path.join(S, "eda_jobs", "_ra_tmp.js")
    io.open(p, "w", encoding="utf-8").write(js)
    r = subprocess.run([sys.executable, os.path.join(S, "eda_bridge.py"), "run", p],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_s)
    return (r.stdout or "").strip()

js = ('const pcbs=await eda.dmt_Pcb.getAllPcbsInfo()||[];'
      'const hit=pcbs.find(p=>p.parentBoardName==="%s");'
      'if(!hit)return JSON.stringify({err:"nf"});'
      'let t=await eda.dmt_EditorControl.openDocument(hit.uuid);'
      'await eda.dmt_EditorControl.activateDocument(t);'
      'await new Promise(r=>setTimeout(r,1200));'
      'const MM=39.3701;const X=%g,Y=%g,R=%g;const ids=[];'
      'function sd(px,py,x1,y1,x2,y2){const dx=x2-x1,dy=y2-y1,L2=dx*dx+dy*dy;'
      'if(L2===0)return Math.hypot(px-x1,py-y1);'
      'let tt=((px-x1)*dx+(py-y1)*dy)/L2;tt=Math.max(0,Math.min(1,tt));'
      'return Math.hypot(px-(x1+tt*dx),py-(y1+tt*dy));}'
      'const TIGHT=%s;' 'for(const id of (TIGHT?[]:(await eda.pcb_PrimitiveLine.getAllPrimitiveId()||[]))){'
      'const o=await eda.pcb_PrimitiveLine.get(id);'
      'if(o&&o.layer!==11&&sd(X,Y,o.startX/MM,o.startY/MM,o.endX/MM,o.endY/MM)<R)ids.push(id);}'
      'for(const id of (await eda.pcb_PrimitiveVia.getAllPrimitiveId()||[])){'
      'const v=await eda.pcb_PrimitiveVia.get(id);'
      'if(v&&Math.hypot(v.x/MM-X,v.y/MM-Y)<R)ids.push(id);}'
      'for(const id of (await eda.pcb_PrimitivePad.getAllPrimitiveId()||[])){'
      'const p=await eda.pcb_PrimitivePad.get(id);'
      'if(p&&Math.hypot(p.x/MM-X,p.y/MM-Y)<R)ids.push(id);}'
      'if(!ids.length)return JSON.stringify({err:"no prims"});'
      'await eda.pcb_SelectControl.doSelectPrimitives(ids);'
      'await new Promise(r=>setTimeout(r,400));'
      'await eda.dmt_EditorControl.zoomToSelectedPrimitives();'
      'await new Promise(r=>setTimeout(r,1200));'
      'await eda.pcb_SelectControl.clearSelected();'
      'await new Promise(r=>setTimeout(r,600));'
      'const img=await eda.dmt_EditorControl.getCurrentRenderedAreaImage();'
      'if(!img)return JSON.stringify({err:"noimg"});'
      'const buf=await img.arrayBuffer();'
      'let bin="";const bytes=new Uint8Array(buf);'
      'for(let i=0;i<bytes.length;i++)bin+=String.fromCharCode(bytes[i]);'
      'return JSON.stringify({b64:btoa(bin),n:ids.length});') % (BOARD, X, Y, R, ('true' if os.environ.get('RA_TIGHT')=='1' else 'false'))
out = run_js(js)
try:
    v = json.loads(out)
    if isinstance(v, str): v = json.loads(v)
    if "b64" in v:
        outd = os.path.join(S, "_out")
        os.makedirs(outd, exist_ok=True)
        path = os.path.join(outd, OUT + ".png")
        io.open(path, "wb").write(base64.b64decode(v["b64"]))
        print("SAVED", path, "prims:", v["n"])
    else:
        print("FAIL", str(v)[:200])
except Exception as e:
    print("ERR", str(e), out[:200])
