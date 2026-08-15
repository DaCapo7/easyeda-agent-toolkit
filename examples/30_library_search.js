// 例 4: 器件库检索与料号核验 —— 选型阶段的"证据通道"
// 跑法: 改下面的 KEY / LCSC_IDS, 然后 python ../tools/eda_bridge.py run 30_library_search.js
//
// 用途: 选型调研给出的候选料号, 必须在这里检索命中才算数(见 prompts/part-number-verification.zh.md)。
// 这条通道读的是 EDA 客户端连着的器件库, 比让 AI 凭记忆报料号可靠。
//
// 已核对的 API(来自官方 easyeda-api-skill 的 LIB_Device 参考):
//   eda.lib_Device.search(key, libraryUuid?, classification?, symbolType?, itemsOfPage?, page?)
//       -> Array<ILIB_DeviceSearchItem>
//   eda.lib_Device.getByLcscIds(lcscIds, libraryUuid?, allowMultiMatch?)
//
// ⚠ 字段位置的注意事项: 商业字段(库存/价格/基础库归属/供应商编号/厂商)在官方参考里
//    已标记为 obsolete, 说明"在 otherProperty 中替代"。顶层字段可能仍在, 也可能为空。
//    所以本例**同时**输出 otherProperty 的原始键名和归一化结果 ——
//    先看一眼你这个版本真正给了什么, 再决定怎么解析, 不要照抄别人的字段名。

const KEY = "0402 10k";                    // ← 检索关键词(示例: 0402 封装 10kΩ 电阻)
const LCSC_IDS = [];                       // ← 要核验的 C 编号, 如 ["C1234567"]; 留空则跳过
const PAGE_SIZE = 10;

function pick(item, keys) {
  // otherProperty 优先, 顶层字段兜底
  const op = item.otherProperty || {};
  for (const k of keys) {
    if (op[k] !== undefined && op[k] !== "") return op[k];
  }
  for (const k of keys) {
    if (item[k] !== undefined && item[k] !== "") return item[k];
  }
  return null;
}

function normalize(item) {
  return {
    name: item.name || null,
    description: item.description || null,
    footprint: item.footprint || item.footprintName || null,
    manufacturer: pick(item, ["Manufacturer", "manufacturer"]),
    mpn: pick(item, ["Manufacturer Part", "manufacturerId"]),
    supplier: pick(item, ["Supplier", "supplier"]),
    supplierPart: pick(item, ["Supplier Part", "supplierId"]),   // 立创 C 编号
    libraryCategory: pick(item, ["jlcLibraryCategory"]),          // "standard"=基础库 / "extend"=扩展库
    jlcInventory: pick(item, ["jlcInventory"]),
    lcscInventory: pick(item, ["lcscInventory"]),
    jlcPrice: pick(item, ["jlcPrice"]),
    lcscPrice: pick(item, ["lcscPrice"]),
    uuid: item.uuid || null,
    libraryUuid: item.libraryUuid || null
  };
}

const out = {};

// ---- 通道 1: 关键词检索 ----
try {
  const hits = await eda.lib_Device.search(KEY, undefined, undefined, undefined, PAGE_SIZE, 1) || [];
  out.searchKey = KEY;
  out.hitCount = hits.length;
  // 原始键名: 用来确认你这个版本到底把商业字段放在哪
  out.rawTopLevelKeys = hits[0] ? Object.keys(hits[0]) : [];
  out.rawOtherPropertyKeys = hits[0] && hits[0].otherProperty ? Object.keys(hits[0].otherProperty) : [];
  out.results = hits.map(normalize);
} catch (e) {
  out.searchError = String(e).slice(0, 200);
}

// ---- 通道 2: 按 C 编号核验 ----
if (LCSC_IDS.length) {
  out.verify = [];
  for (const id of LCSC_IDS) {
    const rec = { lcsc: id };
    try {
      const devs = await eda.lib_Device.getByLcscIds(id);
      const dev = devs && devs[0];
      if (!dev) {
        rec.found = false;
        rec.note = "库里查不到 —— 可能已下架, 按 MPN 找现行料号替换";
      } else {
        rec.found = true;
        rec.device = normalize(dev);
      }
    } catch (e) {
      rec.error = String(e).slice(0, 200);
    }
    out.verify.push(rec);
  }
}

return JSON.stringify(out);
