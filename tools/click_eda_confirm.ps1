# [来源] 本工具产出于一个真实 PCB 工程的 AI 自动化画板实践, 已脱敏后开源 — easyeda-agent-toolkit
# 自动点击嘉立创"导入变更"确认对话框的"应用修改"按钮(UIAutomation, 按按钮名精确点)
# 用法: powershell -ExecutionPolicy Bypass -File click_eda_confirm.ps1 [按钮名] [超时秒]
#   不传按钮名 → 默认用码点构造"应用修改"(避开 PS 5.1 按ANSI读.ps1把中文默认值读乱的坑)
# 返回: CLICKED / NOTFOUND / ERROR; 退出码 0=点到, 1=没找到, 2=错误
param([string]$BtnName = "", [int]$TimeoutSec = 15)
$ErrorActionPreference = "Stop"
# 用格式字符串构造目标名(避开 [char]+[char] 在 PS 里变数值相加的坑, 也避开本文件编码坑):
#   应(5E94)用(7528)修(4FEE)改(6539)
if ([string]::IsNullOrEmpty($BtnName)) {
  $BtnName = "{0}{1}{2}{3}" -f [char]0x5E94, [char]0x7528, [char]0x4FEE, [char]0x6539
}
$suffix = "{0}{1}" -f [char]0x4FEE, [char]0x6539   # 修改 (容错: 名字可能带空格)
if ($TimeoutSec -le 0) { $TimeoutSec = 15 }
try {
  Add-Type -AssemblyName UIAutomationClient
  Add-Type -AssemblyName UIAutomationTypes
  $root = [System.Windows.Automation.AutomationElement]::RootElement
  $procs = Get-Process -Name "lceda-pro" -ErrorAction SilentlyContinue
  if (-not $procs) { Write-Output "NOTFOUND: no lceda-pro process"; exit 1 }
  $pids = @($procs | ForEach-Object { $_.Id })
  $winCond = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::Window)
  # 枚举所有 Button(不靠 NameProperty 精确匹配, 改 PS 内比名字, 最稳)
  $btnTypeCond = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::Button)
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    $windows = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $winCond)
    foreach ($w in $windows) {
      if ($pids -notcontains $w.Current.ProcessId) { continue }
      $btns = $w.FindAll([System.Windows.Automation.TreeScope]::Descendants, $btnTypeCond)
      foreach ($b in $btns) {
        try {
          $nm = $b.Current.Name
          if ([string]::IsNullOrEmpty($nm)) { continue }
          if (($nm -eq $BtnName) -or ($nm.Trim() -eq $BtnName) -or ($nm -like ("*" + $suffix + "*"))) {
            if (-not $b.Current.IsEnabled) { continue }
            $inv = $b.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
            $inv.Invoke()
            Write-Output ("CLICKED: win='" + $w.Current.Name + "' btn='" + $nm + "'")
            exit 0
          }
        } catch {}
      }
    }
    Start-Sleep -Milliseconds 400
  }
  Write-Output ("NOTFOUND: '" + $BtnName + "' button not found within " + $TimeoutSec + "s")
  exit 1
} catch {
  Write-Output ("ERROR: " + $_.Exception.Message)
  exit 2
}
