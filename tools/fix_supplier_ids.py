# -*- coding: utf-8 -*-
# [来源] 本工具产出于一个真实 PCB 工程的 AI 自动化画板实践, 已脱敏后开源 — easyeda-agent-toolkit
"""读板的 .json(位号→立创料号), 经 Bridge 批量 modify 修正器件 SupplierId(供应商料号)。
修复嘉立创 DRC "供应商不符": 网表重建导入后 SupplierId 被设成"MPN.1"而非立创 C 料号。
用法: python fix_supplier_ids.py <netlist.json> [批大小, 默认40]
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
with open(json_path, encoding="utf-8") as f:
    nl = json.load(f)

mapping = {}
for v in nl.values():
    if not isinstance(v, dict):
        continue   # 容忍网表里混入 _comment 之类的说明字段
    d = v["props"]["Designator"]
    sp = (v["props"].get("Supplier Part") or "").strip()
    if sp:
        mapping[d] = sp

# 分批 modify(每批 <30s 防 Bridge 超时), 多批连跑
items = list(mapping.items())
BATCH = int(sys.argv[2]) if len(sys.argv) > 2 else 40
script_dir = os.path.dirname(os.path.abspath(__file__))
jobs_dir = os.path.join(script_dir, "eda_jobs")
os.makedirs(jobs_dir, exist_ok=True)
out_js = os.path.join(jobs_dir, "_fixsupplier_tmp.js")
print("[gen] 料号映射", len(mapping), "个 | 分批大小", BATCH)
for i in range(0, len(items), BATCH):
    batch = dict(items[i:i + BATCH])
    js = (
        "const M=" + json.dumps(batch, ensure_ascii=False) + ";\n"
        "const cs=await eda.sch_PrimitiveComponent.getAll();let n=0;\n"
        "for(const c of cs){let d;try{d=c.getState_Designator()}catch(e){continue}\n"
        "if(d&&M[d]){await eda.sch_PrimitiveComponent.modify(c.getState_PrimitiveId(),{supplier:'LCSC',supplierId:M[d]});n++}}\n"
        "return {batchFixed:n};"
    )
    with open(out_js, "w", encoding="utf-8") as f:
        f.write(js)
    print(f"[批 {i // BATCH + 1}] 位号 {i}~{i + len(batch)}:", flush=True)
    subprocess.run([sys.executable, os.path.join(script_dir, "eda_bridge.py"), "run", out_js])
