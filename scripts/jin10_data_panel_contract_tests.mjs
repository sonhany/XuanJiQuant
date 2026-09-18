import assert from 'assert';
import fs from 'fs';

const app = fs.readFileSync('App.tsx', 'utf-8');
const shell = fs.readFileSync('components/AppShell.tsx', 'utf-8');
const market = fs.readFileSync('components/MarketInformationPanel.tsx', 'utf-8');
const componentPath = 'components/Jin10DataPanel.tsx';

assert(fs.existsSync(componentPath), 'Jin10 data page component must exist');
const src = fs.readFileSync(componentPath, 'utf-8');
assert(src.includes('X-XuanJi-Token'), 'Jin10 requests must carry the configured control token');

assert(shell.includes("label: '市场资讯'"), 'left navigation must expose the investor-facing market information tab');
assert(shell.includes("key: 'jin10'"), '市场资讯 tab key must be jin10');
assert(
  app.includes("const MarketInformationPanel = lazy(() => import('./components/MarketInformationPanel'))"),
  'App must lazy-load the combined market information panel',
);
assert(app.includes('jin10:') && app.includes('<MarketInformationPanel />'), 'App panels must render the combined market information panel for the jin10 tab');
assert(market.includes("import Jin10DataPanel"), 'market information panel must retain Jin10DataPanel');
assert(market.includes('<Jin10DataPanel />'), 'market information panel must render Jin10DataPanel in its source tab');
assert(!app.includes('<Jin10McpSidebar'), 'Jin10 data must not render as a sidebar card');

for (const section of ['宏观行情', '市场快讯', '新闻资讯', '财经日历']) {
  assert(src.includes(section), `Jin10 page must render section: ${section}`);
}

for (const action of ['quotes', 'flash', 'news', 'calendar']) {
  assert(src.includes(`action: '${action}'`) || src.includes(`action: "${action}"`), `Jin10 page must call /api/jin10 action=${action}`);
}

for (const action of ['flash_detail', 'news_detail']) {
  assert(src.includes(`'${action}'`) || src.includes(`"${action}"`), `Jin10 feed rows must load ${action}`);
}

assert(src.includes('data-jin10-detail-toggle'), 'Jin10 feed rows must expose a detail toggle');
assert(src.includes('data-jin10-detail-panel'), 'Jin10 feed rows must render expanded detail content');
assert(src.includes('data-jin10-detail-image'), 'Jin10 graphic flash details must render the official image');
assert(src.includes('row.title &&'), 'Jin10 feed rows must render a title independently');
assert(src.includes('row.content &&'), 'Jin10 feed rows must render content independently from the title');

for (const code of ['XAUUSD', 'USOIL', 'USDCNH', 'USDJPY']) {
  assert(src.includes(code), `Jin10 page must display macro code ${code}`);
}

assert(src.includes('MAX_LIST_ITEMS = 200'), 'Jin10 feeds and calendar must retain 200 rows');
assert(src.includes("action: 'codes'"), 'Jin10 macro page must discover all supported quote codes');
assert(src.includes('QUOTE_BATCH_SIZE = 20'), 'Jin10 quotes must respect the backend batch limit');
assert(src.includes('DEEP_FEED_PAGES = 10'), 'Jin10 deep feed load must request up to ten pages');
assert(src.includes('FULL_QUOTES_REFRESH_MS'), 'Jin10 page must use a low-frequency full-universe refresh');
assert(src.includes('CORE_QUOTES_REFRESH_MS'), 'Jin10 page must use a separate core quote refresh');
assert(src.includes('mergeLatestRows'), 'background feed refresh must merge and deduplicate recent rows');

assert(src.includes('setInterval'), 'Jin10 page must poll data automatically');
assert(!src.includes('jin10-roll'), 'Jin10 page must not use auto rolling marquee animation');
assert(src.includes('data-jin10-tab'), 'Jin10 page must expose four top tabs');
assert(src.includes("overflowY: 'auto'") || src.includes('overflowY: "auto"'), 'Jin10 page must support mouse-wheel manual browsing');
assert(src.includes('query') && src.includes('手动查询'), 'Jin10 page must support manual query');

console.log('jin10 data panel contract tests passed');
