# -*- coding: utf-8 -*-
# [来源] 本工具产出于一个真实 PCB 工程的 AI 自动化画板实践, 已脱敏后开源 — easyeda-agent-toolkit
"""
EasyEDA Pro 控制器 — 通过 easyeda-api-skill 的 WebSocket Bridge 向嘉立创发送 JS 代码。
支持多窗口(多开的嘉立创各注册一个 windowId)。

链路: 本脚本 --HTTP--> Bridge(localhost:49620-49629) --WS--> 嘉立创EDA Pro(装 run-api-gateway.eext)

用法:
  python eda_bridge.py health                       # Bridge / 嘉立创连接状态
  python eda_bridge.py windows                       # 列出所有已连接的嘉立创窗口
  python eda_bridge.py select <windowId>             # 设为活动窗口
  python eda_bridge.py exec "<js>" [windowId]        # 执行 JS(可指定窗口)
  python eda_bridge.py run <job.js> [windowId]       # 执行 JS 文件(可指定窗口)
仅用标准库(urllib)。所有请求 30s 超时(防卡死)。
"""
import sys
import json
import urllib.request
import urllib.error

# 中文 Windows 控制台默认 GBK, 打印中文/✓✗ 会抛 UnicodeEncodeError 直接崩脚本
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PORT_RANGE = range(49620, 49630)
TIMEOUT = 30  # 秒, 防止请求挂死


def _get(url):
    with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(url, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def find_bridge():
    for port in PORT_RANGE:
        try:
            info = _get(f"http://localhost:{port}/health")
            if info.get("service") == "easyeda-bridge":
                return port, info
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            continue
    return None, None


def health():
    port, info = find_bridge()
    if not port:
        print("[ERR] 未找到 Bridge (端口 49620-49629 无响应)。")
        print("      先在官方 easyeda-api-skill 目录下跑 `npm run server`。")
        print("      仓库: https://github.com/easyeda/easyeda-api-skill")
        return 2
    print(f"[Bridge] 端口 {port}  status={info.get('status')}  窗口数={info.get('edaWindowCount')}")
    if info.get("edaConnected"):
        print(f"[嘉立创] 已连接  活动窗口={info.get('activeWindowId')}")
        return 0
    print("[嘉立创] 未连接 — 在嘉立创装并打开扩展 run-api-gateway.eext")
    print("         (市场: https://ext.lceda.cn/item/oshwhub/run-api-gateway)")
    return 1


def list_windows():
    port, _ = find_bridge()
    if not port:
        print("[ERR] 未找到 Bridge。")
        return 2
    data = _get(f"http://localhost:{port}/eda-windows")
    print(f"已连接窗口 {data.get('count', 0)} 个, 活动窗口={data.get('activeWindowId')}:")
    for w in data.get("windows", []):
        mark = " *活动" if w.get("active") else ""
        print(f"   - {w.get('windowId')}  connected={w.get('connected')}{mark}")
    return 0


def select_window(window_id):
    port, _ = find_bridge()
    if not port:
        print("[ERR] 未找到 Bridge。")
        return 2
    try:
        res = _post(f"http://localhost:{port}/eda-windows/select", {"windowId": window_id})
        print(json.dumps(res, ensure_ascii=False))
        return 0
    except urllib.error.HTTPError as e:
        print(f"[HTTP {e.code}] {e.read().decode('utf-8','replace')}")
        return 1


def execute(code, window_id=None):
    port, info = find_bridge()
    if not port:
        print("[ERR] 未找到 Bridge。")
        return None
    if not info.get("edaConnected"):
        print("[ERR] 嘉立创未连接 — 装扩展并打开嘉立创后重试。")
        return None
    payload = {"code": code}
    if window_id:
        payload["windowId"] = window_id
    try:
        res = _post(f"http://localhost:{port}/execute", payload)
    except urllib.error.HTTPError as e:
        print(f"[HTTP {e.code}] {e.read().decode('utf-8','replace')}")
        return None
    # Bridge 返回 {success, result, windowId} 或 {success:false, error}
    if isinstance(res, dict) and res.get("success") is False:
        print(f"[EDA ERROR] {res.get('error')}")
    else:
        out = res.get("result") if isinstance(res, dict) else res
        print(json.dumps(out, ensure_ascii=False, indent=2))
    return res


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd = sys.argv[1]
    if cmd == "health":
        return health()
    if cmd == "windows":
        return list_windows()
    if cmd == "select" and len(sys.argv) >= 3:
        return select_window(sys.argv[2])
    if cmd == "exec" and len(sys.argv) >= 3:
        execute(sys.argv[2], sys.argv[3] if len(sys.argv) >= 4 else None)
        return 0
    if cmd == "run" and len(sys.argv) >= 3:
        with open(sys.argv[2], "r", encoding="utf-8") as f:
            execute(f.read(), sys.argv[3] if len(sys.argv) >= 4 else None)
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
