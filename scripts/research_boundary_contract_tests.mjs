import fs from 'node:fs';
import assert from 'node:assert/strict';

for (const file of [
  'components/DbPanel.tsx',
  'components/FactorPanel.tsx',
  'components/StrategyPanel.tsx',
  'components/Jin10DataPanel.tsx',
  'components/QlibResearchPanel.tsx',
]) {
  const source = fs.readFileSync(file, 'utf8');
  assert(source.includes('ResearchBoundary'), `${file} must expose its research/operations boundary`);
}

const boundary = fs.readFileSync('components/ResearchBoundary.tsx', 'utf8');
assert(boundary.includes('不构成可直接执行的生产交易信号'), 'research results must not be represented as production orders');
assert(boundary.includes('鉴权失败不等于内容为空'), 'external authorization failures must differ from empty content');
assert(boundary.includes('来源：'), 'boundaries must expose provenance');
assert(boundary.includes('截至：'), 'boundaries must expose as-of context');

const readme = fs.readFileSync('README.md', 'utf8');
const handoff = fs.readFileSync('docs/XUANJI_HANDOFF.md', 'utf8');
const workflowMap = fs.readFileSync('docs/XUANJI_SYSTEM_WORKFLOW_MAP.md', 'utf8');
const qlibGuide = fs.readFileSync('docs/QLIB_LOCAL_TRAINING.md', 'utf8');
assert(readme.includes('ResearchTrainingScheduler'), 'README must name deterministic research scheduling ownership');
assert(handoff.includes('ResearchJobStore'), 'handoff must explain the independent research job ledger');
assert(handoff.includes('research_only'), 'handoff must explain the research-only promotion boundary');
for (const token of [
  'XuanJiQuant-Paper-Daily',
  'data/paper/f5_ledger.db',
  'paper_execution_authority',
  'live_execution_authority=false',
  'blocked_by_f4',
]) {
  assert(
    readme.includes(token) || handoff.includes(token) || workflowMap.includes(token),
    `F5 boundary documentation must include ${token}`,
  );
}
assert(
  qlibGuide.includes('C:\\Users\\HYSHEN\\XuanJiQuant\\data\\qlib'),
  'Qlib guide must name the active project-local data root',
);
for (const schedule of ['交易日 16:20', '周日 10:00', '周六 18:30']) {
  assert(qlibGuide.includes(schedule), `Qlib guide must document ${schedule}`);
}
for (const [name, source] of [
  ['README', readme],
  ['handoff', handoff],
  ['workflow map', workflowMap],
]) {
  for (const token of [
    'research_selection',
    'F4/PIT 数据截止日',
    '当前因子/选股日',
    '不构成交易信号',
  ]) {
    assert(source.includes(token), `${name} must document selection visibility token ${token}`);
  }
}
for (const [name, source] of [
  ['README', readme],
  ['handoff', handoff],
  ['workflow map', workflowMap],
]) {
  for (const token of [
    'XuanJiQuant-Research-Daily',
    '交易日 16:20',
    'XuanJiQuant-Qlib-Weekly',
    '周六 18:30',
    'XuanJiQuant-Strategy-Weekly',
    '周日 10:00',
    'research_selection_daily',
    '失败关闭',
    'research_only',
  ]) {
    assert(source.includes(token), `${name} must document ${token}`);
  }
}
for (const forbiddenPromotion of ['paper_active', 'production_candidate', 'approved', 'live']) {
  assert(
    handoff.includes(forbiddenPromotion),
    `handoff must document scheduler prohibition for ${forbiddenPromotion}`,
  );
}

for (const token of [
  'f4-multi-alpha-candidate-factory-v2',
  '24 个预登记候选',
  'factory-v2/<factory_run_id>',
  '只有窗口锁定胜者可以读取 test',
  'promotion_state=research_only',
  'execution_authority=false',
]) {
  assert(
    readme.includes(token) || handoff.includes(token),
    `F4 v2 handoff must include ${token}`,
  );
}

console.log('research boundary contract tests passed');
