import fs from 'node:fs';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { PersistentRunner } from '../server/persistent_runner.mjs';

const persistentRunnerSource = fs.readFileSync('server/persistent_runner.mjs', 'utf8');
const dataRouteSource = fs.readFileSync('server/routes/data.mjs', 'utf8');
const dataRunnersSource = fs.readFileSync('server/data-runners.mjs', 'utf8');
const marketRouteSource = fs.readFileSync('server/routes/market.mjs', 'utf8');
const dataRunnerSource = fs.readFileSync('scripts/data_runner.py', 'utf8');
const dbPanelSource = fs.readFileSync('components/DbPanel.tsx', 'utf8');
const dataRunnerImports = dataRunnerSource.slice(0, dataRunnerSource.indexOf('class NpEncoder'));

const browseRunner = new PersistentRunner('data_runner.py', 'latency-test-browse');
const realtimeRunner = new PersistentRunner('data_runner.py', 'latency-test-realtime');
assert.notStrictEqual(
  browseRunner,
  realtimeRunner,
  'PersistentRunner must isolate queues when instance keys differ',
);
browseRunner.close();
realtimeRunner.close();

assert(
  persistentRunnerSource.includes('if (this.proc !== proc) return;'),
  'an old child exit must not clear the active child process reference',
);
assert(
  persistentRunnerSource.includes('this.terminating'),
  'runner replacement must wait for the timed-out child to terminate',
);

assert(
  dataRunnersSource.includes("new PersistentRunner('data_runner.py', 'data-read')"),
  'local database reads should use a dedicated data-read runner',
);
assert(
  dataRunnersSource.includes("new PersistentRunner('data_runner.py', 'data-realtime')"),
  'realtime network quotes should use a dedicated runner',
);
assert(
  dataRunnersSource.includes("new PersistentRunner('data_runner.py', 'data-stocks')"),
  'quote-backed stock lists should use their own runner',
);
assert(
  dataRouteSource.includes("if (action === 'realtime_prices') return dataRealtimeRunner"),
  'data route should isolate realtime quote polling',
);
assert(
  dataRouteSource.includes("if (action === 'stocks') return dataStocksRunner"),
  'data route should isolate TOP100 background refreshes',
);
assert(
  marketRouteSource.includes("new PersistentRunner('data_runner.py', 'market-indices')"),
  'top-bar indices should not share the data-browser queue',
);

assert(
  dataRunnerSource.includes('_schedule_realtime_view_refresh'),
  'realtime quote views should refresh in the background',
);
assert(
  dataRunnerSource.includes('_realtime_view_fallback'),
  'realtime quote views should have an immediate local fallback',
);
assert(
  dataRunnerSource.includes('refresh_if_stale'),
  'realtime quote action should expose stale-while-revalidate behavior',
);
assert(
  !dataRunnerImports.includes('import numpy as np'),
  'data browser cold start must not import NumPy only for JSON encoding',
);
assert(
  !dataRunnerImports.includes('financial_quality'),
  'data browser cold start must defer the heavy financial-quality module',
);

assert(
  dbPanelSource.includes('const realtimeLoadingRef = useRef(false)'),
  'realtime polling must prevent overlapping requests',
);
assert(
  dbPanelSource.includes("refresh_if_stale: true"),
  'realtime panel should request stale-while-revalidate snapshots',
);
assert(
  dbPanelSource.includes("if (tab !== 'kline') return;"),
  'K-line data should only load after the K-line tab is selected',
);
assert(
  dbPanelSource.includes("channels: ['market_top100']") &&
    dbPanelSource.includes('fallbackIntervalMs: 5000') &&
    !dbPanelSource.includes('setInterval(loadStocks, 15000)'),
  'market browse should use server push with one bounded fallback poll',
);
assert(
  dbPanelSource.includes('服务端完整快照推送'),
  'market browse should display its actual server-push update mode',
);
assert(
  dbPanelSource.includes("setQuoteStatus(r.stale ? 'refreshing' : 'live')"),
  'realtime panel should distinguish a fast local snapshot from refreshed quotes',
);
assert(
  dbPanelSource.includes('本地快照，后台刷新中'),
  'realtime panel should explain the initial stale-while-revalidate state',
);
assert(
  dbPanelSource.includes("stocksMeta.source === 'realtime_stale'"),
  'market browse should distinguish a stale market snapshot explicitly',
);
assert(
  dbPanelSource.includes('最近完整快照') && dbPanelSource.includes('上一交易日快照') && dbPanelSource.includes('后台刷新中'),
  'market browse should distinguish current-day expired cache from a prior-session snapshot',
);

const lazyDataImport = spawnSync(
  'python',
  ['-c', "import sys; from quant.data import create_cache; assert 'pandas' not in sys.modules; assert callable(create_cache)"],
  { cwd: process.cwd(), encoding: 'utf8' },
);
assert.equal(
  lazyDataImport.status,
  0,
  `importing the SQLite cache must not eagerly load Pandas: ${lazyDataImport.stderr}`,
);

console.log('data browser latency contract tests passed');
