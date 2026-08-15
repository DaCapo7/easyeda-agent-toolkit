# -*- coding: utf-8 -*-
# [来源] 本工具产出于一个真实 PCB 工程的 AI 自动化画板实践, 已脱敏后开源 — easyeda-agent-toolkit
"""违例线段降宽: 把 DRC 违例涉及的 Track 中"比目标线宽更粗"的统一降到目标线宽, 靠腾出的间隙消违例.

适用前提: 那些粗线本来就是画板时留的余量(载流早已够), 降宽不影响电气。
这一招在真实项目里一次把 397 条间距违例打到 267, 是所有几何手术里性价比最高的。

用法: python width_cut.py <parentBoardName> [目标线宽mil, 默认 3.5433 = 0.09mm]"""
import json, io, os, sys, subprocess

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
W = float(sys.argv[2]) if len(sys.argv) > 2 else 3.5433   # mil; 3.5433mil = 0.09mm

def run_js(js, timeout_s=600):
    p = os.path.join(S, "eda_jobs", "_wc_tmp.js")
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

d = run_js(OPEN + '''
const L=await eda.pcb_PrimitiveLine.getAll()||[];
const drc=await eda.pcb_Drc.check(false,false,true);
const ids=new Set();
for(const cat of (drc||[]))for(const g of (cat.list||[]))for(const e of (g.list||[])){
  const ed=e.explanation&&e.explanation.errData; if(!ed)continue;
  if(ed.obj1Type==="Track")ids.add(ed.obj1);
  if(ed.obj2Type==="Track")ids.add(ed.obj2);
}
return JSON.stringify({viol:[...ids],
 lines:L.map(o=>({id:o.primitiveId,n:o.net||"",w:o.lineWidth,l:o.layer}))});''')

if not isinstance(d, dict) or "lines" not in d:
    print("[ABORT] 取板数据失败(板名对不对? 桥通不通? 嘉立创开着吗):", str(d)[:200]); sys.exit(1)
lines = {o["id"]: o for o in d["lines"]}
fat = [i for i in d["viol"] if i in lines and lines[i]["w"] > W + 0.01]
nets = {}
for i in fat: nets[lines[i]["n"]] = nets.get(lines[i]["n"], 0) + 1
print(f"[{BOARD}] 违例Track {len(d['viol'])} 条, 其中粗线(> {W}mil) {len(fat)} 条")
print(f"  按网络: {json.dumps(nets, ensure_ascii=False)}")
if not fat:
    print("无粗线可降"); sys.exit(0)

CH = 150
done = 0
for c0 in range(0, len(fat), CH):
    chunk = fat[c0:c0+CH]
    ops = "".join(f'try{{const r=await eda.pcb_PrimitiveLine.modify("{i}",{{lineWidth:{W}}});if(r)ok++;}}catch(e){{errs.push((""+e).slice(0,60));}}' for i in chunk)
    r = run_js(OPEN + "let ok=0;const errs=[];" + ops + 'await eda.pcb_Document.save();return JSON.stringify({ok:ok,errN:errs.length,errs:errs.slice(0,3)});')
    print(f"  [chunk] {r}")
    done += (r.get("ok", 0) if isinstance(r, dict) else 0)
print(f"[done] 降宽 {done}/{len(fat)} 条至 {W}mil(0.09mm)")
