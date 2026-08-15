REM [来源] 本工具产出于一个真实 PCB 工程的 AI 自动化画板实践, 已脱敏后开源 — easyeda-agent-toolkit
@echo off
chcp 65001 >nul
REM =====================================================================
REM 一键拉起官方 easyeda-api-skill 的 Bridge Server, 并检查嘉立创连接状态
REM 用法: 先把下面的 SKILL_DIR 改成你本机 easyeda-api-skill 的实际目录
REM =====================================================================

set "SKILL_DIR=C:\path\to\easyeda-api-skill"

echo === 启动 EasyEDA Bridge ===
if not exist "%SKILL_DIR%\package.json" (
  echo [ERR] 找不到 %SKILL_DIR%\package.json
  echo       请先把本文件里的 SKILL_DIR 改成 easyeda-api-skill 的真实路径,
  echo       仓库地址: https://github.com/easyeda/easyeda-api-skill
  pause
  exit /b 1
)

cd /d "%SKILL_DIR%"
start "EDA-Bridge" cmd /k "npm run server"
echo Bridge server 已在新窗口启动 (自动占用 49620-49629 中的空闲端口)
echo.
echo === 还需手动: 打开嘉立创EDA专业版, 确保已装并启用扩展 run-api-gateway.eext ===
echo     扩展市场: https://ext.lceda.cn/item/oshwhub/run-api-gateway
timeout /t 4 >nul

REM 检查连接状态 (%~dp0 = 本 .bat 所在目录, 与 eda_bridge.py 同级)
python "%~dp0eda_bridge.py" health
pause
