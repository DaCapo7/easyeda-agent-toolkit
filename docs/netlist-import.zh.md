[English](./netlist-import.en.md) | 简体中文

# 网表重建导入：从一份网表到板上有器件

本文讲整条链路的前半段：**手里有一份网表，怎么把它变成嘉立创工程里的原理图，
再变成 PCB 上摆好的器件**，全程不手画。

先说清楚"网表重建"是什么：它是嘉立创 EDA 专业版扩展市场里的一个官方扩展
（`eext-generate-schematic-from-netlist`），接受一个特定格式的 JSON，按里面的器件和连接关系自动生成原理图。
本文的第一段流程就是在喂它。

---

## 全景

```
.tel 网表 + BOM(带立创料号)
        │  tel2json_netlist.py
        ▼
   料号网表 .json  ──── netlist_drc.py（离线自查，挡掉低级错误）
        │
        ├─(路线 A) 嘉立创扩展"网表重建"手工导入
        └─(路线 B) generate_schematic_from_json.py 经桥全自动建
        ▼
     原理图有器件了
        │  fix_supplier_ids.py  刷 SupplierId
        │  fix_nc.py            未用引脚打 NC 标记
        ▼
     原理图 DRC 干净
        │  10_export_netlist.js + compare_netlist.py  逐脚比对导入忠实度
        ▼
     确认导入没走样
        │  sync_pcb_via_importchanges.py
        ▼
     PCB 上器件和飞线都到位
```

---

## 第 0 步：为什么必须有立创料号

这是整件事的命门，先说，省得后面反复撞墙。

**网表重建扩展查库时只看一个字段：`props["Supplier Part"]`，也就是立创的 C 料号。**
它拿这个料号去调 `eda.lib_Device.getByLcscIds()` 取器件放到图上。
`device_name`（厂家型号）、`Footprint`（封装名）这两个字段**完全不参与匹配**。

所以：

- 没料号 → 导入直接失败，报 "no component placed"。
- 料号填错 → 器件放上去了，但是个错器件（错封装、错符号），
  **而且事后改不回来**——`modify` 改不了器件的库关联，属性表里根本没有 component / symbol / footprint 这些字段。
  唯一的解法是改 JSON 重新导入。
- 界面上的"器件标准化"救不了填错的料号，它只会把器件标准化成那个错料号对应的标准件。

结论：**料号这一关必须在生成 JSON 的时候就做对**，后面没有补救窗口。

料号还会下架。碰到 `getByLcscIds` 和搜索都返回空，说明这个料号已经不在库里了，
按 MPN（厂家型号）去嘉立创商城搜现行料号替换。

---

## 第 1 步：`.tel` + BOM → 料号网表 JSON

```bash
python tools/tel2json_netlist.py in.tel out.json --bom bom.csv [--override over.json]
```

`.tel` 是嘉立创 EDA 专业版自己能导出的网表格式，结构是 `$PACKAGES`（器件和封装）和 `$NETS`（网络和引脚）两段。
BOM 提供料号。脚本把两者按位号对起来。

**料号匹配是三级兜底的**，因为真实 BOM 从来不规整：

1. **精确位号**：解析 BOM 的 Designator 列，支持逗号列表和 `R01-R08` 这种范围写法（前缀相同、数字连续即可）。
   含 `...` 省略号的行会跳过——省略号没法可靠展开，硬展开就是在猜。
2. **封装 + 数值**：按（封装类型，数值 token）去配。这一级救的是 BOM 位号写得不全的情况。
   封装类型做过归一化：`C0402` / `R0402` / `0402` 会归到同一个 `0402`，FPC 座按脚数归到 `FPC-8P` 这种。
3. **封装唯一**：某个封装类型在整份 BOM 里只对应一个料号，那就直接用它。

