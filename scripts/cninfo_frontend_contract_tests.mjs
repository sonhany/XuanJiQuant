import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync('App.tsx', 'utf8');
const shell = fs.readFileSync('components/AppShell.tsx', 'utf8');
const marketPath = 'components/MarketInformationPanel.tsx';
const panelPath = 'components/CninfoDisclosurePanel.tsx';

assert(fs.existsSync(marketPath), 'MarketInformationPanel must exist');
assert(fs.existsSync(panelPath), 'CninfoDisclosurePanel must exist');

const market = fs.readFileSync(marketPath, 'utf8');
const panel = fs.readFileSync(panelPath, 'utf8');

assert(
  app.includes("const MarketInformationPanel = lazy(() => import('./components/MarketInformationPanel'))"),
  'App must lazy-load MarketInformationPanel',
);
assert(app.includes('jin10: <MarketInformationPanel />'), 'market information navigation must render the combined panel');
assert(market.includes('金十数据') && market.includes('巨潮公告'), 'combined panel must expose sibling source tabs');
assert(market.includes('定期报告'), 'Cninfo source description must include periodic financial reports');
assert(market.includes('<Jin10DataPanel />') && market.includes('<CninfoDisclosurePanel />'), 'combined panel must retain both source panels');
assert(!shell.includes("key: 'cninfo'"), 'Cninfo must not add another sidebar item');

assert(panel.includes('/api/cninfo'), 'Cninfo panel must call the local Cninfo API');
assert(panel.includes("preset: 'latest'") || panel.includes("value: 'latest'"), 'Cninfo panel must expose latest announcements');
assert(panel.includes('performance_express') && panel.includes('业绩快报'), 'Cninfo panel must expose performance express announcements');
assert(panel.includes('performance_forecast') && panel.includes('业绩预告'), 'Cninfo panel must expose performance forecast announcements');
assert(panel.includes('periodic_report') && panel.includes('业绩公告'), 'Cninfo panel must expose periodic financial reports');
assert(panel.includes('股票代码') && panel.includes('关键词'), 'Cninfo panel must support stock and keyword filters');
assert(panel.includes('start_date') && panel.includes('end_date'), 'Cninfo panel must support a bounded date range');
assert(panel.includes('data-cninfo-original-link'), 'announcement rows must expose an official original link');
assert(panel.includes('data-cninfo-loading'), 'Cninfo panel must provide a stable loading marker');
assert(panel.includes('data-cninfo-empty'), 'Cninfo panel must provide an actionable empty state');
assert(panel.includes('ResearchBoundary'), 'Cninfo panel must state its external research boundary');
assert(panel.includes('CNINFO_INFLIGHT'), 'identical Cninfo requests must be coalesced under React Strict Mode');
assert(panel.includes('选择公告类型和筛选条件后查询'), 'Cninfo must provide an explicit pre-query state');
assert(panel.includes('CNINFO_POLL_MS') && panel.includes('setInterval'), 'current announcement preset must refresh automatically');
assert(panel.includes("runQuery(filters.preset"), 'automatic refresh must query the currently selected preset');
assert(!panel.includes("filters.preset === 'latest'"), 'automatic refresh must not be limited to latest announcements');
assert(panel.includes("action: 'detail'"), 'announcement rows must load readable detail content');
assert(panel.includes('cninfo-detail-drawer'), 'announcement content must open in an in-app detail drawer');
assert(panel.includes('<iframe'), 'the detail drawer must retain the official PDF reader fallback');

console.log('cninfo frontend contract tests passed');
