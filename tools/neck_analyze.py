# -*- coding: utf-8 -*-
# [来源] 本工具产出于一个真实 PCB 工程的 AI 自动化画板实践, 已脱敏后开源 — easyeda-agent-toolkit
"""违例台账: 按网络对/网络参与度统计, 定位需下沉的干线网络. 用法: python neck_analyze.py <board>"""
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

def run_js(js, timeout_s=600):
    p = os.path.join(S, "eda_jobs", "_na_tmp.js")
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

d = run_js(OPEN + '''
const L=await eda.pcb_PrimitiveLine.getAll()||[];
const drc=await eda.pcb_Drc.check(false,false,true);
const viol=[];
for(const cat of (drc||[]))for(const g of (cat.list||[]))for(const e of (g.list||[])){
  const ed=e.explanation&&e.explanation.errData; if(!ed)continue;
  viol.push({o1:ed.obj1,t1:ed.obj1Type,o2:ed.obj2,t2:ed.obj2Type,
    s1:ed.obj1Suffix||"",s2:ed.obj2Suffix||"",lay:(ed.layerIds&&ed.layerIds[0])||0,
    x:ed.position?ed.position.x:0,y:ed.position?ed.position.y:0});
}
return JSON.stringify({lines:L.map(o=>({id:o.primitiveId,n:o.net||""})),viol:viol});''')

if not isinstance(d, dict) or "lines" not in d:
    print("[ABORT] 取板数据失败(板名对不对? 桥通不通? 嘉立创开着吗):", str(d)[:200]); sys.exit(1)
net_of = {o["id"]: o["n"] for o in d["lines"]}
import re
def suf_net(s):
    m = re.match(r"\(([^)]*)\)", s or "")
    return m.group(1) if m else "?"

pair_cnt, net_cnt = {}, {}
for v in d["viol"]:
    n1 = net_of.get(v["o1"]) or suf_net(v["s1"])
    n2 = net_of.get(v["o2"]) or suf_net(v["s2"])
    k = "|".join(sorted([n1, n2]))
    pair_cnt[k] = pair_cnt.get(k, 0) + 1
    for n in (n1, n2):
        net_cnt[n] = net_cnt.get(n, 0) + 1

print(f"== {BOARD} 违例总数 {len(d['viol'])}")
print("-- 网络参与度 Top15:")
for n, c in sorted(net_cnt.items(), key=lambda x: -x[1])[:15]:
    print(f"   {n:14s} {c}")
print("-- 网络对 Top15:")
for k, c in sorted(pair_cnt.items(), key=lambda x: -x[1])[:15]:
    print(f"   {k:30s} {c}")