三级都配不上的器件会**列出来告警，绝不静默填一个错料号**——这是设计上的硬要求。
告警里的器件用 `--override`（一份 `{位号: 料号}` 的 JSON）手工指定，优先级最高。
连接器最常需要 override，因为 BOM 和 `.tel` 里的封装名往往对不上。

产出格式是这样（也就是 `examples/example_netlist.json`）：

```json
{
  "gge1": {
    "props": { "Designator": "R1", "device_name": "...", "value": "10k", "Supplier Part": "C0000001" },
    "pins":  { "1": "VCC_3V3", "2": "SENSE_A" }
  }
}
```

几个格式细节，写错了导入就不认：器件 key 必须是 `gge1` / `gge2` 顺序编号；
`props` 里的字段名 `device_name`、`value` 是小写。

---

## 第 2 步：离线自查

```bash
python tools/netlist_drc.py out.json [其他板.json ...]
```

在导进嘉立创**之前**跑，不需要开软件。查三件事：

- **单网络**：某个网只连了 1 个引脚 —— 这基本上就是画错或漏画，导进去也是白导。
- **重复位号**：同一个位号出现两次。
- **引脚连接率**：连了多少 / 一共多少，心里有个数。

这一步很便宜，但能挡掉大部分"导进去才发现连错"的返工。

**注意它查不出的东西**：同名网自动合并造成的误连。
后面第 5 步的逐脚比对才能抓到那一类——见下文那个螺端子的例子。

---

## 第 3 步：生成原理图

两条路，选一条。

### 路线 A：用官方"网表重建"扩展手工导入

在嘉立创里装扩展（扩展市场搜 `eext-generate-schematic-from-netlist`），把上一步的 JSON 喂给它。
成功时会提示 Import netlist success。

优点是稳，缺点是要人点。

### 路线 B：`generate_schematic_from_json.py` 经桥全自动建

```bash
python tools/generate_schematic_from_json.py out.json [--clear] [--batch 10] [--test 5]
```

它不走扩展，直接用 API 一个个建：
网格布局 → 每个器件 `lib_Device.getByLcscIds(料号)` 取库（带缓存）→ `sch_PrimitiveComponent.create` 放上去
→ `modify` 改位号 → 每个引脚拉一段带 net 的短线（同名 net 逻辑上就连通了）。

`--test N` 先拿几个器件试水，确认料号能查到、位号能改对，再全量跑。
`--clear` 会先清空当前原理图——新建的板里有一个默认占位器件，不清掉会混进去。

**这里有一个必须记住的参数。** `create` 的完整签名是：

```js
create(component, x, y, subPartName, rotation, mirror, addIntoBom, addIntoPcb)
```

最后两个参数（尤其 `addIntoPcb`）漏传，器件就只活在原理图里，**第 6 步同步到 PCB 时会放 0 个元件**。
这个脚本默认传的是 `true`。如果你手上有一块历史遗留的板放不进 PCB，
逐器件补 `sch_PrimitiveComponent.modify(id, {addIntoPcb: true, addIntoBom: true})` 再 `sch_Document.save()`。

批大小别调太大：单个桥作业执行超过 30 秒左右会超时。

---

## 第 4 步：把原理图 DRC 修干净

```bash
python tools/fix_supplier_ids.py out.json [批大小]
python tools/fix_nc.py out.json [批大小]
```

- `fix_supplier_ids.py`：网表重建导入之后，器件的 SupplierId 常被设成 MPN 而不是 C 料号，
  会触发 DRC 的"供应商不符"。这个脚本按位号批量刷回来。
- `fix_nc.py`：没用到的引脚会被 DRC 报"引脚悬空，建议放置非连接标识"。
  这个脚本读网表里每个器件**用到了哪些脚**，把剩下的脚调 `setState_NoConnected(true).done()` 打上 NC 标记。

两个都分批跑，防 30 秒超时。

---

## 第 5 步：逐脚比对，确认导入没走样

这一步不能跳。

