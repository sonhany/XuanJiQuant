const DEFAULT_STALE_MS = 90_000;

export function freshnessState(timestamp, now = Date.now(), staleMs = DEFAULT_STALE_MS) {
  if (!timestamp) return { state: 'unknown', ageMs: null, label: '时间未知' };
  const parsed = typeof timestamp === 'number' ? timestamp : Date.parse(timestamp);
  if (!Number.isFinite(parsed)) return { state: 'unknown', ageMs: null, label: '时间未知' };
  const ageMs = Math.max(0, now - parsed);
  return {
    state: ageMs <= staleMs ? 'fresh' : 'stale',
    ageMs,
    label: ageMs <= staleMs ? '数据新鲜' : '数据已过期',
  };
}

export function deriveTradePermission(permission = {}) {
  if (permission.allowed !== true) {
    return {
      allowed: false,
      state: 'blocked',
      reason: permission.reason || '交易未获许可',
    };
  }
  if (permission.risk_state !== 'ok') {
    return { allowed: false, state: 'blocked', reason: '风险状态未知或异常' };
  }
  if (permission.fresh !== true) {
    return { allowed: false, state: 'blocked', reason: '关键数据已过期' };
  }
  return { allowed: true, state: 'allowed', reason: '风险检查通过' };
}

export function normalizePercentInput(value) {
  if (value === null || value === undefined || value === '') return null;
  const cleaned = typeof value === 'string' ? value.replace('%', '').trim() : value;
  const numeric = Number(cleaned);
  if (!Number.isFinite(numeric)) return null;
  const normalized = Math.abs(numeric) <= 1 ? numeric * 100 : numeric;
  return Math.min(100, Math.max(0, normalized));
}

export function toDisplayPercent(value, digits = 2) {
  if (value === null || value === undefined || value === '') return '--';
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return '--';
  const percent = Math.abs(numeric) <= 1 ? numeric * 100 : numeric;
  return `${percent.toFixed(digits)}%`;
}

export function toPercentPoints(value, digits = 2) {
  if (value === null || value === undefined || value === '') return '--';
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return '--';
  return `${numeric.toFixed(digits)}%`;
}

export function computeDayReturnPct(account = {}) {
  if (account.daily_pnl === null || account.daily_pnl === undefined) return null;
  const equity = Number(account.total_equity);
  const dailyPnl = Number(account.daily_pnl);
  const dayStartEquity = equity - dailyPnl;
  if (!Number.isFinite(equity) || !Number.isFinite(dailyPnl) || dayStartEquity <= 0) return null;
  return Number(((dailyPnl / dayStartEquity) * 100).toFixed(4));
}

export function benchmarkComparisonState(benchmark = {}) {
  const comparable = Boolean(
    benchmark
    && !benchmark.error
    && benchmark.initial_date
    && Number.isFinite(Number(benchmark.total_return_pct)),
  );
  return {
    comparable,
    reason: comparable ? '基准共同起点已确认' : '基准共同起点未提供，超额收益仅作参考',
  };
}

export function displayExecutionPrice(order = {}) {
  if (order.status === 'rejected' || order.status === 'cancelled') return '--';
  const value = Number(order.filled_price || order.price);
  return Number.isFinite(value) && value > 0 ? value.toFixed(2) : '--';
}

const EXECUTION_STATUS_LABELS = {
  filled: '已成交',
  rejected: '已拒绝',
  cancelled: '已取消',
  pending: '待处理',
  submitted: '已提交',
  partial: '部分成交',
  partially_filled: '部分成交',
  partially_filled_cancelled: '部分成交，余量取消',
  planned: '已准备',
};

export function executionStatusLabel(value) {
  const normalized = String(value || 'unknown').toLowerCase();
  return EXECUTION_STATUS_LABELS[normalized] || statusLabel(value);
}

