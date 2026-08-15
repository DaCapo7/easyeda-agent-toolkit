# -*- coding: utf-8 -*-
# [来源] 本工具产出于一个真实 PCB 工程的 AI 自动化画板实践, 已脱敏后开源 — easyeda-agent-toolkit
"""导入忠实度逐脚比对: 源网表(料号+pins) vs 嘉立创导出的成品网表, 查器件遗漏 / 引脚连接不一致。

成品网表怎么来: 在桥里跑
    const f = await eda.sch_ManufactureData.getNetlistFile('out.json');
    await eda.sys_FileSystem.saveFileToFileSystem('C:/tmp/out.json', f);
(保存路径用纯 ASCII, 可免 UI 弹窗)

用法: python compare_netlist.py <源网表.json> <成品网表.json>
"""
import json
import io
import sys

# 中文 Windows 控制台默认 GBK, 打印中文/✓✗ 会抛 UnicodeEncodeError 直接崩脚本
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

if len(sys.argv) < 3:
    print(__doc__)
    sys.exit(1)

SRC, FINAL = sys.argv[1], sys.argv[2]

src = json.load(io.open(SRC, encoding='utf-8'))
final = json.load(io.open(FINAL, encoding='utf-8'))

src_container = src['components'] if isinstance(src, dict) and 'components' in src else src
src_by_d = {}
for k, v in src_container.items():
    if not isinstance(v, dict):
        continue   # 容忍网表里混入 _comment 之类的说明字段
    d = v['props']['Designator']
    pins = v.get('pins')
    if pins is None:
        pins = {pn: pi.get('net') for pn, pi in v.get('pinInfoMap', {}).items()}
    src_by_d[d] = dict(pins)

final_container = final['components'] if isinstance(final, dict) and 'components' in final else final
final_by_d = {}
for k, v in final_container.items():
    if not isinstance(v, dict):
        continue
    d = v['props']['Designator']
    final_by_d[d] = {pn: pi.get('net') for pn, pi in v.get('pinInfoMap', {}).items()}

missing = sorted(set(src_by_d) - set(final_by_d))
extra = sorted(set(final_by_d) - set(src_by_d))
print('源器件', len(src_by_d), '| 成品器件', len(final_by_d))
print('源有成品无:', missing)
print('成品有源无:', extra)

diff = []
for d in src_by_d:
    if d not in final_by_d:
        continue
    for pn, net in src_by_d[d].items():
        fnet = final_by_d[d].get(pn)
        if fnet != net:
            diff.append(f"{d}.{pn}: 源={net} | 成品={fnet}")
print('pin 连接不一致:', len(diff))
for x in diff[:40]:
    print('  ', x)

sys.exit(0 if (not missing and not diff) else 1)
