import fs from 'node:fs';

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const src = fs.readFileSync('components/FactorPanel.tsx', 'utf-8');

assert(src.includes('factorStocks.snapshot_generated_at'), 'factor stock detail should render snapshot generation time');
assert(src.includes('factorStocks.data_latest_date'), 'factor stock detail should render source data latest date');
assert(src.includes('factorStocks.freshness_warning'), 'factor stock detail should render stale snapshot warning');
assert(src.includes('factorStocks.factor_definition'), 'factor stock detail should render factor definition');
assert(src.includes('factorStocks.data_version'), 'factor stock detail should render bound data version');
assert(src.includes('factorStocks.universe_policy'), 'factor stock detail should render governed universe policy');
assert(src.includes('factorStocks.promotion_state'), 'factor stock detail should render research-only state');
assert(src.includes('marketEval?.data_version'), 'market evaluation should render bound data version');
assert(src.includes('marketEval?.eligible_count'), 'market evaluation should render eligible universe count');
assert(src.includes("marketEval?.promotion_state === 'research_only'"), 'market evaluation should label research-only state');
assert(src.includes('排序依据'), 'factor stock detail should explain sort basis');
assert(src.includes('s.name || s.code'), 'factor stock rows should fall back to code only when name is absent');
assert(src.includes('chinese_name'), 'factor list should consume chinese factor names from backend meta');
assert(
  src.includes('marketEval?.data_start_date') && src.includes('marketEval?.data_end_date'),
  'factor research boundary should render the current market_eval date range fields',
);
assert(src.includes('<select value={fname}'), 'IC evaluation should use a factor dropdown instead of free text input');
assert(src.includes('因子名称'), 'IC evaluation should label the factor dropdown clearly');
assert(src.includes('股票代码'), 'IC evaluation should label the stock code input clearly');
assert(src.includes('正在更新目标日期'), 'factor panel should identify the target date while a new generation is refreshing');
assert(src.includes('当前展示上一完整版本'), 'factor panel should label the last complete generation instead of showing a mismatch error');

console.log('factor panel contract tests passed');