const F5_REASON_LABELS = {
  eligible: '准入通过',
  eligible_experimental: '实验模拟准入通过',
  blocked_by_f4: 'F4 组合门禁未通过',
  positive_excess_window_ratio_below_0_60: '正超额收益窗口占比低于 60%',
  after_cost_excess_return_not_positive: '计入成本后超额收益不为正',
  sharpe_below_0_80: '夏普比率低于 0.80',
  max_drawdown_below_minus_0_20: '最大回撤低于 -20%',
  double_cost_excess_return_not_positive: '双倍成本压力下超额收益不为正',
  portfolio_policy_incompatible: '组合政策与硬风控不兼容',
  selection_stale: '研究组合已过期',
  validation_identity_mismatch: 'F4 验证身份不一致',
  data_identity_mismatch: '数据快照身份不一致',
  paper_execution_disabled: 'F5 后续模拟周期已暂停',
  kill_switch_active: 'F5 熔断已打开',
  market_facts_incomplete: '目标交易日市场事实尚不完整',
  superseded_by_intraday: '同交易日盘中模拟已完成，日频备用单已安全作废',
  reconciliation_failed: '模拟账本对账失败，已安全停机',
  transaction_rolled_back: '账本事务已回滚，等待安全重试',
  arbitrary_order_action_forbidden: '禁止任意下单操作',
  outside_intraday_window: '盘中执行窗口外',
  non_trading_weekday: '当前不是交易日',
};

export function f5ReasonLabel(value) {
  if (!value) return '暂无阻断原因';
  return F5_REASON_LABELS[String(value)] || String(value);
}

const F5_RUN_STATUS_LABELS = {
  blocked: 'F5 已就绪 · 当前被门禁阻断',
  prepared: '已准备 · 等待目标交易日',
  execution_pending: '等待完整市场事实',
  executing: '正在进行确定性模拟',
  reconciling: '正在对账',
  completed: '模拟完成且对账通过',
  completed_with_rejections: '模拟完成 · 含明确拒单',
  halted_unknown: '未知副作用 · 已熔断',
};

export function f5RunStatusLabel(value) {
  if (!value) return '尚无 F5 运行';
  return F5_RUN_STATUS_LABELS[String(value)] || String(value);
}

export function isTestAlert(alert = {}) {
  const text = [
    alert.title,
    alert.message,
    alert.source,
    alert.category,
    alert.rule_id,
  ].filter(Boolean).join(' ').toLowerCase();
  return /测试|演练|test|contract|smoke|demo/.test(text);
}

export function qlibDatasetState(dataset = {}) {
  const rows = Number(dataset.rows || 0);
  const instruments = Number(dataset.instruments || 0);
  if (dataset.status === 'ready' && (rows <= 0 || instruments <= 0)) {
    return { state: 'invalid', label: '元数据不完整' };
  }
  if (dataset.status === 'ready' && rows > 0 && instruments > 0) {
    return { state: 'ready', label: '可用于研究' };
  }
  return { state: dataset.status || 'unknown', label: dataset.status || '未知' };
}

const STATUS_LABELS = {
  ok: '正常',
  warning: '警告',
  error: '异常',
  unknown: '未知',
  running: '运行中',
  refreshing: '刷新中',
  completed: '已完成',
  stopped: '已停止',
  ready: '就绪',
  candidate: '候选',
  rejected: '已淘汰',
  invalidated: '已失效',
  filled: '已成交',
  pending: '待处理',
  cancelled: '已取消',
  active: '进行中',
  acknowledged: '已确认',
  resolved: '已解决',
  critical: '严重',
  info: '提示',
  low: '低',
  medium: '中',
  high: '高',
  fresh: '数据新鲜',
  stale: '已过期',
  live: '实时',
  current: '当前',
  queued: '排队中',
  cancelling: '取消中',
  completed: '已完成',
  failed: '失败',
  success: '成功',
  enabled: '已启用',
  disabled: '已禁用',
  idle: '空闲',
  succeeded: '已成功',
  shadow: '影子验证',
  enforced: '已强制执行',
  incomplete: '未完成',
  interrupted: '已中断',
  partial_failed: '部分失败',
  review_required: '需要人工复核',
};

