/** XuanJiQuant Web/API read-only acceptance suite. */
import fs from 'node:fs';

const API = 'http://127.0.0.1:8880';

function token() {
  if (process.env.XUANJI_API_TOKEN) return process.env.XUANJI_API_TOKEN;
  try {
    for (const line of fs.readFileSync('.env', 'utf8').split(/\r?\n/)) {
      const [key, ...rest] = line.split('=');
      if (key?.trim() === 'XUANJI_API_TOKEN') return rest.join('=').trim().replace(/^['"]|['"]$/g, '');
    }
  } catch {}
  return '';
}

async function post(route, body) {
  const started = performance.now();
  const response = await fetch(`${API}/api/${route}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(token() ? { 'X-XuanJi-Token': token() } : {}) },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  return { ok: response.ok, status: response.status, data, ms: Math.round(performance.now() - started) };
}

async function main() {
  let passed = 0;
  let failed = 0;
  const check = (name, condition, detail = '') => {
    if (condition) { passed += 1; console.log(`PASS ${name} ${detail}`); }
    else { failed += 1; console.error(`FAIL ${name} ${detail}`); }
  };

  const checks = [
    ['驾驶舱', 'workbench', { action: 'status' }],
    ['市场数据', 'data', { action: 'stats' }],
    ['因子列表', 'factor', { action: 'meta' }],
    ['策略元数据', 'strategy', { action: 'meta' }],
    ['模拟账本', 'execution', { action: 'all', refresh_prices: false }],
    ['组合风险', 'risk', { action: 'portfolio_risk' }],
    ['系统诊断', 'risk', { action: 'system_health' }],
    ['告警统计', 'alerts', { action: 'stats' }],
    ['模拟盘状态', 'paper', { action: 'status' }],
    ['Qlib 状态', 'qlib', { action: 'status' }],
    ['数据同步状态', 'sync', { action: 'status' }],
    ['金十状态', 'jin10', { action: 'status' }],
    ['巨潮状态', 'cninfo', { action: 'status' }],
  ];

  for (const [name, route, body] of checks) {
    const result = await post(route, body);
    check(name, result.ok && result.data?.success !== false, `HTTP ${result.status} ${result.ms}ms`);
  }

  const [workbenchLedger, executionLedger, riskLedger, f5Account] = await Promise.all([
    post('workbench', { action: 'status' }),
    post('execution', { action: 'all' }),
    post('risk', { action: 'portfolio_risk' }),
    post('paper-execution', { action: 'account' }),
  ]);
  const workbenchData = workbenchLedger.data?.data ?? workbenchLedger.data;
  const executionData = executionLedger.data?.data ?? executionLedger.data;
  const riskData = riskLedger.data?.data ?? riskLedger.data;
  const f5AccountData = f5Account.data?.data ?? f5Account.data;
  const equities = [
    Number(workbenchData?.account?.total_equity),
    Number(executionData?.account?.total_equity),
    Number(riskData?.total_equity),
    Number(f5AccountData?.account?.total_equity),
  ];
  const positionCounts = [
    Number(workbenchData?.positions?.length),
    Number(executionData?.positions?.length),
    Number(riskData?.position_count),
    Number(f5AccountData?.positions?.length),
  ];
  const snapshotIds = [
    workbenchData?.account?.market_snapshot_id,
    executionData?.account?.market_snapshot_id,
    riskData?.market_snapshot_id,
    f5AccountData?.account?.market_snapshot_id,
  ].map(value => String(value || '')).filter(Boolean);
  const sameSnapshot = snapshotIds.length === 4 && new Set(snapshotIds).size === 1;
  const equitySpread = Math.max(...equities) - Math.min(...equities);
  const equityScale = Math.max(1, Math.max(...equities));
  check(
    '统一账本跨页面一致',
    equities.every(Number.isFinite)
      && (sameSnapshot ? equitySpread < 0.02 : equitySpread / equityScale < 0.001)
      && positionCounts.every((value) => value === positionCounts[0])
      && workbenchData?.ledger_authority === 'f5'
      && executionData?.ledger_authority === 'f5'
      && riskData?.ledger_authority === 'f5'
      && f5AccountData?.ledger_authority === 'f5',
    `equity=${equities.join('/')} positions=${positionCounts.join('/')} snapshot=${sameSnapshot ? 'same' : 'moving'} spread=${equitySpread.toFixed(2)}`,
  );

  const executionWrite = await post('execution', { action: 'place_order', code: '600000', quantity: 100 });
  check('自动执行关闭', executionWrite.status === 409 && executionWrite.data?.reason === 'automatic_execution_disabled');
  const paperWrite = await post('paper', { action: 'run_once' });
  check('模拟盘控制面删除', paperWrite.status === 409 && paperWrite.data?.reason === 'automatic_execution_disabled');
  const f5Status = await post('paper-execution', { action: 'status' });
  const f5Projection = f5Status.data?.data ?? f5Status.data;
  check(
    'F5 双通道状态',
    f5Status.ok
      && f5Projection?.paper_execution_capability === true
      && f5Projection?.live_execution_authority === false
      && typeof f5Projection?.execution_lane === 'string',
    `HTTP ${f5Status.status} ${f5Status.ms}ms`,
  );
  const intradayClosed = f5Projection?.execution_mode === 'paper_intraday'
    && Boolean(f5Projection?.market_fact_timestamp)
    && ['completed', 'completed_with_rejections'].includes(f5Projection?.latest_run?.status)
    && f5Projection?.latest_run?.reconciliation_passed !== false;
  const dailyPrepared = f5Projection?.execution_mode === 'paper_daily'
    && f5Projection?.market_fact_timestamp == null
    && f5Projection?.latest_run?.status === 'prepared'
    && Boolean(f5Projection?.latest_run?.intended_session);
  const currentReadiness = f5Projection?.current_readiness;
  const waitingForWindow = currentReadiness?.paper_execution_ready === true
    && currentReadiness?.market_window_allowed === false
    && ['outside_intraday_window', 'non_trading_weekday'].includes(currentReadiness?.reason_code);
  check(
    'F5 当前时钟终态有效',
    f5Status.ok && (intradayClosed || dailyPrepared || waitingForWindow),
    `HTTP ${f5Status.status} ${f5Status.ms}ms`,
  );
  const f5ArbitraryOrder = await post('paper-execution', { action: 'place_order', code: '600000', quantity: 100 });
  check(
    'F5 任意下单永久禁止',
    f5ArbitraryOrder.status === 409 && f5ArbitraryOrder.data?.reason === 'arbitrary_order_action_forbidden',
  );

  console.log(`RESULT ${passed} passed / ${failed} failed`);
  process.exitCode = failed ? 1 : 0;
}

main();
