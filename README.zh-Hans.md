[English](./README.md) | 简体中文

# easyeda-agent-toolkit

**嘉立创 EDA 专业版 × AI 编码代理的自动化画板工具箱与教程（基于官方 easyeda-api-skill 桥）**

一套 Python / PowerShell 脚本，让 Claude Code 这类 AI 编码代理能够操作嘉立创 EDA 专业版：
转网表、生成原理图、同步到 PCB、跑 DRC、批量改线宽与几何、导下单文件。
有几个操作确实没有 API 可达，文档里会明确指出，并说明本工具箱采用的界面自动化替代方案。

---

## 目录

- [适用范围](#适用范围)
- [与官方 easyeda-api-skill 的关系](#与官方-easyeda-api-skill-的关系)
- [环境准备](#环境准备)
- [第一条命令](#第一条命令)
- [主线流程：从网表到下单文件](#主线流程从网表到下单文件)
- [工具清单](#工具清单)
- [值得先读的坑](#值得先读的坑)
- [目录结构](#目录结构)
- [声明](#声明)

---

## 适用范围

**这是什么。** 让 AI 代理执行嘉立创 EDA 专业版里重复性工作的脚本——批量改属性、批量挪几何、
批量校验、导文件——以及一份官方文档未覆盖的 API 行为记录。

**这不是什么。** 不是自动布线器，也不是"描述需求就出板子"的系统。
需要工程判断的决策——拥堵区怎么收口、板框怎么排、某条网该走哪层——手工仍然更快。
在窄缝区继续跑脚本的边际收益是负的，交互式编辑通常更快。
可行的分工是：脚本负责批量重建与校验，人负责难处理的区域。

**文档为什么重要。** 嘉立创 EDA 专业版有几类反直觉的 API 行为：
写属性返回成功但重启后还原、DRC 完全不检查连通性、确认对话框可能要几分钟才渲染出来、
共线同网的线段在创建时会被合并。这些官方参考文档里没有。
`docs/铁律与坑.md` 收集了这些行为，下面的[值得先读的坑](#值得先读的坑)挑出了最容易耗掉一整天的那些。

---

## 与官方 easyeda-api-skill 的关系

```
   AI 代理                  本仓库                    官方 easyeda-api-skill        嘉立创EDA专业版
 (Claude Code 等)        (Python/PS 脚本)               (Node 桥服务)            (装 run-api-gateway 扩展)
      │                       │                              │                            │
      │   写一段 JS 作业        │                              │                            │
      ├──────────────────────>│                              │                            │
      │                       │  HTTP POST /execute          │                            │
      │                       ├─────────────────────────────>│                            │
      │                       │                              │   WebSocket 下发 JS        │
      │                       │                              ├───────────────────────────>│
      │                       │                              │                            │ eda.* API
      │                       │                              │<───────────────────────────┤
      │                       │<─────────────────────────────┤        结果回传             │
      │<──────────────────────┤   解析 / 校验 / 下一轮        │                            │
```

**中间那个 Node 桥是嘉立创官方软件，不属于本仓库。**
它来自 [easyeda/easyeda-api-skill](https://github.com/easyeda/easyeda-api-skill)（JLCEDA，MIT 协议）。
本仓库不包含它的任何代码，请按[环境准备](#环境准备)自行安装。

本仓库在它之上补的是这些：

- `tools/eda_bridge.py` 是桥的 HTTP 客户端：扫 49620–49629 端口找到桥、查连接状态、
  把一个 `.js` 文件作为作业提交、返回 JSON 结果。所有联机脚本都从它走。
  （`tel2json_netlist.py`、`netlist_drc.py`、`compare_netlist.py` 是纯离线的，不需要开着嘉立创。）
- 其余脚本是作业生成器加结果校验器：拼出一段 JS，经 `eda_bridge.py` 发出去，
  再在 Python 侧做几何、比对与决策，然后生成下一段 JS。
  重计算——间距检查、路径规划、逐脚网表比对——全在 Python 侧；嘉立创只负责读写图元。
- 两个 PowerShell 脚本走的是另一条通道：用 Windows UIAutomation 点嘉立创界面上的按钮。
  有些动作没有 API 对应，最典型的就是 `importChanges` 弹出的确认框——API 能把它叫出来，但关不掉。

一句话：官方 skill 决定 JS 能不能送进嘉立创，本仓库决定送什么 JS、以及怎么确认它真的生效了。

---

## 环境准备

### 1. 嘉立创 EDA 专业版桌面客户端

本仓库全部脚本都是在**桌面客户端**上验证的。两个 PowerShell 脚本用了 Windows UIAutomation，需要 Windows。

### 2. 装 run-api-gateway 扩展

扩展页面：<https://ext.lceda.cn/item/oshwhub/run-api-gateway>

装完确保它处于启用状态。这个扩展负责把嘉立创连到桥。

### 3. 装官方 easyeda-api-skill 并起桥

```bash
git clone https://github.com/easyeda/easyeda-api-skill.git
cd easyeda-api-skill
npm install
npm run server        # 占用 49620-49629 里第一个空闲端口
```

具体步骤以官方 README 为准：不同版本的 npm 脚本名有出入，有的版本需要先跑 `npm run build:docs`。

如果你用 Claude Code 或其它支持 Agent Skills 标准的工具，把那个目录放到工具能读到的地方，
代理会读它的 `SKILL.md` 拿到完整 API 参考。**本仓库刻意不重复官方 API 文档，查 API 请看官方 skill。**

### 4. 克隆本仓库

```bash
git clone https://github.com/DaCapo7/easyeda-agent-toolkit.git
cd easyeda-agent-toolkit
```

需要 Python 3.8+，**无任何第三方依赖**，全部标准库。

想一键起桥，把 `tools/start_bridge.bat` 里的 `SKILL_DIR` 改成你本机 easyeda-api-skill 的路径再运行。

---

## 第一条命令

**1. 确认桥通了：**

```bash
python tools/eda_bridge.py health
```

期望输出：

```
[Bridge] 端口 49620  status=ok  窗口数=1
[嘉立创] 已连接  活动窗口=xxxx
```

「未找到 Bridge」说明 `npm run server` 没起；「嘉立创未连接」说明扩展没装或没启用。

> 桥必须监听双栈 `::`。嘉立创把 `localhost` 解析成 IPv6 的 `::1`，只监听 IPv4 会连不上。

**2. 跑第一个作业：**

```bash
python tools/eda_bridge.py run examples/00_probe.js
```

它会列出当前工程里所有板及其 uuid。**记下 `parentBoardName`**——本仓库几乎每个脚本的第一个参数都是它。

**3. 开了多个嘉立创窗口时：**

```bash
python tools/eda_bridge.py windows            # 列出已连接的窗口
python tools/eda_bridge.py select <windowId>  # 指定活动窗口
```

> **传 JS 一律用文件（`run <文件>`），不要用命令行字符串（`exec "<字符串>"`）。**
> PowerShell 会破坏引号和 `Ω` 这类字符。

**4. 离线验证，不需要嘉立创。** 仓库自带一份四器件的演示网表，可以先把网表这一段跑通：

```bash
python tools/tel2json_netlist.py examples/demo.tel examples/out.json --bom examples/demo_bom.csv
python tools/netlist_drc.py examples/out.json
```

第一条会打印 `器件 4 | 引脚 10 | 已配料号 4/4`；
第二条会把 `NC_SPARE` 这个只连了一个引脚的网标出来，这正是它的用途。

---

## 主线流程：从网表到下单文件

完整版在 [`docs/网表重建导入.md`](docs/网表重建导入.md)，这里给骨架。

```
.tel 网表 + BOM(带立创料号)
        │  tel2json_netlist.py
        ▼
   带料号的网表 .json  ──── netlist_drc.py（离线自查）
        │  generate_schematic_from_json.py
        ▼
   原理图有器件了
        │  fix_supplier_ids.py / fix_nc.py
        ▼
   原理图 DRC 干净
        │  compare_netlist.py（逐脚校验导入忠实度）
        ▼
        │  sync_pcb_via_importchanges.py
        ▼
   PCB 上器件和飞线到位
        │  摆件 / 板框 / 布线（API 或 FreeRouting）
        ▼
        │  repour_safe → neck_analyze → gap_nudge → width_cut → neck_sink → fix_sink
        ▼
   DRC 收敛
        │  netcmp_live.py 逐脚回归 + render_at.py 截图确认
        ▼
        │  export_mfg.py
        ▼
   BOM + 贴片坐标，可以下单
```

### 命门一：料号

网表重建扩展查库**只认 `props["Supplier Part"]`，即立创 C 料号**。
厂家型号与封装名不参与匹配。没料号导入直接失败；填错料号会静默放上错器件，
**而且事后改不回来**——`modify` 改不了器件的库关联，只能改 JSON 重新导入。
界面上的"器件标准化"也救不了，它只会标准化成那个错料号指向的器件。

因此 `tel2json_netlist.py` 用三级兜底匹配（精确位号 → 封装+数值 → 封装唯一），
**配不上的列出告警而不是猜一个**。

### 命门二：`addIntoPcb`

```js
sch_PrimitiveComponent.create(component, x, y, subPartName, rotation, mirror, addIntoBom, addIntoPcb)
```

最后两个参数（尤其 `addIntoPcb`）漏传，器件就只存在于原理图。
后续同步到 PCB 会**放 0 个元件**，而且没有任何报错解释原因。

### 命门三：那个要等几分钟的对话框

`pcb_Document.importChanges(schUuid)` 返回 `true` **不代表元件落板了**，只代表弹出了一个确认对话框。
只有点了那个标着**「应用修改」**（不是「确定」）的按钮，元件才会真的放上去。

某些版本上这个对话框**要好几分钟**才渲染出来。15 秒或 40 秒的看门狗会报"对话框没出现"，
从而让你得出"API 坏了"的错误结论。

`sync_pcb_via_importchanges.py` 默认等 300 秒，期间持续扫描按钮。
找不到按钮就跑 `list_eda_buttons.ps1`，把实际存在的按钮名打出来。

### 命门四：DRC 干净不等于板子连对了

**实证：故意断开一条网，DRC 仍报 0 违例。**
嘉立创的 DRC 管的是间距与孔的几何，**不检查连通性**。

连通引擎只认**完全重合的端点**——线身交叠不算连接，T 形穿越不算连接，端点"非常接近"也不算。
坐标四舍五入到两位小数就是开路，而且没有任何提示。

每一轮几何操作之后都跑一遍 `netcmp_live.py` 做逐脚回归。

### 命门五：返回成功但没落盘的写入

有些 API 调用**返回成功、当场读回是新值，重启之后仍是旧值**。
已确认的有：过孔孔径/盘径、铺铜轮廓宽、以及传错形状的规则配置。

> **读回新值不算验证。改了关键属性之后，重启嘉立创再读一遍。**

---

## 工具清单

全部在 `tools/`，扁平放置——脚本之间靠同目录相对路径互相调用，别拆开。

### 桥与界面

| 脚本 | 用途 |
|---|---|
| `eda_bridge.py` | 所有联机脚本的入口。找桥、查状态、提交 `.js` 作业。子命令：`health` / `windows` / `select` / `run` / `exec` |
| `start_bridge.bat` | 启动官方桥并检查连接（先改里面的 `SKILL_DIR`） |
| `click_eda_confirm.ps1` | 用 UIAutomation 点「应用修改」。中文按钮名在脚本内由 Unicode 码点拼出，绕开所有编码层 |
| `list_eda_buttons.ps1` | 诊断：打印嘉立创所有窗口的所有按钮名。版本改了按钮文案时用它 |

### 网表 → 原理图

| 脚本 | 用途 |
|---|---|
| `tel2json_netlist.py` | `.tel` + BOM → 带料号的网表 JSON。三级匹配，配不上就告警而不是猜 |
| `netlist_drc.py` | 离线自查：单引脚网、重复位号、连接率。**不需要开嘉立创** |
| `generate_schematic_from_json.py` | 经桥生成原理图：查库 → 放器件 → 改位号 → 每脚拉一段带 net 的短线 |
| `fix_supplier_ids.py` | 批量修正 SupplierId，消掉"供应商不符"的 DRC 项 |
| `fix_nc.py` | 批量给未用引脚打 NC 标记，消掉"引脚悬空"警告 |
| `compare_netlist.py` | 源网表与导出结果逐脚比对，校验导入忠实度 |
| `netcmp_live.py` | 读板上实况与 `.tel` 源比对。几何操作后的回归校验用它 |

### 原理图 → PCB

| 脚本 | 用途 |
|---|---|
| `sync_pcb_via_importchanges.py` | `importChanges` + 自动点「应用修改」+ 轮询到器件数稳定。对话框默认等 300 秒 |

### PCB 几何

按这个顺序跑：

| 脚本 | 用途 |
|---|---|
| `repour_safe.py` | 安全重灌铺铜。发 `Shift+B` 之前先确认嘉立创确实是前台窗口，否则中止——按键绝不能落进别的程序 |
| `neck_analyze.py` | 违例台账：按网络、按网络对统计，看清是哪几条网在闹 |
| `gap_nudge.py` | 平移违例线段。只动几何不动拓扑；端点连同精确共享该端点的段一起动；挪之前先查空间 |
| `width_cut.py` | 把违例的过宽线段降到目标线宽。适用于那些多出来的宽度本来就是余量、并非载流需要的情况 |
| `neck_sink.py` | 把拥堵的干线段挪到内层，给表层腾净空。会改拓扑，动手前自动备份该网络 |
| `fix_sink.py` | 重定位那些离板框或其它孔太近的过孔 |
| `render_at.py` | 对关注点截图。**改完自己看一眼**，别只信 API 返回值 |

### 下单

| 脚本 | 用途 |
|---|---|
| `export_mfg.py` | 导出 BOM 与贴片坐标。处理两个坑：嘉立创的 "csv" 实为 UTF-16LE + TAB 分隔；文件内容经 base64 过桥以避开控制台编码 |

---

## 值得先读的坑

完整列表在 [`docs/铁律与坑.md`](docs/铁律与坑.md)。最贵的十条：

1. **返回成功但没落盘的写入。** 过孔孔径与铺铜轮廓宽都会报成功却没保存。重启嘉立创复核。
2. **DRC 不管连通性。** 断了的网照样报 0。连通要独立校验。
3. **连通要求端点完全重合。** 坐标四舍五入就是开路，无任何提示。
4. **共线同网的段在创建时会被合并。** 想在干线中间保留一个接头，就把接头过孔在干线中心线上下各偏几 mil
   交替放置，相邻段斜率不同就不会被合并。否则拆开的段会被粘回一条，接头落到线身上（见第 3 条）。
5. **图元 id 出了作业边界就失效。** 读 id 与用 id 必须在同一个桥作业内。跨作业使用会抛
   `t.isAsync is not a function`，还可能让批量操作跑一半死掉——此前的改动已经落板，网络被撕成两半。
6. **DRC 会报幻影违例。** `closeDocument` 再打开就消失了。在断定某块板需要返工之前先复核。
7. **中文 Windows 上的三个编码坑。** Python 打印非 GBK 字符会崩（用 `sys.stdout.reconfigure`）；
   读 PowerShell 输出必须显式指定 utf-8；嘉立创导出的 "csv" 是 UTF-16LE + TAB。
   一个在打印成功信息时崩掉的脚本，看起来和真的失败一模一样。
8. **`pcb_PrimitivePolyline.create(net, layer, polygon, lineWidth, primitiveLock)`**——`net` 在第一位，
   `polygon` 必须用 `pcb_MathPolygon.createPolygon([...])` 工厂构造，直接传裸数组会报参数错误。
9. **单个作业约 30 秒上限。** 据此分批：属性 `modify` 约 40 个一批，几何 `modify` 约 150 个一批。
10. **在断定一块板不可用之前**，先做三件事：逐路核算电流、清掉幻影违例后复核、
    区分电气问题、制造性问题与规则问题。制造性问题（线宽低于板厂下限、孔径低于最小钻孔）
    靠局部调整解决，不是推倒重来。

---

## 目录结构

```
easyeda-agent-toolkit/
├── README.md                 英文版（默认）
├── README.zh-Hans.md         本文
├── LICENSE                   MIT
├── docs/                     仅中文
│   ├── 铁律与坑.md            API 行为与坑
│   └── 网表重建导入.md         网表到 PCB 的完整流程
├── tools/                    脚本（扁平放置，互相靠相对路径调用）
│   └── eda_jobs/             脚本生成的临时 JS 作业落在这里（不入 git）
└── examples/
    ├── 00_probe.js            连通性探针与列板
    ├── 10_export_netlist.js   导出成品网表落盘
    ├── 20_pin_truth_probe.js  脚位探针（比 datasheet 可靠）
    ├── demo.tel               演示网表，四个器件，可直接跑
    ├── demo_bom.csv           配套 BOM
    └── example_netlist.json   该演示的产物，也是网表 JSON 的格式参考
```

`examples/` 下的料号与网名都是占位值，不对应任何真实设计。

---

## 声明

**本项目是非官方项目，与嘉立创（JLC / LCEDA / 立创EDA）没有任何关联**，也未获得其认可。
涉及的产品名与商标仅用于说明兼容性。

**关于官方 skill。** 本仓库依赖
[easyeda/easyeda-api-skill](https://github.com/easyeda/easyeda-api-skill)（JLCEDA，MIT 协议）
提供的桥服务与 API 参考，但**不包含、不复制、不重新分发它的任何内容**。
请按[环境准备](#环境准备)自行安装，其版权归 JLCEDA 所有。

**关于作者。** 这些脚本由 Claude（Anthropic）与作者协作产出。本仓库以 MIT 协议发布。

**风险自负。** 这些脚本会**直接修改你的嘉立创工程文件**，其中几个
（`neck_sink.py`、`fix_sink.py`、`width_cut.py`、`gap_nudge.py`）会成批改动板上几何。
**请先备份工程。** 作者不对使用本工具箱造成的设计损失、生产损失或费用承担责任。
具体行为——按钮文案、API 签名、DRC 返回结构——会随嘉立创版本变化，请先在废板上试。

**关于数据。** 本仓库不含任何凭据、API token 或私有板卡数据——没有网表、坐标、料号、网络名或 Gerber。
`examples/` 下的内容全部是编造的。
