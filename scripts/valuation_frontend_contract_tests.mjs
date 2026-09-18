import assert from 'node:assert/strict';
import fs from 'node:fs';

const dbPanel = fs.readFileSync('components/DbPanel.tsx', 'utf8');
const panelPath = 'components/ValuationPanel.tsx';

assert(
  dbPanel.includes("{ key: 'valuation', label: '股票估值'"),
  'DbPanel must add the 股票估值 tab',
);
assert(
  dbPanel.indexOf("key: 'valuation'") < dbPanel.indexOf("key: 'realtime'"),
  '股票估值 must appear immediately after 市场浏览 and before 实时行情',
);
assert(dbPanel.includes('ctxMenuGoValuation'), 'Top100 context menu must dispatch valuation');
assert(dbPanel.includes('<ValuationPanel'), 'DbPanel must render ValuationPanel');
for (const existing of ['ctxMenuAiAnalysis', 'ctxMenuGoKline', 'ctxMenuAddWatch']) {
  assert(dbPanel.includes(existing), `existing context action ${existing} must remain`);
}
assert(dbPanel.includes('<Scale'), 'valuation context action must use the Scale icon');

assert(fs.existsSync(panelPath), 'ValuationPanel.tsx must exist');
const panel = fs.readFileSync(panelPath, 'utf8');
assert(panel.includes("action: 'analyze'"), 'panel must request deterministic analysis');
assert(panel.includes("action: 'glm_analyze'"), 'panel must expose manual GLM analysis');
assert(panel.includes('手动运行 AI 估值'), 'manual valuation action must use provider-neutral copy');
assert(!panel.includes('手动运行 GLM 估值'), 'manual valuation action must not name a retired provider-specific label');
assert(
  !/useEffect\([\s\S]{0,500}glm_analyze/.test(panel),
  'GLM analysis must not be triggered by an effect or polling',
);
for (const label of ['绝对估值', '相对估值', '市场估值', 'AI 模型估值']) {
  assert(panel.includes(label), `panel must render ${label}`);
}
for (const component of ['SummaryMetric', 'ValuationTrack', 'StatusBadge']) {
  assert(
    new RegExp(`^(?:const|function) ${component}`, 'm').test(panel),
    `${component} must be declared at module scope`,
  );
}
assert(panel.includes('DCF 敏感性'), 'panel must expose DCF sensitivity');
assert(panel.includes('同行样本'), 'panel must expose peer sample details');
assert(panel.includes('数据质量与审计'), 'panel must expose audit/data-quality details');
assert(panel.includes("analysis?.consensus?.final_mid"), 'panel must use the deterministic consensus midpoint');
assert(!panel.includes('deterministicMids.reduce'), 'panel must not average absolute, relative and market tracks');
assert(panel.includes('股权资本成本 Ke'), 'panel must distinguish FCFE cost of equity from WACC');
assert(panel.includes('市场调整仅应用一次'), 'panel must disclose single market adjustment');
assert(panel.includes('point_in_time_quality'), 'panel must expose point-in-time financial quality');
assert(panel.includes('consensus?.weights?.absolute'), 'panel must expose consensus model weights');

console.log('valuation_frontend_contract_tests: PASS');
