# -*- coding: utf-8 -*-
# [来源] 本工具产出于一个真实 PCB 工程的 AI 自动化画板实践, 已脱敏后开源 — easyeda-agent-toolkit
"""
.tel(嘉立创EDA专业版导出网表) + BOM(立创料号) → .json(扩展 eext-generate-schematic-from-netlist 可导入)

背景: 扩展 doc/tutorial.md 已证实, 库匹配只认 props["Supplier Part"](立创料号 C-number),
      调用 eda.lib_Device.getByLcscIds(料号) 查库放符号; device_name/Footprint 不参与匹配。
      故必须给每个器件注入正确料号, 否则导入报 "no component placed"。

输出格式(对齐官方 example/netlist_example.json):
{
  "gge1": {
    "props": {"Designator","device_name","value","Supplier Part"},
    "pins":  {"<引脚号>": "<网络名>"}
  }, ...
}

料号匹配策略(三级, 稳健):
  1) 精确位号: 解析 BOM Designator 列(逗号列表 + "R01-R08"范围; 跳过"..."省略号)→ 位号→料号
  2) 封装+数值: BOM 行的 (封装类型, 数值token) → 料号 (解决 BOM 位号简写/省略号漏配)
  3) 封装唯一: 某封装类型在 BOM 只有一个料号 → 直接用
匹配不到的器件会列出告警, 绝不静默填错料号。

用法: python tel2json_netlist.py <in.tel> <out.json> --bom <bom.csv> [--override over.json]
      --override: {位号: 料号} 手工指定, 优先级最高(用于 BOM/.tel 封装名不一致的连接器等)
"""
import sys
import re
import csv
import json
import argparse

# 中文 Windows 控制台默认 GBK, 打印中文/✓✗ 会抛 UnicodeEncodeError 直接崩脚本
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# ---------- .tel 解析 ----------
def _merge_continuations(text):
    return re.sub(r",\s*\n\s*", " ", text)


def _extract_section(text, start_tag, end_tags):
    out, cap = [], False
    for ln in text.splitlines():
        tag = ln.strip()
        if tag == start_tag:
            cap = True
            continue
        if cap and tag in end_tags:
            break
        if cap:
            out.append(ln)
    return "\n".join(out)


def parse_tel(tel_text):
    tel_text = _merge_continuations(tel_text)
    pkg = _extract_section(tel_text, "$PACKAGES", {"$A_PROPERTIES", "$NETS", "$END"})
    net = _extract_section(tel_text, "$NETS", {"$SCHEDULE", "$END"})
    comps = {}
    for line in pkg.splitlines():
        line = line.strip()
        if not line or ";" not in line:
            continue
        left, refs = line.split(";", 1)
        parts = [p.strip() for p in left.split("!")]
        footprint = parts[0] if parts else ""
        value = parts[2].strip().strip("'\"") if len(parts) >= 3 else ""
        for ref in refs.split():
            comps.setdefault(ref, {"footprint": footprint, "value": value, "pins": {}})
    for line in net.splitlines():
        line = line.strip()
        if not line or ";" not in line:
            continue
        net_part, pins_part = line.split(";", 1)
        netname = net_part.strip().strip("'\"")
        for tok in pins_part.split():
            if "." not in tok:
                continue
            ref, pin = tok.rsplit(".", 1)
            comps.setdefault(ref, {"footprint": "", "value": "", "pins": {}})
            comps[ref]["pins"][pin] = netname
    return comps


# ---------- 封装/数值规范化 ----------
def footprint_type(fp):
    fp = fp.strip()
    u = fp.upper()
    if u.startswith("FPC"):
        m = re.search(r"[_-]?S?0*(\d+)P", u)   # 提取脚数: 8P / S08FCA / -20P
        return f"FPC-{int(m.group(1))}P" if m else "FPC"
    # 阻容封装归一: C0402 / R0603 / 0402 / C1206 → 纯数字尺寸(BOM 用"0603", .tel 用"C0603")
    m0 = re.match(r"^[CR]?(\d{4})(?:$|[_\-])", u)
    if m0:
        return m0.group(1)
    m = re.match(r"([A-Za-z]+-?\d+)", fp)
    return m.group(1).upper() if m else u


def value_token(val):
    v = val.strip().strip("'\"").lower()
    v = v.replace("ω", "").replace("Ω", "").replace("µ", "u").replace("μ", "u")
    if v in ("", "{value}"):
        return ""
    m = re.match(r"([\d.]+\s*[a-z]*)", v)
    return m.group(1).replace(" ", "") if m else ""


