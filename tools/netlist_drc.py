# -*- coding: utf-8 -*-
# [来源] 本工具产出于一个真实 PCB 工程的 AI 自动化画板实践, 已脱敏后开源 — easyeda-agent-toolkit
"""网表层自查(离线, 不依赖嘉立创): 单网络(net 只连 1 脚 = 悬空)、重复位号、引脚连接率统计。

在把网表导进嘉立创之前先跑这个, 能挡掉大部分"导进去才发现连错"的返工。

用法:
  python netlist_drc.py <netlist1.json> [netlist2.json ...]
输入格式 = tel2json_netlist.py 的输出(或带 components 外层的成品网表)。
"""
import json
import io
import os
import sys

# 中文 Windows 控制台默认 GBK, 打印中文/✓✗ 会抛 UnicodeEncodeError 直接崩脚本
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def load_container(path):
    raw = json.load(io.open(path, encoding="utf-8"))
    if isinstance(raw, dict) and "components" in raw:
        return raw["components"]
    return raw


def audit(path):
    container = load_container(path)
    net2pins = {}
    desig_count = {}
    npins_total = 0
    npins_connected = 0
    for _, v in container.items():
        if not isinstance(v, dict):
            continue   # 容忍网表里混入 _comment 之类的说明字段
        props = v.get("props", v)
        d = props.get("Designator", "?")
        desig_count[d] = desig_count.get(d, 0) + 1
        # 兼容两种格式: {"pins":{脚:网}} 与成品网表的 {"pinInfoMap":{脚:{"net":网}}}
        pins = v.get("pins")
        if pins is None:
            pins = {pn: pi.get("net") for pn, pi in v.get("pinInfoMap", {}).items()}
        for pn, net in pins.items():
            npins_total += 1
            if net:
                npins_connected += 1
                net2pins.setdefault(net, []).append(f"{d}.{pn}")
    single = {net: ps for net, ps in net2pins.items() if len(ps) == 1}
    dup = {d: c for d, c in desig_count.items() if c > 1}

    print(f"\n## {os.path.basename(path)}")
    print(f"   器件 {len(container)} | 网络 {len(net2pins)} | 引脚 {npins_total}(已连 {npins_connected})")
    print(f"   重复位号: {dup if dup else '无'}")
    print(f"   单网络(只连 1 脚) {len(single)} 个:")
    if single:
        for net, ps in sorted(single.items()):
            print(f"      {net}  ←只有 {ps[0]}")
    else:
        print("      无")
    return len(single) + len(dup)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    bad = 0
    for path in sys.argv[1:]:
        if not os.path.exists(path):
            print(f"\n## {path}: 文件缺失")
            bad += 1
            continue
        bad += audit(path)
    print(f"\n[总计] 可疑项 {bad} 个")
    return 0


if __name__ == "__main__":
    sys.exit(main())
