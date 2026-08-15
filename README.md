# easyeda-agent-toolkit

**嘉立创 EDA 专业版 × AI 编码代理的自动化画板工具箱与实战教程（基于官方 easyeda-api-skill 桥）**

这是一套 Python / PowerShell 脚本，加上一份写得比较狠的踩坑记录。
它让 Claude Code 这类 AI 编码代理能够真的去操作嘉立创 EDA 专业版——
读网表、生成原理图、同步到 PCB、跑 DRC、批量改线宽、挪线、下沉内层、导下单文件，
整条链路不用手点鼠标（除了几个 API 确实够不着的地方，那几个地方文档里都标出来了）。

**这些代码不是想象出来的。** 它们是在一个真实的多板 PCB 项目里长出来的：
两块柔性板（FPC）被工厂以"线距不够"退单之后，靠里面的几何手术脚本把 2211 条间距违例打到 267 条，
其间三轮大规模改动，逐脚网表比对全程零断网。踩过的坑都写进了 `docs/铁律与坑.md`。

---

## 目录

- [先说清楚三件事](#先说清楚三件事)
- [它和官方 easyeda-api-skill 是什么关系](#它和官方-easyeda-api-skill-是什么关系)
- [环境准备](#环境准备)
- [五分钟跑通第一条命令](#五分钟跑通第一条命令)
- [主线教程：从一份网表到可下单的板](#主线教程从一份网表到可下单的板)
- [工具清单](#工具清单)
- [最值得先读的几条坑](#最值得先读的几条坑)
- [目录结构](#目录结构)
- [声明](#声明)

---

## 先说清楚三件事

**这是什么**：一套让 AI 代理驱动嘉立创 EDA 专业版做重复性画板工作的脚本 + 一份实战踩坑文档。

**这不是什么**：不是自动布线器，不是"输入需求自动出板子"的魔法。
它替你干的是**机械活**——批量改属性、批量挪几何、批量校验、批量导文件。
真正需要判断力的地方（热区怎么收口、板框怎么排、哪根线该走哪层）还是人做得更快。
我们的实测结论是：**交互式手工推挤 15 分钟，能顶脚本跑 3 小时**。所以合理的分工是机器跑重建链和审计，人收口热区。

**为什么值得看**：嘉立创 EDA 专业版的 API 有一批相当反直觉的行为——
改属性返回成功但重启后还原、DRC 根本不检查连通性、确认对话框要几分钟才渲染出来、
共线同网的线段会被自动合并……
这些东西官方文档里查不到，只能踩。`docs/铁律与坑.md` 是这个仓库最值钱的部分，
建议**动手之前先扫一遍标题**。

---

## 它和官方 easyeda-api-skill 是什么关系

先看链路：

```
  你的 AI 代理                本仓库                    官方 easyeda-api-skill        嘉立创EDA专业版
 (Claude Code 等)          (Python/PS 脚本)               (Node 桥服务)              (装 run-api-gateway 扩展)
       │                         │                             │                            │
       │  写一段 JS 作业          │                             │                            │
       ├────────────────────────>│                             │                            │
       │                         │  HTTP POST /execute         │                            │
       │                         ├────────────────────────────>│                            │
       │                         │                             │   WebSocket 下发 JS        │
       │                         │                             ├───────────────────────────>│
       │                         │                             │                            │ 执行 eda.* API
       │                         │                             │<───────────────────────────┤
       │                         │<────────────────────────────┤        结果回传             │
       │<────────────────────────┤   解析 / 校验 / 下一轮       │                            │
```

**中间那个 Node 桥（Bridge Server）是嘉立创官方做的，不是本仓库的东西。**
它来自 [easyeda/easyeda-api-skill](https://github.com/easyeda/easyeda-api-skill)，作者 JLCEDA，MIT 协议。
本仓库**不包含也不复制它的任何代码**，请自行去官方仓库安装。

**本仓库提供的是它上面那一层**：

- `tools/eda_bridge.py` 是桥的 HTTP 客户端——扫 49620-49629 端口找到桥、查连接状态、
  把一个 `.js` 文件作为作业发过去、把结果 JSON 打回来。**所有需要联机的脚本都从它走**（`tel2json_netlist.py`、`netlist_drc.py`、`compare_netlist.py` 是纯离线的，不用开嘉立创）。
- 其余脚本都是"作业生成器 + 结果校验器"：拼出一段 JS，经 `eda_bridge.py` 发过去，
  再把返回的数据在 Python 侧做几何计算、比对、决策，然后生成下一段 JS。
  真正的重量级计算（碰撞检测、路径规划、逐脚比对）全在 Python 这一侧做，
  嘉立创那边只负责读写图元。
- 还有两个 PowerShell 脚本走的是完全不同的通道：用 Windows UIAutomation 去点嘉立创的界面按钮。
  因为有些事 API 真的做不了——比如 `importChanges` 弹出来的那个确认框，API 只能把它叫出来，点不了。

一句话：**官方 skill 负责"能不能把 JS 送进嘉立创"，本仓库负责"送什么 JS 进去、以及怎么确认它真的生效了"。**

---

## 环境准备

### 1. 嘉立创 EDA 专业版（客户端版）

本仓库的全部脚本都是在**桌面客户端**上验证的（PowerShell 那两个用了 Windows UIAutomation，只能在 Windows 桌面端跑）。

### 2. 装 run-api-gateway 扩展

扩展市场：<https://ext.lceda.cn/item/oshwhub/run-api-gateway>

装完确保它是启用状态。这个扩展负责在嘉立创侧扫端口连桥。

### 3. 装官方 easyeda-api-skill 并起桥

```bash
git clone https://github.com/easyeda/easyeda-api-skill.git
cd easyeda-api-skill
npm install
npm run server        # 自动占用 49620-49629 里的空闲端口
```

具体步骤以官方 README 为准——不同版本的 npm 脚本名可能有出入（有的版本还需要先跑一次 `npm run build:docs`）。

如果你用的是 Claude Code 这类支持 Agent Skills 标准的工具，
把这个目录放到工具能读到的地方，AI 就能自动读它的 `SKILL.md` 拿到完整 API 文档。
这一点很重要——**本仓库不重复官方的 API 文档，查 API 请看官方 skill**。

### 4. 拿到本仓库

```bash
git clone https://github.com/DaCapo7/easyeda-agent-toolkit.git
cd easyeda-agent-toolkit
```

只要 Python 3.8+，**没有任何第三方依赖**（全部标准库）。
PowerShell 脚本需要 Windows（UIAutomation 是 Windows 特有的）。

想一键起桥的话，把 `tools/start_bridge.bat` 里的 `SKILL_DIR` 改成你本机 easyeda-api-skill 的路径，双击即可。

---

## 五分钟跑通第一条命令

**第一步，确认桥通了：**

```bash
python tools/eda_bridge.py health
```

期望看到：

```
[Bridge] 端口 49620  status=ok  窗口数=1
[嘉立创] 已连接  活动窗口=xxxx
```

看到「未找到 Bridge」说明 `npm run server` 没起；
看到「嘉立创未连接」说明扩展没装或没启用。

> 桥必须监听双栈 `::`。嘉立创把 `localhost` 解析成 IPv6 的 `::1`，只听 IPv4 会连不上。

**第二步，跑第一个作业：**

```bash
python tools/eda_bridge.py run examples/00_probe.js
```

它会把当前工程里所有板的名字和 uuid 列出来。
**把 `parentBoardName` 抄下来**——本仓库几乎所有脚本的第一个参数都是它。

**第三步，多开了嘉立创的话：**

```bash
python tools/eda_bridge.py windows          # 列出所有连着的窗口
python tools/eda_bridge.py select <windowId>  # 指定活动窗口
```

> **传 JS 一律用 `run <文件>`，不要用 `exec "<字符串>"`。**
> PowerShell 会把引号和 Ω 之类的字符改得面目全非。这是踩过的。

**第四步（不用开嘉立创也能跑）：** 仓库自带一份四器件的演示数据，可以先把网表这一段跑通看看：

```bash
python tools/tel2json_netlist.py examples/demo.tel examples/out.json --bom examples/demo_bom.csv
python tools/netlist_drc.py examples/out.json
```

第一条会打印 `器件 4 | 引脚 10 | 已配料号 4/4`，
第二条会把 `NC_SPARE` 这个只连了一个引脚的网揪出来——它就是干这个的。

---

## 主线教程：从一份网表到可下单的板

完整版在 [`docs/网表重建导入.md`](docs/网表重建导入.md)，这里给骨架。

```
.tel 网表 + BOM(带立创料号)
        │  tel2json_netlist.py
        ▼
   料号网表 .json  ──── netlist_drc.py（离线自查）
        │  generate_schematic_from_json.py
        ▼
     原理图有器件了
        │  fix_supplier_ids.py / fix_nc.py
        ▼
     原理图 DRC 干净
        │  compare_netlist.py（逐脚比对导入忠实度）
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

网表重建扩展查库时**只看 `props["Supplier Part"]`，也就是立创的 C 料号**。
厂家型号和封装名完全不参与匹配。没料号导入直接失败；填错料号会放上一个错器件，
**而且事后改不回来**——`modify` 改不了器件的库关联，只能改 JSON 重导。
界面上的"器件标准化"也救不了，它只会把器件标准化成那个错料号对应的标准件。

所以 `tel2json_netlist.py` 做了三级兜底匹配（精确位号 → 封装+数值 → 封装唯一），
配不上的**列出来告警，绝不静默填一个错的**。

### 命门二：`addIntoPcb`

```js
sch_PrimitiveComponent.create(component, x, y, subPartName, rotation, mirror, addIntoBom, addIntoPcb)
```

最后两个参数（尤其 `addIntoPcb`）漏传，器件就只活在原理图里，同步到 PCB 时**放 0 个元件**。
我们当年为这个 bug 排查了很久，还一度怀疑是 API 坏了。

### 命门三：那个要等几分钟的对话框

`pcb_Document.importChanges(schUuid)` 返回 true **不代表元件落板了**，
它只是把一个确认对话框叫了出来。要点里面那个叫**「应用修改」**的按钮（不是「确定」），元件才会真的放上去。

而这个对话框在某些版本上**要好几分钟才渲染出来**。
任何 15 秒 / 40 秒的看门狗都会误判成"对话框没出现"，然后你就得出"API 无效"的错误结论——
我们当初就是这么误判的，还写了一份完全错误的诊断报告。

`sync_pcb_via_importchanges.py` 默认等 300 秒，期间持续用 UIAutomation 扫按钮。
按钮找不到就先跑 `list_eda_buttons.ps1` 把当前所有按钮名打出来看。

### 命门四：DRC 全绿 ≠ 板子连对了

**实证结论：故意把一条网断开，DRC 照样报 0 违例。**
嘉立创的 DRC 只管间距、孔径这类几何/工艺规则，**不检查连通性**。

而且连通引擎**只认精确共享端点**——线身交叠不算，T 形穿越不算，端点"几乎重合"也不算。
坐标四舍五入到两位小数就是断路，而且没有任何提示。

所以每一轮几何手术之后都要跑一遍 `netcmp_live.py` 做逐脚回归。
我们做过三轮大规模改动，就是靠这个证明"零断网"的。

### 命门五：假成功

有一类 API 调用**返回成功、当场读回也是新值，重启软件后却是旧值**。
已确认的有：改过孔孔径、改铺铜轮廓宽、传错形状的规则配置。

> **"当场读回是新值"不算验证。改了关键属性，必须重启嘉立创之后再读一遍。**

这一条我们知道之后还被骗过一次——明知有坑，仍然因为"读回确实是新值"就写了完成报告，
第二天复核才发现整轮白干。

---

## 工具清单

全部在 `tools/`，扁平放置（脚本之间靠同目录相对路径互相调用，别拆目录）。

### 桥与界面

| 脚本 | 干什么 |
|---|---|
| `eda_bridge.py` | **所有脚本的入口**。扫端口找桥、查状态、把 `.js` 作业发过去。`health` / `windows` / `select` / `run` / `exec` |
| `start_bridge.bat` | 一键起官方桥服务并检查连接（用前改里面的 `SKILL_DIR`） |
| `click_eda_confirm.ps1` | UIAutomation 点「应用修改」。中文按钮名在脚本内用 Unicode 码点拼，绕开所有编码层 |
| `list_eda_buttons.ps1` | 诊断：把嘉立创所有窗口的所有按钮名打出来。改按钮文案的版本靠它救命 |

### 网表 → 原理图

| 脚本 | 干什么 |
|---|---|
| `tel2json_netlist.py` | `.tel` + BOM → 料号网表 JSON。三级料号匹配，配不上就告警不瞎填 |
| `netlist_drc.py` | 离线自查：单网络（只连 1 脚）、重复位号、连接率。**不用开嘉立创** |
| `generate_schematic_from_json.py` | 经桥全自动建原理图：查库 → 放器件 → 改位号 → 每脚拉带 net 的短线 |
| `fix_supplier_ids.py` | 批量刷 SupplierId，修 DRC 的"供应商不符" |
| `fix_nc.py` | 未用引脚批量打 NC 标记，修"引脚悬空"警告 |
| `compare_netlist.py` | 源网表 vs 导出的成品网表逐脚比对，查导入忠实度 |
| `netcmp_live.py` | 直接读板上真值和 `.tel` 逐脚比对。几何手术后的回归校验就用它 |

### 原理图 → PCB

| 脚本 | 干什么 |
|---|---|
| `sync_pcb_via_importchanges.py` | `importChanges` + 自动点「应用修改」+ 轮询到稳定。默认等对话框 300 秒 |

### PCB 几何手术

按这个顺序打，性价比最高：

| 脚本 | 干什么 |
|---|---|
| `repour_safe.py` | 安全重灌铺铜。先校验嘉立创确实是前台窗口才发 `Shift+B`，否则中止——绝不把按键发进别人的窗口 |
| `neck_analyze.py` | 违例台账：按网络、按网络对统计，先看清楚是哪几条网在闹 |
| `gap_nudge.py` | 微挪违例线段。只平移不改拓扑，端点连同共享端点的邻接段一起动以保连接，挪前查背后空间 |
| `width_cut.py` | 违例粗线统一降宽。**投入产出比最高的一招**，我们靠它一次把 397 条打到 267 条 |
| `neck_sink.py` | 拥堵段干线下沉内层。会动拓扑，每个网络动手前自动备份，可整网恢复 |
| `fix_sink.py` | 下沉时打的过孔离板框/别的孔太近，这个负责重定位 |
| `render_at.py` | 定点截图。**改完自己看一眼**，别只信 API 返回值 |

### 下单

| 脚本 | 干什么 |
|---|---|
| `export_mfg.py` | 导 BOM + 贴片坐标。内含两个坑的解法：嘉立创的 "csv" 其实是 UTF-16LE + TAB；文件走 base64 过桥防编码破坏 |

---

## 最值得先读的几条坑

完整版在 [`docs/铁律与坑.md`](docs/铁律与坑.md)，这里挑最容易致命的十条：

1. **假成功**：改过孔孔径、改铺铜轮廓宽都属于"返回成功但没落盘"。必须重启嘉立创复核。
2. **DRC 不检查连通性**：断网它照样报 0。连通必须独立校验。
3. **连通只认精确共享端点**：坐标四舍五入 = 断路，无提示。
4. **共线同网段创建时会被自动合并**：想在干线中间留接头，得走"之字形"（接头过孔在干线中心线上下各偏几 mil 交替），
   否则分段会被粘回长线、接头落到线身上（见第 3 条）。
5. **id 出了作业就失效**：读 id 和用 id 必须在同一个桥作业里。跨作业用会抛 `t.isAsync is not a function`，
   批量操作跑一半死掉——死掉之前的改动已经落板了，于是你得到一个被撕成两半的网络。
6. **DRC 有幻影违例**：`closeDocument` 再打开就消失了。判"这块板要重做"之前先复核。
7. **中文 Windows 三件套**：Python 打印中文会崩（要 `sys.stdout.reconfigure`）；
   读 PowerShell 输出要显式指定 utf-8；嘉立创导出的 "csv" 是 UTF-16LE + TAB。
   我们有一次点击其实成功了，脚本在打印结果那一行崩掉，留下"点击失败"的假象，
   害我们往完全错误的方向排查了很久。
8. **`pcb_PrimitivePolyline.create(net, layer, polygon, lineWidth, primitiveLock)`**：net 在第一位；
   `polygon` 必须用 `pcb_MathPolygon.createPolygon([...])` 工厂造，直接传数组报"参数不正确"。
9. **单作业约 30 秒超时**：属性 modify 每批 40 个左右，几何 modify 每批 150 个左右。
10. **判"设计作废"前的三步**：逐路电流核算、去幻影后复核、分清是电气/制造性/规则问题。
    制造性问题（线宽低于工艺下限、孔径太小）的解法是逐点微调，不是推倒重来。
    我们曾因为过度诊断把一块好板判成"整板作废"并推倒重摆，事后证明是错的。

---

## 目录结构

```
easyeda-agent-toolkit/
├── README.md                 本文
├── LICENSE                   MIT
├── docs/
│   ├── 铁律与坑.md            全仓库最值钱的部分，动手前先扫标题
│   └── 网表重建导入.md         主线流程的完整版
├── tools/                    脚本（扁平放置，互相靠同目录相对路径调用）
│   └── eda_jobs/             脚本生成的临时 JS 作业落在这里（不入 git）
└── examples/
    ├── 00_probe.js            连通性探针 + 列板
    ├── 10_export_netlist.js   导出成品网表落盘
    ├── 20_pin_truth_probe.js  脚位真值探针（比翻 datasheet 可靠）
    ├── demo.tel               演示网表（四个器件，可直接跑）
    ├── demo_bom.csv           配套 BOM
    └── example_netlist.json   demo 跑出来的产物，也是网表 JSON 的格式示例
```

`examples/` 里的料号、网名全是编造的占位值，跟任何真实板子无关。

---

## 声明

**本项目是非官方项目，与嘉立创（JLC / LCEDA / 立创EDA）没有任何关联**，
未获得其授权、认可或背书。所有涉及嘉立创的商标与产品名仅用于说明兼容性。

**关于官方 skill**：本仓库依赖 [easyeda/easyeda-api-skill](https://github.com/easyeda/easyeda-api-skill)
（作者 JLCEDA，MIT 协议）提供的 Bridge Server 与 API 文档，
但**不包含、不复制、不重新分发它的任何代码或文档**。请按上面「环境准备」自行安装。
它的版权归 JLCEDA 所有。

**关于这些工具怎么来的**：本仓库的脚本由 Claude（Anthropic）在一个真实 PCB 项目中与作者协作产出，
在真实板子上跑出来的，也在真实板子上翻过车（翻车过程都写进 `docs/铁律与坑.md` 了）。
本仓库以 MIT 协议开源。

**风险自负**：这些脚本会**直接修改你的嘉立创工程文件**，其中一部分（`neck_sink.py`、`fix_sink.py`、
`width_cut.py`、`gap_nudge.py`）会成批地改动板上几何。
**动手之前请务必备份工程**。作者不对使用本工具造成的任何设计损失、生产损失或费用承担责任。
另外，脚本里的具体行为（按钮文案、API 签名、DRC 返回结构）会随嘉立创版本变化，用之前先在废板上试。

**关于数据**：本仓库不含任何账号凭据、API token，也不含任何私有板卡数据
（网表、坐标、料号、网络名、Gerber 一概没有）。示例里的料号和网名都是占位值。
