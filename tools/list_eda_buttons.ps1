# [来源] 本工具产出于一个真实 PCB 工程的 AI 自动化画板实践, 已脱敏后开源 — easyeda-agent-toolkit
# 诊断: 列出 lceda-pro 所有窗口的所有 Button 名(找"导入变更"对话框的确认按钮真实名)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::RootElement
$procs = Get-Process -Name "lceda-pro" -ErrorAction SilentlyContinue
if (-not $procs) { Write-Output "no lceda-pro process"; exit }
$pids = @($procs | ForEach-Object { $_.Id })
$btnCond = New-Object System.Windows.Automation.PropertyCondition(
  [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
  [System.Windows.Automation.ControlType]::Button)
$kids = $root.FindAll([System.Windows.Automation.TreeScope]::Children, [System.Windows.Automation.Condition]::TrueCondition)
foreach ($w in $kids) {
  if ($pids -notcontains $w.Current.ProcessId) { continue }
  $btns = $w.FindAll([System.Windows.Automation.TreeScope]::Descendants, $btnCond)
  if ($btns.Count -gt 0) {
    Write-Output ("=== 窗口[" + $w.Current.Name + "] ControlType=" + $w.Current.ControlType.ProgrammaticName + " 按钮数=" + $btns.Count + " ===")
    foreach ($b in $btns) { $n = $b.Current.Name; if ($n -and $n.Trim()) { Write-Output ("  [" + $n + "]") } }
  }
}
