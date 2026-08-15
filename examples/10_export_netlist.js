// 例 2: 导出"成品网表"落盘 —— 用来和源网表做逐脚比对(导入忠实度校验)
// 跑法: 先把下面两个占位改成你的板名和输出路径, 然后
//       python ../tools/eda_bridge.py run 10_export_netlist.js
//       python ../tools/compare_netlist.py 源网表.json C:/tmp/board_export.json
//
// 两个注意:
//   1) 保存路径用纯 ASCII, 嘉立创就直接落盘、不弹保存对话框; 带中文/空格容易被拦。
//   2) 导出的是"当前激活原理图"的网表, 所以必须先 openDocument + activateDocument。

const BOARD_NAME = "YourBoardName";              // ← 改成 00_probe.js 里列出的 parentBoardName
const SAVE_PATH  = "C:/tmp/board_export.json";   // ← 改成你的输出路径(纯 ASCII)

const schs = await eda.dmt_Schematic.getAllSchematicsInfo() || [];
const hit = schs.find(s => s.parentBoardName === BOARD_NAME);
if (!hit) return JSON.stringify({ err: "board not found: " + BOARD_NAME });

const tab = await eda.dmt_EditorControl.openDocument(hit.uuid);
await eda.dmt_EditorControl.activateDocument(tab);
await new Promise(r => setTimeout(r, 1500));

const f = await eda.sch_ManufactureData.getNetlistFile("export.json");
if (!f) return JSON.stringify({ err: "getNetlistFile returned null" });

const out = { size: f.size };
try {
  out.saved = await eda.sys_FileSystem.saveFileToFileSystem(SAVE_PATH, f);
  out.path = SAVE_PATH;
} catch (e) {
  out.save_err = String(e);
}
return JSON.stringify(out);
