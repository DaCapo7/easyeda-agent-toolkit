# -*- coding: utf-8 -*-
# [来源] 本工具产出于一个真实 PCB 工程的 AI 自动化画板实践, 已脱敏后开源 — easyeda-agent-toolkit
"""安全自动重灌: 桥激活目标板 → 校验EDA确为前台窗口后才发 Shift+B → 等待 → 桥保存。
前台校验失败则中止(绝不把按键发进别的窗口)。用法: python repour_safe.py <board>"""
import json, io, os, sys, subprocess, time

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

def run_js(js, timeout_s=300, retries=2):
    p = os.path.join(S, "eda_jobs", "_rps_tmp.js")
    io.open(p, "w", encoding="utf-8").write(js)
    for a in range(retries + 1):
        try:
            r = subprocess.run([sys.executable, os.path.join(S, "eda_bridge.py"), "run", p],
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_s)
            v = json.loads((r.stdout or "").strip())
            if isinstance(v, str): v = json.loads(v)
            return v
        except Exception:
            time.sleep(3)
    return {"err": "fail"}

OPEN = ('const pcbs=await eda.dmt_Pcb.getAllPcbsInfo()||[];'
        'const hit=pcbs.find(p=>p.parentBoardName==="%s");'
        'if(!hit)return JSON.stringify({err:"nf"});'
        'let t=await eda.dmt_EditorControl.openDocument(hit.uuid);'
        'await eda.dmt_EditorControl.activateDocument(t);'
        'await new Promise(r=>setTimeout(r,2000));' % BOARD)

r = run_js(OPEN + 'return JSON.stringify({activated:true});')
print("[activate]", r)
if not (isinstance(r, dict) and r.get("activated")):
    sys.exit("激活失败, 中止")

PS = r'''
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName Microsoft.VisualBasic
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class FG {
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
}
"@
$eda = Get-Process | Where-Object { ($_.ProcessName -match 'lceda|jlceda|easyeda') -and $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $eda) { Write-Output "NO_EDA"; exit 1 }
[Microsoft.VisualBasic.Interaction]::AppActivate($eda.Id)
Start-Sleep -Milliseconds 900
$h = [FG]::GetForegroundWindow()
$fpid = 0
[void][FG]::GetWindowThreadProcessId($h, [ref]$fpid)
$edapids = (Get-Process | Where-Object { $_.ProcessName -match 'lceda|jlceda|easyeda' }).Id
if ($edapids -notcontains [int]$fpid) { Write-Output ("FOREGROUND_NOT_EDA pid=" + $fpid); exit 2 }
[System.Windows.Forms.SendKeys]::SendWait('+b')
Start-Sleep -Seconds 12
Write-Output "SENT_OK"
'''
pp = os.path.join(S, "_repour_safe.ps1")
io.open(pp, "w", encoding="utf-8-sig").write(PS)
p = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", pp],
                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
out = (p.stdout or "").strip()
print("[sendkeys]", out)
if "SENT_OK" not in out:
    sys.exit("按键未发送(前台不是EDA或无窗口), 已安全中止")

time.sleep(6)
r = run_js(OPEN + 'await eda.pcb_Document.save(); return JSON.stringify({saved:true});')
print("[save]", r)
