# -*- coding: utf-8 -*-
# [来源] 本工具产出于一个真实 PCB 工程的 AI 自动化画板实践, 已脱敏后开源 — easyeda-agent-toolkit
"""从 .json(料号网表) 用 create+wire API 全新生成原理图(已验证: create 放标准库器件、
wire 带 net、同 net 名逻辑连通)。setNetlist 不可用(只设数据不建器件)。

流程: [--clear 先清空] → 网格布局 → 每器件 getByLcscIds(料号,缓存)→create→改位号
       → 每 pin 出短 wire(带 net) → 同 net 名连通。分批防 30s 超时。
用法: python generate_schematic_from_json.py <netlist.json> [--clear] [--batch N] [--test N]
"""
import json
import io
import os
import sys
import subprocess

# 中文 Windows 控制台默认 GBK, 打印中文/✓✗ 会抛 UnicodeEncodeError 直接崩脚本
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

args = sys.argv[1:]
if len(sys.argv) < 2:
    print(__doc__); sys.exit(1)
src = args[0]
CLEAR = '--clear' in args
BATCH = int(args[args.index('--batch') + 1]) if '--batch' in args else 10
TEST = int(args[args.index('--test') + 1]) if '--test' in args else None

COLS, DX, DY, X0, Y0 = 14, 500, 400, 500, 500

raw = json.load(io.open(src, encoding='utf-8'))
container = raw['components'] if isinstance(raw, dict) and 'components' in raw else raw

items = []
for k, v in container.items():
    if not isinstance(v, dict):
        continue   # 容忍网表里混入 _comment 之类的说明字段
    props = v.get('props', v)
    desig = props.get('Designator')
    lcsc = props.get('Supplier Part') or props.get('supplierId')
    if 'pins' in v:
        pins = v['pins']
    else:
        pins = {pn: pi.get('net') for pn, pi in v.get('pinInfoMap', {}).items()}
    if desig and lcsc:
        items.append({'designator': desig, 'lcsc': lcsc, 'pins': pins})

items.sort(key=lambda it: it['designator'])
for i, it in enumerate(items):
    it['x'] = X0 + (i % COLS) * DX
    it['y'] = Y0 + (i // COLS) * DY
if TEST:
    items = items[:TEST]

script_dir = os.path.dirname(os.path.abspath(__file__))
os.makedirs(os.path.join(script_dir, "eda_jobs"), exist_ok=True)
out_js = os.path.join(script_dir, "eda_jobs", "_import_tmp.js")


def run_js(js, label):
    with open(out_js, "w", encoding="utf-8") as f:
        f.write(js)
    print(f"[{label}]", flush=True)
    subprocess.run([sys.executable, os.path.join(script_dir, "eda_bridge.py"), "run", out_js])


print(f"[gen] 器件 {len(items)} | 批大小 {BATCH} | clear={CLEAR}")

if CLEAR:
    run_js(
        "const cs=await eda.sch_PrimitiveComponent.getAll();let n=0;"
        "for(const c of cs){try{await eda.sch_PrimitiveComponent.delete(c.getState_PrimitiveId());n++}catch(e){}}"
        "let wn=0;try{const ws=await eda.sch_PrimitiveWire.getAll();for(const w of ws){try{await eda.sch_PrimitiveWire.delete(w.getState_PrimitiveId());wn++}catch(e){}}}catch(e){}"
        "return {deletedComps:n,deletedWires:wn};",
        "清空原理图",
    )

for bi in range(0, len(items), BATCH):
    batch = items[bi:bi + BATCH]
    js = (
        "const ITEMS=" + json.dumps(batch, ensure_ascii=False) + ";\n"
        "const dc={};let cr=0,wr=0,errs=[];\n"
        "for(const it of ITEMS){\n"
        " if(!(it.lcsc in dc)){try{const d=await eda.lib_Device.getByLcscIds(it.lcsc);dc[it.lcsc]=(d&&d[0])?d[0]:null;}catch(e){dc[it.lcsc]=null;}}\n"
        " const dev=dc[it.lcsc];if(!dev){errs.push(it.designator+':no-dev');continue;}\n"
        " let c;try{c=await eda.sch_PrimitiveComponent.create(dev,it.x,it.y,undefined,0,false,true,true);}catch(e){errs.push(it.designator+':create');continue;}\n"
        " const cid=c.getState_PrimitiveId();\n"
        " try{await eda.sch_PrimitiveComponent.modify(cid,{designator:it.designator});}catch(e){}\n"
        " cr++;\n"
        " let pins;try{pins=await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(cid);}catch(e){continue;}\n"
        " for(const p of pins){const net=it.pins[p.pinNumber];if(!net)continue;const px=p.getState_X(),py=p.getState_Y();let r=0;try{r=p.getState_Rotation();}catch(e){}let ex=px+20,ey=py;if(r===180){ex=px-20;ey=py;}else if(r===90){ex=px;ey=py+20;}else if(r===270){ex=px;ey=py-20;}try{await eda.sch_PrimitiveWire.create([px,py,ex,ey],net);wr++;}catch(e){}}\n"
        "}\n"
        "return {created:cr,wired:wr,errs:errs.slice(0,6)};"
    )
    run_js(js, f"导入 {bi}~{bi + len(batch)}")
