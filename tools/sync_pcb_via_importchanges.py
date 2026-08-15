# -*- coding: utf-8 -*-
# [来源] 本工具产出于一个真实 PCB 工程的 AI 自动化画板实践, 已脱敏后开源 — easyeda-agent-toolkit
"""原理图 → PCB 同步(importChanges + UIAutomation 自动点"应用修改")。

前提: 原理图器件已 addIntoPcb=true(generate_schematic_from_json.py 默认就带); 嘉立创已开着对应工程。
用法: python sync_pcb_via_importchanges.py <BoardName> [等对话框秒数, 默认 300]
     例: python sync_pcb_via_importchanges.py Board1

关键经验(全部实测, 每条都踩过):
  - importChanges 返回 true 之后, "确认导入信息"对话框可能要**好几分钟**才渲染出来;
    15s/40s 的看门必然误判 NOTFOUND。所以默认等 300s, 期间持续扫按钮。
  - 触发后只用裸 getAll() 轮询计数, **不要再 openDocument+activate**——
    放置过程中重新激活文档会打断放置(器件停在中途)。
  - PS 点击脚本**不传中文参数**(Windows subprocess 传中文会乱码), 由脚本内用码点构造"应用修改"。
  - 连续多次重触发会把上一个对话框冲掉, 看起来像"不弹框"。慢, 但要一次一次来。
"""
import sys, os, json, subprocess, time

# 控制台用 GBK 时, 打印 ✓/✗ 等非 GBK 字符会崩溃 -> 强制 stdout 用 utf-8(替换不可编码字符)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
JOBS = os.path.join(SCRIPTS, "eda_jobs")
os.makedirs(JOBS, exist_ok=True)
if len(sys.argv) < 2:
    print(__doc__); sys.exit(1)
board = sys.argv[1]
DIALOG_WAIT = int(sys.argv[2]) if len(sys.argv) > 2 else 300


def run_js(js):
    p = os.path.join(JOBS, "_sync_tmp.js")
    open(p, "w", encoding="utf-8").write(js)
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "eda_bridge.py"), "run", p],
                       capture_output=True, text=True, encoding="utf-8")
    s = (r.stdout or "") + (r.stderr or "")
    i, j = s.find("{"), s.rfind("}")
    try:
        return json.loads(s[i:j + 1])
    except Exception:
        return {"_raw": s[:300]}


print(f"\n===== PCB 同步 {board} =====")
info = run_js(f'const i=await eda.dmt_Board.getBoardInfo("{board}");'
              f'return {{pcb:i.pcb.uuid, sch:i.schematic.uuid}};')
pcb_uuid, sch_uuid = info.get("pcb"), info.get("sch")
if not pcb_uuid:
    print("[ABORT] 取板信息失败:", info); sys.exit(1)

# 激活 PCB 一次 + 记录导入前器件数(此后不再 openDocument)
before = run_js(f'const t=await eda.dmt_EditorControl.openDocument("{pcb_uuid}");'
                f'await eda.dmt_EditorControl.activateDocument(t);'
                f'return {{n:(await eda.pcb_PrimitiveComponent.getAll()).length}};').get("n")
print(f"[导入前] PCB 器件 {before}")

# 触发 importChanges(PCB 已激活; 弹"应用修改"框)
ret = run_js(f'return {{ret: await eda.pcb_Document.importChanges("{sch_uuid}")}};').get("ret")
print(f"[importChanges] 返回 {ret}")

# UIAutomation 自动点"应用修改"(不传中文按钮名, 靠 PS 脚本内用码点构造; 只传超时秒数)
print(f"[等待对话框] 最多 {DIALOG_WAIT}s (本版 EDA 渲染这个框可能要几分钟, 别提前掐)")
ps = subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File",
                     os.path.join(SCRIPTS, "click_eda_confirm.ps1"), "-TimeoutSec", str(DIALOG_WAIT)],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=DIALOG_WAIT + 60)
clk = [ln for ln in ((ps.stdout or "") + (ps.stderr or "")).splitlines()
       if ln.startswith(("CLICKED", "NOTFOUND", "ERROR"))]
print(f"[自动点击] {clk[-1] if clk else (ps.stdout or ps.stderr)[:120]}")

# 裸 getAll() 轮询至稳定(不 openDocument, 避免打断放置)
last, stable = -1, 0
for _ in range(24):
    time.sleep(3)
    n = run_js('return {n:(await eda.pcb_PrimitiveComponent.getAll()).length};').get("n")
    if n == last and n and n > (before or 0):
        stable += 1
        if stable >= 2:
            break
    else:
        stable = 0
    last = n
ok = last and last > (before or 0)
print(f"[导入后] PCB 器件 {last}  ({'✓ 增量成功' if ok else '✗ 未增加(查对话框/按钮名/是否打断)'})")
sys.exit(0 if ok else 1)
