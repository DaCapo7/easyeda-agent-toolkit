// 例 1: 连通性探针 —— 拿到桥之后第一条该跑的作业
// 跑法: python ../tools/eda_bridge.py run 00_probe.js
//
// 作用: 确认桥能真的执行 JS、并列出当前工程里所有板的 uuid。
// 后面几乎所有脚本都要用 parentBoardName 去定位板, 先在这里抄下来。

const pcbs = await eda.dmt_Pcb.getAllPcbsInfo() || [];
const schs = await eda.dmt_Schematic.getAllSchematicsInfo() || [];

return JSON.stringify({
  boardCount: pcbs.length,
  pcbs: pcbs.map(p => ({
    parentBoardName: p.parentBoardName,   // 脚本参数里传的就是它
    pcbName: p.name,                      // 嘉立创侧显示的 PCBn 编号
    uuid: p.uuid
  })),
  schematics: schs.map(s => ({
    parentBoardName: s.parentBoardName,
    schName: s.name,
    uuid: s.uuid
  }))
});
