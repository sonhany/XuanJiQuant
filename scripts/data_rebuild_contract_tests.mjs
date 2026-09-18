import fs from 'node:fs';

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function testMissingKlineInitialFetchUsesOneYearWindow() {
  const src = fs.readFileSync('scripts/daily_update.py', 'utf-8');
  assert(
    /fetch_kline_dual\(code,\s*count=3\d\d,\s*period="1d"\)/.test(src),
    'daily_update should fetch roughly one trading year (300 bars) when rebuilding missing K-line data',
  );
}

function testFullDownloaderKeepsTdxQuantPrimary() {
  const src = fs.readFileSync('scripts/download_all.py', 'utf-8');
  const primary = src.indexOf('fetch_kline_dual(code, count=KLINE_COUNT, period="1d")');
  const bs = src.indexOf('bs_fetch(code, count=KLINE_COUNT)');
  assert(primary !== -1 && bs !== -1 && primary < bs, 'download_all should try TdxQuant reconciliation before Baostock fallback');
}

function testSourcePolicyDocumentsTdxQuantFirstSources() {
  const src = fs.readFileSync('quant/data/source_policy.py', 'utf-8');
  assert(src.includes('"realtime_primary": "tdx_quant"'), 'source policy should document TdxQuant as realtime primary source');
  assert(src.includes('"realtime_fallbacks": ["sina", "tencent"]'), 'source policy should document Sina/Tencent realtime fallback sources');
  assert(src.includes('"kline_primary": "tdx_quant"'), 'source policy should document TdxQuant as K-line primary source');
  assert(src.includes('"kline_cross_check": "tencent"'), 'source policy should document Tencent as K-line cross-check source');
  assert(src.includes('"kline_fallbacks": ["sina", "baostock"]'), 'source policy should document Sina/Baostock as K-line fallback sources');
  assert(src.includes('"historical_store": "sqlite"'), 'source policy should name SQLite as the active historical store');
  assert(src.includes('"historical_store_target": "clickhouse"'), 'source policy should retain ClickHouse only as a migration target');
  assert(src.includes('"realtime_store": "sqlite"'), 'source policy should document SQLite as realtime storage target');
  assert(src.includes('"fundamental_primary": "akshare"'), 'source policy should document AkShare as fundamental primary source');
}

function testUniverseBuildExcludesUnsupported920Codes() {
  const rebuild = fs.readFileSync('scripts/rebuild_market_data.py', 'utf-8');
  const download = fs.readFileSync('scripts/download_all.py', 'utf-8');
  assert(rebuild.includes('filter_trade_universe_codes'), 'rebuild_market_data should filter unsupported universe codes such as 920xxx');
  assert(download.includes('filter_trade_universe_codes'), 'download_all should filter unsupported universe codes such as 920xxx');
}

function testSourcePolicyUsesTdxQuant() {
  const src = fs.readFileSync('quant/data/source_policy.py', 'utf-8');
  assert(src.includes('"tdx_quant"'), 'source policy must use tdx_quant as a configured primary source');
}

function testKlineReconcilerUsesTdxQuantPrimary() {
  const src = fs.readFileSync('quant/data/kline_reconciler.py', 'utf-8');
  assert(src.includes('tdx_quant_source import fetch_klines as fetch_tdx_klines'), 'kline reconciler must import TdxQuant source');
  assert(src.includes('from quant.data.tencent_source import'), 'kline reconciler must import Tencent source');
  assert(src.includes('primary_source="tdx_quant"'), 'kline reconciler must report tdx_quant as primary source');
  assert(src.includes('cross_check_source=check.get("source")'), 'kline reconciler must record Tencent cross-check source');
}

function testFinancialReconcilerUsesAksharePrimary() {
  const src = fs.readFileSync('quant/data/financial_reconciler.py', 'utf-8');
  assert(src.includes('from quant.data.akshare_source') || src.includes('import akshare'), 'financial reconciler must use AkShare');
  assert(!src.includes('tdx_quant_source'), 'financial reconciler must not import TdxQuant source');
  assert(src.includes('"primary_source": "akshare"'), 'financial reconciler must report akshare as primary source');
}

function testParallelRebuildWorkerExists() {
  const src = fs.readFileSync('scripts/rebuild_market_data.py', 'utf-8');
  assert(src.includes('ThreadPoolExecutor'), 'rebuild worker should use parallel K-line fetching');
  assert(src.includes('fetch_kline_dual'), 'rebuild worker should use Tencent reconciliation');
}

function testRebuildMaintainsDailySummary() {
  const src = fs.readFileSync('scripts/rebuild_market_data.py', 'utf-8');
  assert(src.includes('upsert_from_bars'), 'rebuild worker should maintain stock_daily_summary while writing K-line data');
}

function testProgressPayloadIsCompact() {
  const src = fs.readFileSync('scripts/rebuild_market_data.py', 'utf-8');
  assert(src.includes('_compact_state'), 'rebuild worker should compact DB progress payloads');
  assert(src.includes('cache.set("data:rebuild:latest", _compact_state(payload))'), 'rebuild progress stored in SQLite should not include full stock lists');
}

testMissingKlineInitialFetchUsesOneYearWindow();
testFullDownloaderKeepsTdxQuantPrimary();
testSourcePolicyDocumentsTdxQuantFirstSources();
testUniverseBuildExcludesUnsupported920Codes();
testSourcePolicyUsesTdxQuant();
testKlineReconcilerUsesTdxQuantPrimary();
testFinancialReconcilerUsesAksharePrimary();
testParallelRebuildWorkerExists();
testRebuildMaintainsDailySummary();
testProgressPayloadIsCompact();

console.log('data rebuild contract tests passed');
