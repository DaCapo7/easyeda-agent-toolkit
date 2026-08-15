// 例 3: 脚位真值探针 —— 比翻 datasheet 可靠的查脚方法
// 跑法: 改 LCSC_IDS, 然后 python ../tools/eda_bridge.py run 20_pin_truth_probe.js
//
// 为什么需要它: 写网表时最怕"脚号↔功能"对错。datasheet 的脚序、封装的丝印脚序、
// 嘉立创库里符号的脚号, 三者不一定一致。与其猜, 不如直接把器件放到图上问一遍库,
// 问完删掉 —— 这是零成本、零污染、且拿到的是"你马上要用的那个库器件"的真值。
//
// 用完记得确认 deleted 都是 true, 别把探针器件留在图纸上。

const LCSC_IDS = ["C1234567", "C7654321"];   // ← 改成你要查的立创料号

const out = [];
for (const id of LCSC_IDS) {
  const rec = { lcsc: id };
  try {
    const devs = await eda.lib_Device.getByLcscIds(id);
    const dev = devs && devs[0];
    if (!dev) { rec.err = "料号在库里查不到(可能已下架, 换现行料号)"; out.push(rec); continue; }

    // 放到一个不碍事的位置; 最后两个 false = 不进 BOM、不进 PCB(探针器件用完就删, 别污染工程)
    const c = await eda.sch_PrimitiveComponent.create(dev, 100, 100, undefined, 0, false, false, false);
    const cid = c.getState_PrimitiveId();

    const pins = await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(cid);
    rec.pins = pins.map(p => ({
      pinNumber: p.pinNumber,          // 脚号 —— 网表 pins 的 key 要用这个
      name: p.getState_Name()          // 功能名, 如 PA0 / VIN+ / SCL
    }));

    rec.deleted = await eda.sch_PrimitiveComponent.delete(cid);
  } catch (e) {
    rec.err = String(e).slice(0, 200);
  }
  out.push(rec);
}
return JSON.stringify(out);
