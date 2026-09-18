import assert from 'node:assert/strict';
import fs from 'node:fs';

const dbPanel = fs.readFileSync('components/DbPanel.tsx', 'utf8');
const router = fs.readFileSync('server/router.mjs', 'utf8');
const componentPath = 'components/FinancialStatementsPanel.tsx';
const formattingPath = 'components/financialFormatting.ts';

assert(fs.existsSync(componentPath), 'FinancialStatementsPanel.tsx must exist');
assert(fs.existsSync(formattingPath), 'financialFormatting.ts must exist');
const panel = fs.readFileSync(componentPath, 'utf8');
const formatting = fs.readFileSync(formattingPath, 'utf8');
const financialUi = `${panel}\n${formatting}`;

const realtimeTab = dbPanel.indexOf("{ key: 'realtime', label: '实时行情'");
const financialTab = dbPanel.indexOf("{ key: 'financials', label: '财务报表'");
const klineTab = dbPanel.indexOf("{ key: 'kline',");

assert(realtimeTab >= 0, 'DbPanel must retain the 实时行情 tab');
assert(financialTab > realtimeTab, '财务报表 must appear after 实时行情');
assert(klineTab > financialTab, '财务报表 must appear before K线走势');
assert(
  dbPanel.includes('data-testid="data-browser-tabs"') &&
    dbPanel.includes("overflowX: 'auto'") &&
    dbPanel.includes("whiteSpace: 'nowrap'") &&
    dbPanel.includes('data-browser-tabs::-webkit-scrollbar'),
  'data browser tabs must remain single-line and horizontally scrollable on narrow screens',
);
assert(
  dbPanel.includes("tab === 'financials'") && dbPanel.includes('<FinancialStatementsPanel'),
  'DbPanel must mount FinancialStatementsPanel for the financials tab',
);
assert(
  dbPanel.includes('ctxMenuGoFinancials'),
  'Top100 context menu must dispatch the selected stock to financial statements',
);
assert(
  dbPanel.includes('<FileSpreadsheet') && dbPanel.includes('>财务报表'),
  'Top100 context menu must expose a financial statements action with an icon',
);
assert(
  dbPanel.includes('initialCode={financialStock.code}')
    && dbPanel.includes('requestKey={financialRequestKey}'),
  'DbPanel must pass the selected stock and request identity into FinancialStatementsPanel',
);
for (const existing of ['ctxMenuAiAnalysis', 'ctxMenuGoValuation', 'ctxMenuGoKline', 'ctxMenuAddWatch']) {
  assert(dbPanel.includes(existing), `existing context action ${existing} must remain`);
}
assert(
  panel.includes("action: 'financials'"),
  'FinancialStatementsPanel must query the read-only financials action',
);
assert(
  panel.includes('initialCode?: string') && panel.includes('requestKey?: number'),
  'FinancialStatementsPanel must accept a stock selection from the market browser',
);
assert(
  panel.includes('new URLSearchParams') && !panel.includes("method: 'POST'"),
  'FinancialStatementsPanel must use the read-only GET route without control-plane authorization',
);
assert(panel.includes('最新一期核心指标'), 'panel must render the latest-period decision summary');
assert(panel.includes('历史完整度'), 'panel must render historical completeness status');
assert(panel.includes('数据时效'), 'panel must render financial freshness status');
assert(panel.includes('覆盖区间'), 'panel must render financial coverage range');
assert(
  panel.includes('quality?: FinancialQuality') &&
    panel.includes('data?.quality?.completeness') &&
    panel.includes('data?.quality?.freshness') &&
    panel.includes('data?.quality?.coverage'),
  'panel must tolerate cached responses created before quality metadata existed',
);
assert(
  panel.includes('data?.quality?.completeness') &&
    panel.includes('data?.quality?.freshness') &&
    panel.includes('data?.quality?.coverage'),
  'panel must consume backend financial quality metadata',
);
assert(
  panel.includes('financial-quality-strip') &&
    panel.includes('aria-label="财务数据质量"'),
  'financial quality status must use a compact accessible strip',
);
assert(financialUi.includes('利润与现金流'), 'panel must provide the cashflow metric group');
assert(financialUi.includes('盈利能力') && financialUi.includes('成长能力'), 'panel must provide profitability and growth groups');
assert(financialUi.includes('偿债与运营') && financialUi.includes('其他指标'), 'panel must provide solvency and fallback groups');
assert(panel.includes('aria-pressed'), 'metric group buttons must expose their selected state');
assert(panel.includes('financial-period-cell'), 'the report period column must use a dedicated sticky class');
assert(panel.includes('formatFinancialValue'), 'all financial values must use semantic formatting');
assert(panel.includes('getExchangeLabel'), 'stock identity must include the inferred exchange');
assert(!panel.includes('<DataTable rows={historyRows} />'), 'the old ungrouped history table must be removed');
assert(panel.includes('数据库原始数据'), 'panel must render all raw database datasets');
assert(!panel.includes('<details open'), 'raw database datasets must be collapsed by default');
assert(
  (panel.includes('overflowX:') || panel.includes("overflow: 'auto'")) && panel.includes('sticky'),
  'wide financial tables must remain scrollable with sticky headers',
);
assert(
  router.includes("'financials'"),
  'financials must be registered as a read-only /api/data action',
);

console.log('financial statements contract tests passed');