# ---------- BOM 解析 ----------
def expand_designators(s):
    """BOM Designator 字段 → 位号集合。处理逗号列表 + 'R01-R08'范围; 含 '...' 的跳过。"""
    refs = set()
    s = s.strip().strip("'\"")
    if "..." in s or "…" in s:
        return refs  # 省略号无法可靠展开, 交给封装+数值兜底
    for frag in s.split(","):
        frag = frag.strip()
        if not frag:
            continue
        m = re.match(r"^(.*?)(\d+)\s*-\s*(.*?)(\d+)$", frag)
        if m and m.group(1) == m.group(3):
            pre, a, b = m.group(1), int(m.group(2)), int(m.group(4))
            width = len(m.group(2))
            for i in range(a, b + 1):
                refs.add(f"{pre}{str(i).zfill(width)}")
        else:
            refs.add(frag)
    return refs


def _col(row, *names):
    """按优先级取第一个非空列(兼容不同 BOM 的列名)。"""
    for n in names:
        v = row.get(n)
        if v and v.strip():
            return v.strip()
    return ""


def load_bom(bom_csv):
    precise = {}        # 位号 -> (lcsc, mfr)
    by_ftval = {}       # (ft_type, val_token) -> (lcsc, mfr)
    ft_lcscs = {}       # ft_type -> set(lcsc)
    with open(bom_csv, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            lcsc = _col(row, "Supplier Part", "JLC/LCSC Part #", "LCSC", "LCSC Part", "JLCPCB Part #")
            if not lcsc or not lcsc.upper().startswith("C"):
                continue  # 无立创料号(铜皮等)跳过
            mfr = _col(row, "Manufacturer Part", "MPN", "Comment")
            fp = _col(row, "Footprint", "Package")
            val = _col(row, "Value")
            ft = footprint_type(fp)
            tok = value_token(val)
            by_ftval.setdefault((ft, tok), (lcsc, mfr))
            ft_lcscs.setdefault(ft, set()).add(lcsc)
            for ref in expand_designators(_col(row, "Designator", "Designators")):
                # 不覆盖: BOM 里同一批位号出现在多个变体行时, 保留先出现的那一行
                precise.setdefault(ref, (lcsc, mfr))
    return precise, by_ftval, ft_lcscs


def resolve_part(ref, footprint, value, bom):
    precise, by_ftval, ft_lcscs = bom
    if ref in precise:
        return (*precise[ref], "ref")
    ft = footprint_type(footprint)
    tok = value_token(value)
    if (ft, tok) in by_ftval:
        return (*by_ftval[(ft, tok)], "ft+val")
    if ft in ft_lcscs and len(ft_lcscs[ft]) == 1:
        lcsc = next(iter(ft_lcscs[ft]))
        mfr = next((m for (f, t), (l, m) in by_ftval.items() if l == lcsc), "")
        return (lcsc, mfr, "ft-uniq")
    return (None, None, "MISS")


# ---------- 输出 ----------
def to_extension_json(comps, bom, overrides):
    out = {}
    misses = []
    for i, ref in enumerate(sorted(comps), start=1):
        c = comps[ref]
        if ref in overrides:
            lcsc, mfr, how = overrides[ref], "", "override"
        else:
            lcsc, mfr, how = resolve_part(ref, c["footprint"], c["value"], bom)
        if not lcsc:
            misses.append((ref, c["footprint"], c["value"]))
        out[f"gge{i}"] = {
            "props": {
                "Designator": ref,
                "device_name": mfr or "",
                "value": c["value"] if c["value"] != "{Value}" else "",
                "Supplier Part": lcsc or "",
            },
            "pins": {p: c["pins"][p] for p in sorted(c["pins"], key=lambda x: (len(x), x))},
        }
    return out, misses


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tel")
    ap.add_argument("out_json")
    ap.add_argument("--bom", required=True)
    ap.add_argument("--override", help="JSON: {位号: 料号}, 优先级最高")
    args = ap.parse_args()

    with open(args.tel, "r", encoding="utf-8") as f:
        comps = parse_tel(f.read())
    bom = load_bom(args.bom)
    overrides = {}
    if args.override:
        with open(args.override, "r", encoding="utf-8") as f:
            overrides = json.load(f)

    result, misses = to_extension_json(comps, bom, overrides)
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    n_pin = sum(len(v["pins"]) for v in result.values())
    n_lcsc = sum(1 for v in result.values() if v["props"]["Supplier Part"])
    print(f"[OK] {args.out_json}")
    print(f"     器件 {len(result)} | 引脚 {n_pin} | 已配料号 {n_lcsc}/{len(result)}")
    if misses:
        print(f"     [缺料号 {len(misses)}] (需 --override 手工指定, 不会静默填错):")
        for ref, fp, val in misses:
            print(f"        - {ref:16s} fp={fp} val={val}")


if __name__ == "__main__":
    main()
