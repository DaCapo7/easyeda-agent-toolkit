# -*- coding: utf-8 -*-
# [来源] 本工具产出于一个真实 PCB 工程的 AI 自动化画板实践, 已脱敏后开源 — easyeda-agent-toolkit
"""读板 .json(每器件已用引脚), 经 Bridge 给未用引脚打 NC 标记(setState_NoConnected(true).done())。
修嘉立创 DRC "引脚悬空,建议放置非连接标识"警告。分批防超时。
用法: python fix_nc.py <netlist.json> [batch]
"""
import json
import sys
import os
import subprocess

# 中文 Windows 控制台默认 GBK, 打印中文/✓✗ 会抛 UnicodeEncodeError 直接崩脚本
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

if len(sys.argv) < 2:
    print(__doc__); sys.exit(1)
json_path = sys.argv[1]
BATCH = int(sys.argv[2]) if len(sys.argv) > 2 else 40
with open(json_path, encoding="utf-8") as f:
    nl = json.load(f)

# 位号 -> 已用引脚号列表(.json 的 pins keys)
used = {}
for v in nl.values():
    if not isinstance(v, dict):
        continue   # 容忍网表里混入 _comment 之类的说明字段
    d = v["props"]["Designator"]
    used[d] = list(v["pins"].keys())

items = list(used.items())
script_dir = os.path.dirname(os.path.abspath(__file__))
jobs_dir = os.path.join(script_dir, "eda_jobs")
os.makedirs(jobs_dir, exist_ok=True)
out_js = os.path.join(jobs_dir, "_fixnc_tmp.js")
print("[gen] 器件", len(used), "| 分批", BATCH)
for i in range(0, len(items), BATCH):
    batch = dict(items[i:i + BATCH])
    js = (
        "const U=" + json.dumps(batch) + ";\n"
        "const cs=await eda.sch_PrimitiveComponent.getAll();let nc=0;\n"
        "for(const c of cs){let d;try{d=c.getState_Designator()}catch(e){continue}\n"
        "if(!d||!U[d])continue;const used=new Set(U[d]);\n"
        "let pins;try{pins=await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(c.getState_PrimitiveId())}catch(e){continue}\n"
        "for(const p of pins){if(!used.has(p.pinNumber)&&!p.getState_NoConnected()){await p.setState_NoConnected(true).done();nc++}}}\n"
        "return {ncSet:nc};"
    )
    with open(out_js, "w", encoding="utf-8") as f:
        f.write(js)
    print(f"[批 {i // BATCH + 1}] 器件 {i}~{i + len(batch)}:", flush=True)
    subprocess.run([sys.executable, os.path.join(script_dir, "eda_bridge.py"), "run", out_js])