export function statusLabel(value) {
  const normalized = String(value || 'unknown').toLowerCase();
  return STATUS_LABELS[normalized] || String(value || '未知');
}

const SEGMENT_LABELS = {
  train: '训练集',
  valid: '验证集',
  validation: '验证集',
  test: '测试集',
};

const QLIB_JOB_LABELS = {
  setup: '目录检查',
  schedule_weekly: '周度研究周期',
  schedule_monthly: '月度研究周期',
  schedule_quarterly: '季度研究周期',
  collect_one_year: '采集近一年行情',
  collect_six_years: '补齐六年原始行情',
  build_point_in_time: '构建点时数据',
  quality_six_years: '六年数据质量门禁',
  export_six_years: '导出六年 Qlib 数据',
  export: '导出当前数据集',
  train_smoke: '官方示例验证训练',
  train_one_year: '训练近一年基线',
  train_walk_forward: '训练六年滚动基线',
  train_regime: '训练市场状态模型',
  workflow_baseline: '周度固定基线',
  workflow_monthly_walk_forward: '月度滚动训练',
  workflow_quarterly_matrix: '季度固定矩阵',
  backtest_ashare: 'A 股规则双回测',
  resolve_backtest_divergence: '确认回测差异',
  cancel_job: '取消任务',
  promote_shadow: '人工晋升影子模型',
  collect: '数据采集',
  quality: '质量检查',
  export_stage: '数据导出',
  workflow: '官方 Workflow',
  backtest: '回测评估',
  gate: '统一门禁',
  report: '报告生成',
  tdxquant_daily: 'TdxQuant 日线',
  official_demo: '官方示例',
};

export function priorityLabel(value) {
  return statusLabel(value);
}

export function booleanLabel(value, trueLabel = '是', falseLabel = '否') {
  return value === true ? trueLabel : value === false ? falseLabel : '未知';
}

export function segmentLabel(value) {
  return SEGMENT_LABELS[String(value || '').toLowerCase()] || '未识别分段';
}

export function qlibJobLabel(value) {
  return QLIB_JOB_LABELS[String(value || '').toLowerCase()] || '未识别任务';
}

const SYSTEM_FIELD_LABELS = {
  data_layer: '数据层',
  factor_layer: '因子层',
  strategy_layer: '策略层',
  execution_layer: '执行层',
  system: '系统运行',
  stock_count: '股票数量',
  latest_date: '最新交易日',
  factor_cache_count: '因子缓存数量',
  cached_factor_count: '因子缓存数量',
  position_count: '持仓数量',
  order_count: '订单数量',
  dbsize: '数据库体积',
  db_bytes: '数据库体积',
  key_count: '缓存键数量',
  uptime: '运行状态',
  note: '状态说明',
  source: '数据来源',
  checked_at: '检查时间',
  freshness: '新鲜度',
  as_of: '数据截止时间',
  ledger_as_of: '账本更新时间',
  market_fact_as_of: '行情事实时间',
  expected_as_of: '预期截止日',
  coverage: '覆盖率',
  covered_instruments: '主日期覆盖证券',
  instrument_records: '证券记录总数',
  generation_id: '完整研究代',
  registered_factor_count: '已评估因子',
  eligible_stock_count: '可评估股票',
  authority: '权限边界',
  refresh_state: '刷新状态',
  refresh_target_date: '刷新目标日',
  reason: '状态依据',
  selection_as_of: '选股截止日',
  f4_data_as_of: 'F4 数据截止日',
  f4_status: 'F4 门禁状态',
  validation_id: '验证编号',
  mode: '执行模式',
  run_id: '运行编号',
  run_status: '运行状态',
  fill_count: '成交数量',
  strategy_quality: '策略质量',
  paper_execution_authority: '模拟执行许可',
  live_execution_authority: '实盘执行许可',
  current_readiness: '当前模拟执行准备状态',
  historical_run_reason: '历史运行原因',
};

