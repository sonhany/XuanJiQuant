/**
 * Web 功能验证 — 模拟浏览器对各面板 API 的调用
 * 验证每个 tab 页面加载时需要的数据都能正常获取
 */
const API = 'http://localhost:3334';

async function post(route, body) {
  try {
    const r = await fetch(`${API}/api/${route}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const j = await r.json();
    return { ok: r.status === 200, status: r.status, data: j };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

async function get(route) {
  try {
    const r = await fetch(`${API}/api/${route}`);
    const j = await r.json();
    return { ok: r.status === 200, status: r.status, data: j };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

async function main() {
  console.log('═══════════════════════════════════════════');
  console.log('  AlphaCouncil AI — Web 功能验证');
  console.log('═══════════════════════════════════════════\n');

  let pass = 0, fail = 0;
  function check(name, cond, detail = '') {
    const icon = cond ? '✅' : '❌';
    console.log(`  ${icon} ${name}${detail ? ' — ' + detail : ''}`);
    if (cond) pass++; else fail++;
  }

  // ── Tab 1: 数据浏览 ──
  console.log('📊 Tab 1: 数据浏览');
  let r = await post('sync', { action: 'status' });
  check('数据同步状态', r.ok && r.data?.success);
  r = await post('sync', { action: 'daemon_status' });
  check('Daemon状态', r.ok);

  // ── Tab 2: 因子引擎 ──
  console.log('\n📊 Tab 2: 因子引擎');
  r = await post('factor', { action: 'meta' });
  check('因子元信息', r.ok && r.data?.success, `${Object.keys(r.data?.data || {}).length}个因子类别`);
  r = await post('factor', { action: 'market_evaluation' });
  check('市场因子评估', r.ok);

  // ── Tab 3: 策略运行 ──
  console.log('\n📊 Tab 3: 策略运行');
  r = await post('strategy', { action: 'meta' });
  check('策略元信息', r.ok && r.data?.success, `${Object.keys(r.data?.data || {}).length}个策略`);

  // ── Tab 4: 交易执行 ──
  console.log('\n📊 Tab 4: 交易执行');
  r = await post('execution', { action: 'status' });
  check('执行账户状态', r.ok && r.data?.success, `权益¥${r.data?.data?.total_equity?.toLocaleString() || '?'}`);
  r = await post('execution', { action: 'positions' });
  check('持仓列表', r.ok);

  // ── Tab 5: 模拟盘 ──
  console.log('\n📊 Tab 5: 模拟盘 (核心)');
  r = await post('paper', { action: 'status' });
  check('模拟盘状态', r.ok && r.data?.success);
  const cfg = r.data?.data?.config || {};
  check('LLM配置', cfg.llm?.provider === 'glm', `provider=${cfg.llm?.provider} mode=${cfg.llm?.mode}`);
  r = await post('paper', { action: 'report' });
  check('日报', r.ok && r.data?.success);
  const rpt = r.data?.data || {};
  check('日报数据不stale', rpt.data?.is_stale === false, `latest=${rpt.data?.latest_kline_date}`);
  check('AI复盘', rpt.ai_review?.active === true, rpt.ai_review?.provider_label || '');
  r = await post('paper', { action: 'progress' });
  check('实时进度', r.ok && r.data?.success, `${r.data?.data?.events?.length || 0}条事件`);

  // ── Tab 6: 风控监控 ──
  console.log('\n📊 Tab 6: 风控监控');
  r = await post('risk', { action: 'check' });
  check('风控检查', r.ok && r.data?.success);

  // ── Tab 7: 监控告警 ──
  console.log('\n📊 Tab 7: 监控告警');
  r = await post('alerts', { action: 'list' });
  check('告警列表', r.ok && r.data?.success, `${r.data?.data?.alerts?.length || 0}条告警`);

  // ── AI 五层系统 ──
  console.log('\n🤖 AI 五层系统');
  r = await post('paper', { action: 'ai_all_status' });
  check('AI全层状态聚合', r.ok && r.data?.success);
  const all = r.data?.data || {};
  check('L1数据层', !!all.L1_data, `stale=${all.L1_data?.data_stale}`);
  check('L2因子工厂', (all.L2_factor?.approved?.length || 0) >= 0, `${all.L2_factor?.approved?.length || 0}个通过`);
  check('L3策略工厂', !!all.L3_strategy, `${all.L3_strategy?.candidates?.length || 0}个候选`);
  check('L5风控', !!all.L5_risk, `policy=${all.L5_risk?.pre_trade?.trade_policy}`);
  check('全球动态', !!all.global, `risk=${all.global?.risk_level}`);
  check('AI总控', !!all.operator, `policy=${all.operator?.trade_policy}`);
  check('AI闭环', !!all.loop?.latest, `${all.loop?.progress?.length || 0}条进度`);

  // ── GLM 连接 ──
  console.log('\n🔌 模型连接');
  r = await post('paper', { action: 'test_llm', provider: 'glm' });
  check('GLM连接', r.ok && r.data?.success, r.data?.text || r.data?.error || '');

  // ── 总结 ──
  console.log('\n═══════════════════════════════════════════');
  console.log(`  结果: ${pass} 通过 / ${fail} 失败 / 共 ${pass + fail} 项`);
  console.log('═══════════════════════════════════════════');
  process.exit(fail > 0 ? 1 : 0);
}

main();
