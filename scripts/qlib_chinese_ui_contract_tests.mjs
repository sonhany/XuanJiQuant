import fs from 'fs';
import assert from 'assert';
import { qlibJobLabel, statusLabel } from '../lib/workbench-state.mjs';

const files = [
  'components/QlibResearchPanel.tsx',
  'components/qlib/QlibOverview.tsx',
  'components/qlib/QlibDataPanel.tsx',
  'components/qlib/QlibTrainingPanel.tsx',
  'components/qlib/QlibExperimentsPanel.tsx',
  'components/qlib/QlibModelsPanel.tsx',
  'components/qlib/QlibBacktestPanel.tsx',
  'components/qlib/QlibLogsPanel.tsx',
];
for (const file of files) assert(fs.existsSync(file), `missing Qlib UI file: ${file}`);
const source = files.map(file => fs.readFileSync(file, 'utf8')).join('\n');

for (const label of [
  '研究总览', '数据准备', '模型训练', '实验记录',
  '模型仓库', '回测评估', '任务日志',
  '六年原始行情', '点时状态覆盖率', '复权校验异常',
  '历史退市股票', 'ST 未知区间', '数据质量门禁',
  'Walk-Forward 六年基线', '窗口通过率', '最差窗口',
  'Recorder ID', '数据版本', 'Qlib 官方回测', 'A 股规则回测',
  '差异审查', '历史记录，不是活动路径',
]) {
  assert(source.includes(label), `missing Chinese Qlib label: ${label}`);
}
assert(source.includes('setInterval') && source.includes('5_000'), 'active Qlib job must poll runtime state every five seconds');
assert(source.includes('X-XuanJi-Token'), 'Qlib control requests must send the API token');
assert(source.includes('离线研究产物'), 'Qlib page must disclose the offline research boundary');
assert(source.includes('当前进度'), 'Qlib task log must show the current progress');
assert(source.includes('scrollTop ='), 'Qlib task log must keep the latest output visible');
assert(source.includes('最近任务输出'), 'Qlib task log must retain the latest completed job output');
assert(source.includes('jobs[0]'), 'Qlib panel must fetch the latest job log after completion');
assert(source.includes('Number(item.coverage || 0) * 100'), 'Qlib dataset coverage must be rendered as a percentage');
assert(source.includes('.toFixed(2)}%'), 'Qlib dataset coverage must include an explicit percent sign');
assert.equal(qlibJobLabel('collect_six_years'), '补齐六年原始行情');
assert.equal(qlibJobLabel('schedule_weekly'), '周度研究周期');
assert.equal(qlibJobLabel('workflow_quarterly_matrix'), '季度固定矩阵');
assert.equal(statusLabel('interrupted'), '已中断');
assert.equal(qlibJobLabel('quality_six_years'), '六年数据质量门禁');
assert.equal(statusLabel('succeeded'), '已成功');
assert.equal(statusLabel('shadow'), '影子验证');
assert(source.includes('qlibJobLabel('), 'Qlib job kinds must use a Chinese display mapping');
assert(source.includes('statusLabel('), 'Qlib dynamic statuses must use a Chinese display mapping');
for (const fragment of ['status?.active_job?.kind ||', '>{item.status}<', '>{job.status}<']) {
  assert(!source.includes(fragment), `Qlib must not render a raw internal value: ${fragment}`);
}
for (const allowed of ['Qlib', 'LightGBM', 'Alpha158']) {
  assert(source.includes(allowed), `Qlib product and model name should remain unchanged: ${allowed}`);
}
assert(!source.includes('\uFFFD'), 'Qlib components contain Unicode replacement characters');
for (const fragment of ['鏁版嵁', '妯″瀷', '鐮旂┒', '绂荤嚎']) {
  assert(!source.includes(fragment), `Qlib components contain mojibake: ${fragment}`);
}

console.log('qlib Chinese UI contract tests passed');