const HEALTH_REASON_LABELS = {
  daily_refresh_pending: '日终全市场刷新尚在计划完成窗口内',
  market_daily_coverage_stale_or_incomplete: '全市场日线过期或覆盖不完整',
  research_generation_identity_invalid: '完整研究代身份或权限校验失败',
  factor_evaluation_lags_data_layer: '因子评估落后于数据层',
  factor_refreshing: '因子与选股正在生成新完整研究代',
  strategy_or_selection_identity_invalid: 'F4 或选股组合身份校验失败',
  f4_rejected: 'F4 研究候选未通过组合绩效门禁',
  f4_rejected_exhausted: 'F4 候选已穷尽且未通过组合绩效门禁',
  execution_authority_or_reconciliation_invalid: '执行权限边界或账本对账异常',
  paper_execution_has_no_run: 'F5 尚无运行记录',
  paper_execution_paused: 'F5 模拟执行已暂停或熔断',
  paper_execution_blocked: '本轮模拟执行被确定性门禁阻断',
  paper_execution_cycle_pending: '等待本执行窗口的下一轮调度',
  selection_stale: '研究组合与当前完整研究代不一致，等待刷新后重试',
  outside_intraday_window: '盘中执行窗口外',
  non_trading_weekday: '当前不是交易日',
  eligible_experimental: '实验模拟准入通过',
};

export function formatSystemField(field, value) {
  if (field === 'dbsize' || field === 'db_bytes') {
    const bytes = Number(value);
    const formatted = !Number.isFinite(bytes)
      ? '--'
      : bytes >= 1024 * 1024
        ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
        : `${(bytes / 1024).toFixed(1)} KB`;
    return { label: SYSTEM_FIELD_LABELS[field], value: formatted };
  }
  if (field === 'key_count') {
    const count = Number(value);
    return {
      label: SYSTEM_FIELD_LABELS[field],
      value: Number.isFinite(count) ? count.toLocaleString('zh-CN') : '--',
    };
  }
  if (field === 'coverage') {
    const numeric = Number(value);
    return {
      label: SYSTEM_FIELD_LABELS[field],
      value: Number.isFinite(numeric) ? `${(numeric * 100).toFixed(2)}%` : '--',
    };
  }
  if (field === 'freshness' || field === 'refresh_state') {
    return {
      label: SYSTEM_FIELD_LABELS[field],
      value: value === 'session_current'
        ? '当前交易日有效'
        : value === 'not_applicable'
          ? '日频准备不适用实时行情'
          : statusLabel(value),
    };
  }
  if (field === 'reason') {
    return {
      label: SYSTEM_FIELD_LABELS[field],
      value: value ? (HEALTH_REASON_LABELS[String(value)] || String(value)) : '无异常',
    };
  }
  if (field === 'current_readiness') {
    const readiness = value && typeof value === 'object' ? value : {};
    const parts = [
      readiness.paper_execution_ready === true
        ? '模拟许可已通过'
        : readiness.paper_execution_ready === false
          ? '模拟许可未通过'
          : '模拟许可未知',
      readiness.market_window_allowed === true
        ? '当前处于盘中执行窗口'
        : readiness.market_window_allowed === false
          ? '当前不在盘中执行窗口'
          : '执行窗口状态未知',
    ];
    if (readiness.reason_code) {
      parts.push(HEALTH_REASON_LABELS[String(readiness.reason_code)] || String(readiness.reason_code));
    }
    return { label: SYSTEM_FIELD_LABELS[field], value: parts.join('；') };
  }
  if (field === 'historical_run_reason') {
    return {
      label: SYSTEM_FIELD_LABELS[field],
      value: value ? (HEALTH_REASON_LABELS[String(value)] || String(value)) : '--',
    };
  }
  if (field === 'authority') {
    return { label: SYSTEM_FIELD_LABELS[field], value: value === 'research_only' ? '仅研究' : String(value || '--') };
  }
  if (field === 'paper_execution_authority' || field === 'live_execution_authority') {
    return { label: SYSTEM_FIELD_LABELS[field], value: booleanLabel(value, '已授权', '未授权') };
  }
  if (field === 'mode') {
    return { label: SYSTEM_FIELD_LABELS[field], value: value === 'paper_intraday' ? '盘中模拟' : value === 'paper_daily' ? '日频模拟' : String(value || '--') };
  }
  if (field === 'run_status') {
    return { label: SYSTEM_FIELD_LABELS[field], value: f5RunStatusLabel(value) };
  }
  if (field === 'strategy_quality') {
    return {
      label: SYSTEM_FIELD_LABELS[field],
      value: value === 'unqualified'
        ? '未通过研究绩效门禁'
        : value === 'invalid'
          ? '身份或新鲜度无效'
          : statusLabel(value),
    };
  }
  if (field === 'f4_status') {
    const labels = {
      f4_research_candidate: 'F4 研究候选通过',
      f4_rejected: 'F4 研究候选未通过',
      f4_rejected_exhausted: '候选已穷尽且未通过',
      f4_blocked: 'F4 输入或证据被阻断',
    };
    return { label: SYSTEM_FIELD_LABELS[field], value: labels[String(value)] || String(value || '--') };
  }
  return {
    label: SYSTEM_FIELD_LABELS[field] || String(field).replaceAll('_', ' '),
    value: value === null || value === undefined || value === '' ? '--' : String(value),
  };
}

