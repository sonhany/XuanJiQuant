import fs from 'node:fs';
import assert from 'node:assert/strict';

const source = fs.readFileSync('components/DbPanel.tsx', 'utf-8');
const dbPanelStart = source.indexOf('const DbPanel: React.FC');
const rtRemoveStart = source.indexOf('const RtRemoveBtn');
const dataManageStart = source.indexOf('const DataManagePanel');
const dbPanelBody = source.slice(dbPanelStart, rtRemoveStart);
const dataManageBody = source.slice(dataManageStart);

assert(
  !source.includes('{QUICK_CODES.map'),
  'Market browse quick access must not render hard-coded QUICK_CODES',
);
assert(
  source.includes('{quickCodes.map'),
  'Market browse quick access should render realtime watchlist-backed quickCodes',
);
assert(
  !source.includes("onClick={() => { setCode(c); setTab('kline'); }}"),
  'Market browse quick access must not jump to K-line view',
);
assert(
  source.includes('selectQuickStock') && source.includes('setSelectedStock'),
  'Market browse quick access should select a stock and open the tick/detail panel in the current browse page',
);
assert(
  source.includes('setQuickCodes(merged);'),
  'Market browse quick access should not truncate the realtime watchlist',
);
assert(
  !source.includes('(local.length ? local : DEFAULT_RT_WATCH).slice(0, 16)'),
  'Market browse quick access initial state must not truncate the realtime watchlist',
);
assert(
  source.includes("watchlist_get"),
  'DbPanel should load persisted realtime watchlist for quick access',
);
assert(
  source.includes('const codes = remote.length ? remote : (local.length ? local : DEFAULT_RT_WATCH);'),
  'Market browse quick access should prefer persisted realtime watchlist exactly before fallback defaults',
);
assert(
  source.includes("xuanji:watchlist-changed"),
  'Realtime watchlist changes should notify Market Browse quick access',
);
assert(
  source.includes('onContextMenu={(e) => handleStockContextMenu(e, s)}'),
  'Top100 market rows should expose a stock right-click context menu',
);
assert(
  source.includes("new CustomEvent('xuanji-stock-context'") && source.includes("window.addEventListener('xuanji-stock-context'"),
  'Top100 right-click menu should follow the Jin10 pattern: row dispatches a custom event and parent opens the menu',
);
assert(
  source.includes('data-stock-context-menu="true"') && source.includes("window.addEventListener('scroll', close, true)"),
  'Top100 context menu should have a stable marker and close on click/scroll like the Jin10 feed menu',
);
assert(
  dbPanelBody.includes('data-stock-context-menu="true"') && dbPanelBody.includes('AI 分析证据'),
  'Stock context menu and AI modal must render inside DbPanel where ctxMenu/aiAnalysis state is defined',
);
assert(
  !dataManageBody.includes('ctxMenu') && !dataManageBody.includes('aiAnalysis'),
  'DataManagePanel must not reference DbPanel-only context menu state',
);
assert(
  !source.includes("window.addEventListener('contextmenu', close)"),
  'Top100 context menu must not globally close on contextmenu because that can immediately hide the menu after right-click',
);
assert(
  source.includes('onMouseDown={(e) => { if (e.button === 2) handleStockContextMenu(e, s); }}'),
  'Top100 market rows should also handle right-button mousedown for browser/runtime compatibility',
);
assert(
  source.includes('tabIndex={0}') && source.includes("e.key === 'ContextMenu'"),
  'Top100 market rows should expose an accessible keyboard path to the same stock operation menu',
);
assert(
  source.includes('AI 分析证据') && source.includes('只读分析，不构成自动下单指令'),
  'Right-click menu should expose bounded read-only AI evidence',
);
assert(
  !source.includes('WALL_STREET_COMMITTEE_ROLES') && !source.includes('wallStreet13'),
  'AI evidence must not restore decorative persona fan-out',
);
assert(
  source.includes('ctxMenuGoKline') && source.includes("setTab('kline')"),
  'Right-click K-line action should jump to the K-line tab for the selected stock',
);
assert(
  source.includes('ctxMenuAddWatch') && source.includes("watchlist_add"),
  'Right-click add-watch action should persist selected stock to backend watchlist',
);
assert(
  !source.includes('[...DEFAULT_RT_WATCH, ...codes, ...localCodes]'),
  'Realtime watchlist initialization must not prepend default codes when persisted/custom watchlist exists',
);
assert(
  source.includes('快速访问（自选股）'),
  'Quick access label should make the watchlist source clear',
);

const runner = fs.readFileSync('scripts/data_runner.py', 'utf-8');
assert(
  runner.includes('if isinstance(arr, list) and arr:'),
  'watchlist_get should return persisted watchlist exactly when available',
);
assert(
  !runner.includes('for item in list(DEFAULT_WATCHLIST) + list(raw):'),
  'watchlist_set must not prepend default watchlist to user selections',
);

console.log('dbpanel watchlist quick contract tests passed');
