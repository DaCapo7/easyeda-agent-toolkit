# -*- coding: utf-8 -*-
# [来源] 本工具产出于一个真实 PCB 工程的 AI 自动化画板实践, 已脱敏后开源 — easyeda-agent-toolkit
r"""导出 SMT 下单文件: BOM + 贴片坐标(PickAndPlace), 用 base64 回传保真.

两个坑写在这里省得再踩:
  1) 嘉立创导出的所谓 "csv" 实为 UTF-16LE + TAB 分隔, 直接按 utf-8/逗号解析会乱;
  2) 桥的 stdout 在中文 Windows 上会被 GBK 折腾, 所以文件内容一律 base64 过桥再落盘。
本脚本只负责"原样取回 + 结构自检"(行数/列名/单位量级), 具体拆分与校验请另写下游脚本。
产物: tools/_mfg_out/<label>_BOM_raw.tsv 、<label>_CPL_mm_raw.tsv 、<label>_CPL_mil_raw.tsv

用法: python export_mfg.py <parentBoardName> <label>"""
import json, io, os, sys, subprocess, base64

# 中文 Windows 控制台默认 GBK, 打印中文/✓✗ 会抛 UnicodeEncodeError 直接崩脚本
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
S = os.path.dirname(os.path.abspath(__file__))
os.makedirs(os.path.join(S, "eda_jobs"), exist_ok=True)
if len(sys.argv) < 3:
    print(__doc__); sys.exit(1)
BOARD, LABEL = sys.argv[1], sys.argv[2]
OUTD = os.path.join(S, "_mfg_out")
os.makedirs(OUTD, exist_ok=True)

JS = r'''
const pcbs=await eda.dmt_Pcb.getAllPcbsInfo()||[];
const hit=pcbs.find(p=>p.parentBoardName==="%BOARD%");
if(!hit)return JSON.stringify({err:"nf"});
const t=await eda.dmt_EditorControl.openDocument(hit.uuid);
await eda.dmt_EditorControl.activateDocument(t);
await new Promise(r=>setTimeout(r,2500));
const M=eda.pcb_ManufactureData;
async function b64(f){const buf=await f.arrayBuffer();const b=new Uint8Array(buf);let s='';const CH=8192;
  for(let i=0;i<b.length;i+=CH){s+=String.fromCharCode.apply(null,b.subarray(i,i+CH));}return btoa(s);}
const out={};
try{const f=await M.getBomFile("%LABEL%_BOM","csv","嘉立创EDA专业版BOM模板.xlsx");out.bom=await b64(f);}catch(e){out.bom_err=String(e).slice(0,180);}
try{const f=await M.getPickAndPlaceFile("%LABEL%_CPL","csv","mm");out.pp_mm=await b64(f);}catch(e){out.pp_mm_err=String(e).slice(0,180);}
try{const f=await M.getPickAndPlaceFile("%LABEL%_CPL","csv","mil");out.pp_mil=await b64(f);}catch(e){out.pp_mil_err=String(e).slice(0,180);}
return JSON.stringify(out);
'''.replace("%BOARD%", BOARD).replace("%LABEL%", LABEL)

p = os.path.join(S, "eda_jobs", "_expmfg_tmp.js")
io.open(p, "w", encoding="utf-8").write(JS)
r = subprocess.run([sys.executable, os.path.join(S, "eda_bridge.py"), "run", p],
                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
raw = (r.stdout or "").strip()
try:
    d = json.loads(raw); d = json.loads(d) if isinstance(d, str) else d
except Exception as e:
    print("PARSE-FAIL", e); print(ascii(raw[:600])); sys.exit(1)

def decode_txt(b):
    # 嘉立创 csv = UTF-16LE(BOM). 兜底 utf-8-sig
    if b[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return b.decode("utf-16")
    try:
        return b.decode("utf-8-sig")
    except Exception:
        return b.decode("utf-16", errors="replace")

def sniff(b, tag, fn):
    with open(os.path.join(OUTD, fn), "wb") as fh: fh.write(b)
    txt = decode_txt(b)
    lines = [ln for ln in txt.splitlines() if ln.strip() != ""]
    delim = "\t" if ("\t" in lines[0]) else ","
    rows = [ln.split(delim) for ln in lines]
    print(f"  [{tag}] bytes={len(b)} 行={len(rows)} 分隔={'TAB' if delim==chr(9) else 'COMMA'} 列={len(rows[0]) if rows else 0}")
    if rows:
        print(f"    列名: {rows[0]}")
        for rr in rows[1:3]:
            cells = [(c[:40]+'...' if len(c) > 40 else c) for c in rr]
            print(f"    行: {cells}")
    return rows, delim

print(f"== {LABEL} ({BOARD})")
if "bom" in d:
    sniff(base64.b64decode(d["bom"]), "BOM", f"{LABEL}_BOM_raw.tsv")
else:
    print("  BOM ERR:", d.get("bom_err"))
for uk, fn in (("pp_mm", f"{LABEL}_CPL_mm_raw.tsv"), ("pp_mil", f"{LABEL}_CPL_mil_raw.tsv")):
    if uk in d:
        rows, delim = sniff(base64.b64decode(d[uk]), uk, fn)
        if len(rows) > 1:
            import re
            nums = [x for x in rows[1] if re.match(r"^-?\d+\.?\d+$", x.strip())]
            print(f"    {uk} 首行数值列: {nums}")
    else:
        print(f"  {uk} ERR:", d.get(uk+"_err"))