export function roleCapabilities(role) {
  const normalized = role || 'paper-sandbox';
  return {
    canViewCockpit: true,
    canViewResearch: normalized !== 'risk-review',
    canViewRisk: true,
    canOperateSimulation: normalized === 'paper-sandbox',
    canEditStrategy: normalized === 'paper-sandbox' || normalized === 'research',
    canAcknowledgeAlerts: normalized === 'paper-sandbox' || normalized === 'risk-review',
  };
}

export function valueState(value, loaded, error) {
  if (error) return { state: 'error', value: null, error };
  if (!loaded) return { state: 'loading', value: null, error: '' };
  if (value === null || value === undefined) return { state: 'unknown', value: null, error: '' };
  return { state: 'ready', value, error: '' };
}

export function apiHeaders() {
  const token = import.meta.env?.VITE_XUANJI_API_TOKEN || import.meta.env?.VITE_API_TOKEN || '';
  return {
    'Content-Type': 'application/json',
    ...(token ? { 'X-XuanJi-Token': token } : {}),
  };
}

let workbenchStatusInFlight = null;
let workbenchStatusCached = null;
let workbenchStatusCachedAt = 0;
const WORKBENCH_STATUS_CACHE_MS = 1_000;

export async function workbenchRequest(body = { action: 'status' }, signal) {
  const apiBase = import.meta.env?.VITE_API_BASE || '';
  const request = async () => {
    const response = await fetch(`${apiBase}/api/workbench`, {
      method: 'POST',
      headers: apiHeaders(),
      body: JSON.stringify(body),
      signal,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.success === false) {
      const error = new Error(payload.error || `HTTP ${response.status}`);
      error.status = response.status;
      throw error;
    }
    return payload.data || payload;
  };
  if (signal || body?.action !== 'status') return request();
  if (workbenchStatusCached && Date.now() - workbenchStatusCachedAt < WORKBENCH_STATUS_CACHE_MS) {
    return workbenchStatusCached;
  }
  if (workbenchStatusInFlight) return workbenchStatusInFlight;
  const operation = request();
  workbenchStatusInFlight = operation;
  try {
    const result = await operation;
    workbenchStatusCached = result;
    workbenchStatusCachedAt = Date.now();
    return result;
  } finally {
    if (workbenchStatusInFlight === operation) workbenchStatusInFlight = null;
  }
}
