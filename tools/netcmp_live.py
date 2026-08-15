# -*- coding: utf-8 -*-
# [来源] 本工具产出于一个真实 PCB 工程的 AI 自动化画板实践, 已脱敏后开源 — easyeda-agent-toolkit
"""在线逐脚网表比对: 直接读 PCB 实况(designator.pin→net) 与 .tel 源网表逐脚对齐。

与 compare_netlist.py 的区别: 这个不需要先导出成品网表, 直接经桥读板上真值,
适合布线/手术之后做"有没有把网表改坏"的回归校验。

用法: python netcmp_live.py <parentBoardName> <源网表.tel>"""
import json, io, os, sys, subprocess, re, collections

# 中文 Windows 控制台默认 GBK, 打印中文/✓✗ 会抛 UnicodeEncodeError 直接崩脚本
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
S = os.path.dirname(os.path.abspath(__file__))
os.makedirs(os.path.join(S, "eda_jobs"), exist_ok=True)
if len(sys.argv) < 3:
    print(__doc__)
    sys.exit(1)
B = sys.argv[1]
TEL = sys.argv[2]

def run_js(js, timeout_s=900):
    p = os.path.join(S, "eda_jobs", "_ncl_tmp.js")
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
        'await new Promise(r=>setTimeout(r,2000));' % B)

# ---- PCB 实况 ----
live = run_js(OPEN + '''
const out=[];
for(const id of (await eda.pcb_PrimitiveComponent.getAllPrimitiveId()||[])){
  const c=await eda.pcb_PrimitiveComponent.get(id);
  if(!c)continue;
  let pins=[];
  try{
    const ps=await eda.pcb_PrimitiveComponent.getAllPinsByPrimitiveId(id)||[];
    for(const p of ps)pins.push([String(p.padNumber!==undefined?p.padNumber:(p.pinNumber!==undefined?p.pinNumber:"")),p.net||""]);
  }catch(e){}
  out.push([c.designator||"",pins]);
}
return JSON.stringify(out);''')
if not isinstance(live, list):
    print("[ABORT] 取板数据失败(板名对不对? 桥通不通? 嘉立创开着吗):", str(live)[:200]); sys.exit(1)
pcb = {}
for (des, pins) in live:
    for (pn, net) in pins:
        pcb[(des, str(pn))] = net
print("[pcb] 组件 %d, 引脚 %d" % (len(live), len(pcb)))

# ---- 源 .tel ----
txt = io.open(TEL, encoding="utf-8", errors="replace").read()
m = re.search(r"\$NETS(.*?)(\$END|\Z)", txt, re.S)
sec = m.group(1)
src = {}
netpins = collections.defaultdict(list)
cur_net, buf = None, ""
for raw in sec.splitlines():
    line = raw.strip()
    if not line: continue
    buf += " " + line
    if line.endswith(","): continue
    stmt = buf.strip().rstrip(";").strip()
    buf = ""
    if ";" in stmt:
        pass
    m2 = re.match(r"^'?([^;']+)'?\s*;\s*(.*)$", stmt)
    if not m2: continue
    net = m2.group(1).strip().strip("'")
    pins = m2.group(2).replace(",", " ").split()
    for p in pins:
        if "." in p:
            des, pn = p.rsplit(".", 1)
            src[(des, pn)] = net
            netpins[net].append(p)
print("[src] 网络 %d, 引脚 %d" % (len(netpins), len(src)))

# ---- 比对 ----
missing_on_pcb = [k for k in src if k not in pcb]
extra_on_pcb = [k for k in pcb if k not in src]
mismatch = [(k, src[k], pcb[k]) for k in src if k in pcb and (pcb[k] or "") != src[k]]
print("[cmp] 源有PCB无: %d, PCB有源无: %d, 网络不一致: %d" % (len(missing_on_pcb), len(extra_on_pcb), len(mismatch)))
for k in missing_on_pcb[:10]: print("   缺:", k, "→", src[k])
for k in extra_on_pcb[:10]: print("   多:", k, "net=", pcb[k])
for (k, s, p) in mismatch[:15]: print("   异:", k, "源=", s, "板=", p)
if not missing_on_pcb and not mismatch:
    print("[cmp] ✅ 逐脚一致 (%d 脚全对)" % len(src))