```bash
# 先在桥里导出成品网表（改一下 examples/10_export_netlist.js 里的板名和路径）
python tools/eda_bridge.py run examples/10_export_netlist.js
# 再比对
python tools/compare_netlist.py out.json C:/tmp/board_export.json
```

比对源网表和嘉立创吐出来的成品网表，看器件有没有漏、每个引脚的网络对不对。
目标是**零不一致**。

**这一步能抓到而 ERC 抓不到的一类错误：短线跨脚导致的误合并。**

引脚密集的器件（比如两脚只隔 10 个单位的螺丝端子）上，如果生成脚本给每个引脚都拉一段 +20 长度的
水平短线，这两段短线会**跨过对方的引脚**，把本该分开的两个网络粘成一个。

原理图 ERC 对此报 0，看不出任何异常，只有逐脚比对能发现。

修法：删掉这类跨脚短线（`sch_PrimitiveWire.delete`），改用**竖直错位**的短线
（`create([x, y, x, y±60], net)`）重画，再导出重新比对确认归零。

普通电阻电容不受影响，它们的引脚间距在 100 左右，20 的短线够不着。
**引脚间距小于短线长度的器件都要提防这个。**

另外，嘉立创自带 `SYS_Tool.netlistComparison` 也可以校验导入忠实度，可以两条路互相印证。

---

## 第 6 步：同步到 PCB

```bash
python tools/sync_pcb_via_importchanges.py <BoardName> [等待秒数，默认300]
```

这一步的坑最密，`docs/pitfalls.zh.md` 第二节全篇在讲它。这里只重复三条最要命的：

1. **`importChanges` 返回 true 不代表元件落板了**，它只是把一个确认对话框叫了出来。
   要点里面那个叫「应用修改」的按钮（不是「确定」），元件才会真的放上去。
2. **那个对话框可能要好几分钟才渲染出来**。15 秒 / 40 秒的看门必然误判成"对话框没出现"，
   然后你就会得出"API 坏了"的错误结论。默认等 300 秒。
3. **触发之后不要再激活文档**。放置过程中重新 `openDocument` + `activateDocument`，
   会把放置打断，元件停在中途。要看进度就用裸的 `getAll()` 数个数。

脚本做的事：取板信息 → 激活一次 PCB → 记录导入前器件数 → 触发 `importChanges`
→ 调 `click_eda_confirm.ps1` 用 UIAutomation 找到并点「应用修改」→ 裸 `getAll()` 轮询直到数目稳定。

按钮找不到的时候，先跑诊断：

```powershell
powershell -ExecutionPolicy Bypass -File tools/list_eda_buttons.ps1
```

它会把嘉立创所有窗口的所有按钮名打出来。不同版本的按钮文案可能变，看到真名再改脚本。

---

## 第 7 步：之后呢

到这里 PCB 上已经有器件和飞线了。后面是布局布线，那是另一个话题：

- 摆件、画板框、布线：`pcb_PrimitiveComponent` 的 `setState_X/Y/Rotation`、`pcb_PrimitivePolyline.create`、`pcb_PrimitiveLine.create`。
- 自动布线：`getDsnFile` 导出 → FreeRouting → `importAutoRouteSesFile` 导回。
  （FreeRouting 1.9 的批处理模式可用；2.2.4 有个致命的空指针问题。）
- 间距整改：先 `repour_safe` 重灌铺铜，再 `neck_analyze` → `gap_nudge` → `width_cut` → `neck_sink` → `fix_sink`，顺序和理由见 `docs/pitfalls.zh.md` 第六节。
- 校验：`netcmp_live.py` 逐脚回归 + `render_at.py` 截图用眼睛看。
- 下单文件：`export_mfg.py` 导 BOM 和贴片坐标。

最后提醒一句，这句在 `docs/pitfalls.zh.md` 里也有，值得说两遍：
**DRC 全绿不等于板子连对了。DRC 不检查连通性——故意断一条网，它照样报 0。**
连通必须独立校验。
