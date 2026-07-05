import React, { useState, useEffect, useCallback } from 'react';
import { Activity, RefreshCw, Play, Square, Zap, Globe, Shield, AlertTriangle, CheckCircle, XCircle, Clock, Loader2, Cpu, Layers, Database, TrendingUp, Brain, Bot, ChevronRight } from 'lucide-react';

const API_BASE = (import.meta as any).env?.VITE_API_BASE || '';
const API_TOKEN = (import.meta as any).env?.VITE_ALPHACOUNCIL_API_TOKEN || '';

async function api(body: any) {
  const r = await fetch(`${API_BASE}/api/paper`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(API_TOKEN ? { 'X-AlphaCouncil-Token': API_TOKEN } : {}) },
    body: JSON.stringify(body),
  });
  try {
    return await r.json();  // 原样返回, 不抛错 (驾驶舱要容忍部分失败)
  } catch {
    return { success: false, error: `HTTP ${r.status}` };
  }
}

const fmt = (n: number | undefined) => (n ?? 0).toLocaleString();
const fmtMoney = (n: number | undefined) => `¥${(n ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
const fmtPct = (n: number | undefined) => `${(n ?? 0).toFixed(2)}%`;
const fmtTime = (t: string | undefined) => t ? t.slice(11, 19) : '--';

// ─── 状态灯 ─────────────────────────────────────────────
const StatusDot: React.FC<{ status: string | boolean | undefined }> = ({ status }) => {
  let color = '#64748B';
  if (status === true || status === 'ok' || status === 'done' || status === 'pass') color = '#4ADE80';
  else if (status === 'running' || status === 'pending') color = '#FBBF24';
  else if (status === false || status === 'error' || status === 'fail' || status === 'stale' || status === 'missing') color = '#F87171';
  return <div style={{ width: 8, height: 8, borderRadius: '50%', background: color, boxShadow: `0 0 6px ${color}88`, flexShrink: 0 }} />;
};

// ─── 卡片容器 ───────────────────────────────────────────
const Card: React.FC<{ title: string; icon: React.ReactNode; children: React.ReactNode; accent?: string }> = ({ title, icon, children, accent = '#475569' }) => (
  <div style={{ background: '#111827', border: `1px solid ${accent}33`, borderRadius: 10, overflow: 'hidden' }}>
    <div style={{ padding: '10px 14px', background: '#0B0F1A', borderBottom: `1px solid ${accent}22`, display: 'flex', alignItems: 'center', gap: 8 }}>
      <span style={{ color: accent }}>{icon}</span>
      <span style={{ fontSize: 12, fontWeight: 600, color: '#CBD5E1' }}>{title}</span>
    </div>
    <div style={{ padding: 12 }}>{children}</div>
  </div>
);

// ─── 闭环步骤时间线 ─────────────────────────────────────
const LoopTimeline: React.FC<{ progress: any[] }> = ({ progress }) => {
  if (!progress || progress.length === 0) {
    return <div style={{ fontSize: 11, color: '#475569', textAlign: 'center', padding: '12px 0' }}>暂无闭环运行记录</div>;
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {progress.slice(-12).map((p, i) => {
        const status = p.status;
        const icon = status === 'done' ? <CheckCircle style={{ width: 12, height: 12, color: '#4ADE80' }} />
          : status === 'error' ? <XCircle style={{ width: 12, height: 12, color: '#F87171' }} />
          : status === 'skip' ? <ChevronRight style={{ width: 12, height: 12, color: '#64748B' }} />
          : <Loader2 style={{ width: 12, height: 12, color: '#FBBF24', animation: 'spin 1s linear infinite' }} />;
        return (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 8px', background: '#0B0F1A', borderRadius: 6 }}>
            {icon}
            <span style={{ fontSize: 11, color: '#CBD5E1', minWidth: 90 }}>{p.step}</span>
            <span style={{ fontSize: 10, color: p.status === 'error' ? '#F87171' : p.status === 'done' ? '#4ADE80' : '#64748B', flex: 1 }}>
              {p.detail ? p.detail.slice(0, 50) : p.status}
            </span>
            <span style={{ fontSize: 9, color: '#475569', fontFamily: 'JetBrains Mono, monospace' }}>{fmtTime(p.time)}</span>
          </div>
        );
      })}
    </div>
  );
};

// ─── 层状态卡片 ─────────────────────────────────────────
interface LayerInfo { name: string; icon: React.ReactNode; accent: string; data: any; lastRun: string; status?: string | boolean; }

const LayerCard: React.FC<{ info: LayerInfo }> = ({ info }) => {
  const { name, icon, accent, data, lastRun, status } = info;
  const hasData = !!data;
  const isOk = status !== undefined ? (status === true || status === 'ok' || status === 'done' || status === 'pass') : hasData && (data.success !== false);
  return (
    <div style={{ background: '#0B0F1A', border: `1px solid ${accent}33`, borderRadius: 8, padding: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
        <span style={{ color: accent }}>{icon}</span>
        <span style={{ fontSize: 11, fontWeight: 600, color: '#CBD5E1', flex: 1 }}>{name}</span>
        <StatusDot status={status !== undefined ? status : (hasData ? (isOk ? 'ok' : 'error') : 'pending')} />
      </div>
      <div style={{ fontSize: 9, color: '#64748B' }}>最后运行: {fmtTime(lastRun) || '未运行'}</div>
      {data && <div style={{ fontSize: 10, color: '#94A3B8', marginTop: 4 }}>{data}</div>}
    </div>
  );
};

// ─── 主面板 ─────────────────────────────────────────────
const DashboardPanel: React.FC = () => {
  const [allStatus, setAllStatus] = useState<any>(null);
  const [watchdog, setWatchdog] = useState<any>(null);
  const [scheduler, setScheduler] = useState<any>(null);
  const [usage, setUsage] = useState<any>(null);
  const [autonomous, setAutonomous] = useState<any>(null);
  const [autoConfig, setAutoConfig] = useState<any>({ target_equity: 100000000, horizon_days: 365, provider: 'glm', ultra_thinking: { enabled: true }, risk: { max_position_pct: 0.2, max_gross_exposure_pct: 95, max_position_count: 10, max_daily_turnover_pct: 35 } });
  const [loading, setLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState('');
  const [actionError, setActionError] = useState('');
  const [actionMessage, setActionMessage] = useState('');

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      // 并行拉取, 容忍部分失败
      const [all, wd, sched, us, auto] = await Promise.all([
        api({ action: 'ai_all_status' }),
        api({ action: 'watchdog_status' }),
        api({ action: 'ai_scheduler_status' }),
        api({ action: 'llm_usage', days: 1 }),
        api({ action: 'ai_autonomous_status' }),
      ]);
      if (all?.success) setAllStatus(all.data);
      if (wd?.success) setWatchdog(wd.data);
      if (sched?.success) setScheduler(sched.data);
      if (us?.success) setUsage(us.data);
      if (auto?.success) {
        setAutonomous(auto.data);
        if (auto.data?.config) setAutoConfig(auto.data.config);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 15000);  // 15s 轮询
    return () => clearInterval(t);
  }, [refresh]);

  const doAction = useCallback(async (action: string, label: string, extra: any = {}) => {
    setActionLoading(label);
    setActionError('');
    setActionMessage('');
    try {
      const r = await api({ action, ...extra });
      if (!r?.success) {
        setActionError(r?.error || '操作失败');
      } else {
        setActionMessage(r?.message || r?.data?.message || '操作已提交');
      }
    } catch (e: any) {
      setActionError(e?.message || '网络请求失败');
    }
    setTimeout(refresh, 1000);
    setActionLoading('');
  }, [refresh]);

  const schedRunning = scheduler?.daemon_running;
  const global = allStatus?.global;
  const operator = allStatus?.operator;
  const loopLatest = allStatus?.loop?.latest;
  const loopProgress = allStatus?.loop?.progress || [];
  const lessons = allStatus?.lessons || [];
  const memory = allStatus?.memory || {};
  const verifier = allStatus?.verifier || scheduler?.verifier;
  const toolExecutor = allStatus?.tool_executor || scheduler?.tool_executor;
  const updates = allStatus?.updates || scheduler?.updates;
  const memoryStats = memory?.stats || scheduler?.memory;
  const todayTokens = usage?.today?.totals;

  const objective = autonomous?.objective || allStatus?.objective;
  const portfolio = autonomous?.portfolio || allStatus?.portfolio;
  const committee = autonomous?.committee || allStatus?.committee;
  const loopTradePolicy = loopLatest?.skipped ? null : loopLatest?.final?.trade_policy;
  const operatorTradePolicy = operator?.skipped ? null : (operator?.trade_policy || operator?.plan?.trade_policy);
  const tradePolicy = loopTradePolicy || operatorTradePolicy;
  const needHuman = tradePolicy && tradePolicy !== 'normal';

  const updateAutoConfig = (path: string, value: any) => {
    setAutoConfig((cfg: any) => {
      const next = { ...cfg, risk: { ...(cfg.risk || {}) }, ultra_thinking: { ...(cfg.ultra_thinking || {}) } };
      if (path.startsWith('risk.')) next.risk[path.slice(5)] = value;
      else if (path.startsWith('ultra_thinking.')) next.ultra_thinking[path.slice(15)] = value;
      else next[path] = value;
      return next;
    });
  };

  const saveAutonomousConfig = () => doAction('ai_autonomous_set_config', 'auto_save', { config: autoConfig });

  const L1 = allStatus?.L1_data;
  const L2 = allStatus?.L2_factor;
  const L3 = allStatus?.L3_strategy;
  const L4 = allStatus?.L4_execution;
  const L5 = allStatus?.L5_risk;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {/* 顶栏: 系统健康 + 操作 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Cpu style={{ width: 18, height: 18, color: '#38BDF8' }} />
          <span style={{ fontSize: 16, fontWeight: 700, color: '#E2E8F0' }}>AI 自主进化量化系统 · 驾驶舱</span>
          {loading && <Loader2 style={{ width: 12, height: 12, color: '#38BDF8', animation: 'spin 1s linear infinite' }} />}
        </div>
        <button onClick={refresh} style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '6px 12px', background: '#1E293B', border: '1px solid #334155', borderRadius: 6, color: '#94A3B8', fontSize: 11, cursor: 'pointer' }}>
          <RefreshCw style={{ width: 12, height: 12 }} /> 刷新
        </button>
      </div>

      {!API_TOKEN && (
        <div style={{ padding: '8px 12px', background: '#451A03', border: '1px solid #F59E0B', borderRadius: 8, fontSize: 11, color: '#FDE68A' }}>
          ⚠ 未配置 VITE_ALPHACOUNCIL_API_TOKEN。若后端设置了 ALPHACOUNCIL_API_TOKEN，控制按钮会返回 403。
        </div>
      )}
      {actionError && (
        <div style={{ padding: '8px 12px', background: '#7F1D1D', border: '1px solid #EF4444', borderRadius: 8, fontSize: 11, color: '#FECACA' }}>
          操作失败: {actionError}
        </div>
      )}
      {actionMessage && !actionError && (
        <div style={{ padding: '8px 12px', background: '#052E2B', border: '1px solid #10B981', borderRadius: 8, fontSize: 11, color: '#A7F3D0' }}>
          {actionMessage}
        </div>
      )}

      {/* 重大决策提示 */}
      {needHuman && (
        <div style={{ padding: '10px 14px', background: '#7F1D1D', border: '1px solid #EF4444', borderRadius: 8, display: 'flex', alignItems: 'center', gap: 8 }}>
          <AlertTriangle style={{ width: 16, height: 16, color: '#FCA5A5' }} />
          <span style={{ fontSize: 12, color: '#FECACA', fontWeight: 600 }}>
            需人工参与决策: 当前交易策略 = <b>{tradePolicy}</b> (非 normal)
            {global?.risk_level === 'high' && ' · 全球高风险'}
          </span>
        </div>
      )}

      {/* 系统健康指标行 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
        <div style={{ background: '#0B0F1A', border: '1px solid #1E293B', borderRadius: 8, padding: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
            <Activity style={{ width: 12, height: 12, color: schedRunning ? '#4ADE80' : '#64748B' }} />
            <span style={{ fontSize: 10, color: '#64748B' }}>自主调度器</span>
          </div>
          <div style={{ fontSize: 13, fontWeight: 700, color: schedRunning ? '#4ADE80' : '#64748B' }}>
            {schedRunning ? '运行中' : '已停止'}
          </div>
          <div style={{ fontSize: 9, color: '#475569' }}>模式: {scheduler?.current_mode || '--'} · 巡检 {scheduler?.cycles_count || 0} 次</div>
        </div>

        <div style={{ background: '#0B0F1A', border: '1px solid #1E293B', borderRadius: 8, padding: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
            <Shield style={{ width: 12, height: 12, color: watchdog?.paper_alive ? '#4ADE80' : '#64748B' }} />
            <span style={{ fontSize: 10, color: '#64748B' }}>看门狗</span>
          </div>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#38BDF8' }}>
            {watchdog ? '活跃' : '待启动'}
          </div>
          <div style={{ fontSize: 9, color: '#475569' }}>
            paper: {watchdog?.paper_alive ? '✓' : '✗'} · sched: {watchdog?.scheduler_alive ? '✓' : '✗'} · 重启 {watchdog?.restarts_total || 0}
          </div>
        </div>

        <div style={{ background: '#0B0F1A', border: '1px solid #1E293B', borderRadius: 8, padding: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
            <Clock style={{ width: 12, height: 12, color: '#FBBF24' }} />
            <span style={{ fontSize: 10, color: '#64748B' }}>最后巡检</span>
          </div>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#E2E8F0', fontFamily: 'JetBrains Mono, monospace' }}>
            {loopLatest?.finished_at?.slice(11, 19) || scheduler?.last_cycle_at?.slice(11, 19) || '--'}
          </div>
          <div style={{ fontSize: 9, color: '#475569' }}>下次: {scheduler?.next_cycle_at?.slice(11, 19) || '--'}</div>
        </div>

        <div style={{ background: '#0B0F1A', border: '1px solid #1E293B', borderRadius: 8, padding: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
            <Zap style={{ width: 12, height: 12, color: '#A78BFA' }} />
            <span style={{ fontSize: 10, color: '#64748B' }}>今日 Token</span>
          </div>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#C4B5FD', fontFamily: 'JetBrains Mono, monospace' }}>
            {fmt(todayTokens?.total_tokens)}
          </div>
          <div style={{ fontSize: 9, color: '#475569' }}>{todayTokens?.calls || 0} 次调用</div>
        </div>
      </div>

      {/* 全局 AI 自主目标控制 */}
      <Card title="AI 自主调度控制 · 1年目标1亿" icon={<Bot style={{ width: 14, height: 14 }} />} accent="#F59E0B">
        <div style={{ display: 'grid', gridTemplateColumns: '1.1fr 1fr', gap: 12 }}>
          <div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 10 }}>
              <div style={{ background: '#0B0F1A', borderRadius: 8, padding: 8 }}><div style={{ fontSize: 9, color: '#64748B' }}>目标权益</div><div style={{ fontSize: 13, color: '#FDE68A', fontWeight: 700 }}>{fmtMoney(objective?.target_equity || autoConfig?.target_equity)}</div></div>
              <div style={{ background: '#0B0F1A', borderRadius: 8, padding: 8 }}><div style={{ fontSize: 9, color: '#64748B' }}>当前权益</div><div style={{ fontSize: 13, color: '#E2E8F0', fontWeight: 700 }}>{fmtMoney(objective?.current_equity)}</div></div>
              <div style={{ background: '#0B0F1A', borderRadius: 8, padding: 8 }}><div style={{ fontSize: 9, color: '#64748B' }}>目标进度</div><div style={{ fontSize: 13, color: '#38BDF8', fontWeight: 700 }}>{fmtPct(objective?.progress_pct)}</div></div>
              <div style={{ background: '#0B0F1A', borderRadius: 8, padding: 8 }}><div style={{ fontSize: 9, color: '#64748B' }}>剩余天数</div><div style={{ fontSize: 13, color: '#CBD5E1', fontWeight: 700 }}>{objective?.remaining_days ?? '--'}</div></div>
            </div>
            <div style={{ fontSize: 10, color: '#94A3B8', marginBottom: 8 }}>
              风险模式: <b style={{ color: objective?.risk_mode === 'normal' ? '#4ADE80' : '#FBBF24' }}>{objective?.risk_mode || '--'}</b> · 目标压力: {objective?.objective_pressure || '--'} · 需年化: {fmtPct(objective?.required_annualized_return_pct)} · 需月化: {fmtPct(objective?.required_monthly_return_pct)}
            </div>
            {/* 层级关系说明 */}
            <div style={{ fontSize: 9, color: '#475569', marginBottom: 8, padding: '5px 8px', background: '#0B0F1A', borderRadius: 5, fontFamily: 'JetBrains Mono, monospace' }}>
              调度器(心跳) → AI闭环(五层思考) → 模拟盘(策略执行) → 订单成交
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6 }}>
              <input type="number" value={autoConfig?.target_equity || 100000000} onChange={e => updateAutoConfig('target_equity', Number(e.target.value))} style={{ background: '#0B0F1A', border: '1px solid #334155', borderRadius: 6, color: '#E2E8F0', padding: '6px 8px', fontSize: 11 }} />
              <input type="number" value={autoConfig?.horizon_days || 365} onChange={e => updateAutoConfig('horizon_days', Number(e.target.value))} style={{ background: '#0B0F1A', border: '1px solid #334155', borderRadius: 6, color: '#E2E8F0', padding: '6px 8px', fontSize: 11 }} />
              <select value={autoConfig?.provider || 'glm'} onChange={e => updateAutoConfig('provider', e.target.value)} style={{ background: '#0B0F1A', border: '1px solid #334155', borderRadius: 6, color: '#E2E8F0', padding: '6px 8px', fontSize: 11 }}><option value="glm">GLM</option><option value="deepseek">DeepSeek</option><option value="qwen">Qwen</option><option value="gemini">Gemini</option></select>
              <label style={{ display: 'flex', alignItems: 'center', gap: 5, background: '#0B0F1A', border: '1px solid #334155', borderRadius: 6, color: '#CBD5E1', padding: '6px 8px', fontSize: 11 }}><input type="checkbox" checked={autoConfig?.ultra_thinking?.enabled !== false} onChange={e => updateAutoConfig('ultra_thinking.enabled', e.target.checked)} /> ultra</label>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, marginTop: 6 }}>
              <input type="number" step="0.01" value={autoConfig?.risk?.max_position_pct ?? 0.2} onChange={e => updateAutoConfig('risk.max_position_pct', Number(e.target.value))} title="单股上限" style={{ background: '#0B0F1A', border: '1px solid #334155', borderRadius: 6, color: '#E2E8F0', padding: '6px 8px', fontSize: 11 }} />
              <input type="number" value={autoConfig?.risk?.max_gross_exposure_pct ?? 95} onChange={e => updateAutoConfig('risk.max_gross_exposure_pct', Number(e.target.value))} title="总暴露%" style={{ background: '#0B0F1A', border: '1px solid #334155', borderRadius: 6, color: '#E2E8F0', padding: '6px 8px', fontSize: 11 }} />
              <input type="number" value={autoConfig?.risk?.max_position_count ?? 10} onChange={e => updateAutoConfig('risk.max_position_count', Number(e.target.value))} title="最大持仓数" style={{ background: '#0B0F1A', border: '1px solid #334155', borderRadius: 6, color: '#E2E8F0', padding: '6px 8px', fontSize: 11 }} />
              <input type="number" value={autoConfig?.risk?.max_daily_turnover_pct ?? 35} onChange={e => updateAutoConfig('risk.max_daily_turnover_pct', Number(e.target.value))} title="日换手%" style={{ background: '#0B0F1A', border: '1px solid #334155', borderRadius: 6, color: '#E2E8F0', padding: '6px 8px', fontSize: 11 }} />
            </div>
            <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap', alignItems: 'center' }}>
              <button onClick={saveAutonomousConfig} disabled={!!actionLoading} style={{ padding: '6px 12px', background: '#451A03', border: '1px solid #F59E0B', borderRadius: 6, color: '#FDE68A', fontSize: 11, cursor: 'pointer' }}>保存目标配置</button>
              {schedRunning ? (
                <button onClick={() => doAction('ai_scheduler_stop', 'stop')} disabled={!!actionLoading} style={{ padding: '6px 12px', background: '#7F1D1D', border: '1px solid #EF4444', borderRadius: 6, color: '#FECACA', fontSize: 11, cursor: 'pointer' }}>
                  {actionLoading === 'stop' ? <Loader2 style={{ width: 12, height: 12, animation: 'spin 1s linear infinite' }} /> : <Square style={{ width: 12, height: 12 }} />}
                  停止 AI 自主调度
                </button>
              ) : (
                <button onClick={async () => { await doAction('ai_autonomous_set_config', 'auto_save', { config: autoConfig }); await doAction('ai_scheduler_start', 'start', { provider: autoConfig?.provider }); }} disabled={!!actionLoading} style={{ padding: '6px 12px', background: '#064E3B', border: '1px solid #10B981', borderRadius: 6, color: '#A7F3D0', fontSize: 11, cursor: 'pointer' }}>
                  {actionLoading === 'start' ? <Loader2 style={{ width: 12, height: 12, animation: 'spin 1s linear infinite' }} /> : <Play style={{ width: 12, height: 12 }} />}
                  启动 AI 自主调度
                </button>
              )}
              <button onClick={() => doAction('ai_scheduler_run_once', 'once')} disabled={!!actionLoading} title="按时段自动决定工作量: 盘中轻巡检, 盘后跑完整闭环" style={{ padding: '6px 12px', background: '#1E1B4B', border: '1px solid #6366F1', borderRadius: 6, color: '#C7D2FE', fontSize: 11, cursor: 'pointer' }}>
                <RefreshCw style={{ width: 12, height: 12 }} />
                立即跑一轮
              </button>
              <button onClick={() => doAction('ai_loop_run', 'loop')} disabled={!!actionLoading} title="调试用: 无视时段强制跑9步AI闭环" style={{ padding: '6px 12px', background: '#1E1B4B', border: '1px solid #7C3AED', borderRadius: 6, color: '#A78BFA', fontSize: 10, cursor: 'pointer', opacity: 0.8 }}>
                {actionLoading === 'loop' ? <Loader2 style={{ width: 12, height: 12, animation: 'spin 1s linear infinite' }} /> : <Layers style={{ width: 12, height: 12 }} />}
                调试:完整闭环
              </button>
            </div>
          </div>
          <div style={{ background: '#0B0F1A', border: '1px solid #334155', borderRadius: 8, padding: 10 }}>
            <div style={{ fontSize: 11, color: '#CBD5E1', fontWeight: 600, marginBottom: 6 }}>最新目标组合</div>
            {(portfolio?.target_weights || []).slice(0, 6).map((w: any, i: number) => <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#94A3B8', padding: '3px 0', borderBottom: '1px solid #1E293B' }}><span>{w.code}</span><span>{fmtPct((w.target_weight || 0) * 100)} · {Math.round((w.confidence || 0) * 100)}%</span></div>)}
            {!(portfolio?.target_weights || []).length && <div style={{ fontSize: 10, color: '#64748B' }}>暂无目标组合，等待 AI 闭环生成</div>}
            <div style={{ fontSize: 10, color: '#64748B', marginTop: 8 }}>{portfolio?.summary || committee?.roles?.slice(-1)?.[0]?.data?.summary || '委员会尚未运行'}</div>
          </div>
        </div>
      </Card>

      {/* 主体: 左 5层 + 全球 | 右 闭环时间线 + 经验 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 14 }}>
        {/* 左列 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* 5 层状态 */}
          <Card title="五层系统状态" icon={<Layers style={{ width: 14, height: 14 }} />} accent="#38BDF8">
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              <LayerCard info={{ name: 'L1 数据层', icon: <Database style={{ width: 13, height: 13 }} />, accent: '#F59E0B',
                data: L1 ? `新鲜度: ${L1.data_layer?.status || L1.integrity?.summary ? '已检查' : '--'} · ${L1.integrity?.summary ? Object.values(L1.integrity.summary).reduce((a:number,b:number)=>a+b,0)+' 只' : ''}` : null,
                lastRun: L1?.collected_at || L1?.checked_at || '', status: L1?.success === false ? 'error' : (L1 ? 'ok' : 'pending') }} />
              <LayerCard info={{ name: 'L2 因子工厂', icon: <TrendingUp style={{ width: 13, height: 13 }} />, accent: '#818CF8',
                data: L2 ? `已批准: ${L2.approved?.length || 0} · 候选: ${L2.candidates?.length || 0}` : null,
                lastRun: L2?.candidates?.[0]?.evaluated_at || '', status: L2?.success === false ? 'error' : (L2 ? 'ok' : 'pending') }} />
              <LayerCard info={{ name: 'L3 策略工厂', icon: <Brain style={{ width: 13, height: 13 }} />, accent: '#34D399',
                data: L3 ? `已批准: ${L3.approved?.length || 0} · 候选: ${L3.candidates?.length || 0}` : null,
                lastRun: L3?.candidates?.[0]?.evaluated_at || '', status: L3?.success === false ? 'error' : (L3 ? 'ok' : 'pending') }} />
              <LayerCard info={{ name: 'L4 执行层', icon: <Zap style={{ width: 13, height: 13 }} />, accent: '#FB923C',
                data: L4 ? `持仓 ${L4.positions?.length || 0} · 建议 ${L4.proposed_orders?.length || 0} 条` : null,
                lastRun: L4?.generated_at || '', status: L4?.success === false ? 'error' : (L4 ? 'ok' : 'pending') }} />
              <LayerCard info={{ name: 'L5 风控监控', icon: <Shield style={{ width: 13, height: 13 }} />, accent: '#F472B6',
                data: L5 ? `风控: ${L5.pre_trade?.trade_allowed ? '允许交易' : '限制中'}` : null,
                lastRun: L5?.generated_at || L5?.checked_at || '', status: L5?.success === false ? 'error' : (L5?.pre_trade?.trade_allowed ? 'ok' : L5 ? 'pending' : 'pending') }} />
              <LayerCard info={{ name: 'L0 总控', icon: <Bot style={{ width: 13, height: 13 }} />, accent: '#A78BFA',
                data: operator ? `策略: ${operator.trade_policy || operator.plan?.trade_policy || '--'} · 建议 ${operator.actions?.length || 0} 条` : null,
                lastRun: operator?.generated_at || operator?.latest?.generated_at || '', status: operator?.success === false ? 'error' : (operator ? 'ok' : 'pending') }} />
            </div>
          </Card>

          {/* 自主控制面 */}
          <Card title="AI 自主控制面" icon={<Bot style={{ width: 14, height: 14 }} />} accent="#22C55E">
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              <div style={{ background: '#0B0F1A', border: '1px solid #334155', borderRadius: 8, padding: 10 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                  <StatusDot status={toolExecutor?.status || (toolExecutor?.running ? 'running' : toolExecutor ? 'done' : 'pending')} />
                  <span style={{ fontSize: 11, color: '#CBD5E1', fontWeight: 600 }}>工具执行器</span>
                </div>
                <div style={{ fontSize: 10, color: '#94A3B8' }}>
                  状态: {toolExecutor?.status || '--'} · 动作 {toolExecutor?.actions?.length || 0}
                </div>
                <div style={{ fontSize: 9, color: '#64748B', marginTop: 3 }}>
                  最近: {toolExecutor?.actions?.slice(-1)?.[0]?.tool || '--'}
                </div>
              </div>
              <div style={{ background: '#0B0F1A', border: '1px solid #334155', borderRadius: 8, padding: 10 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                  <StatusDot status={verifier?.overall || verifier?.latest?.overall || 'pending'} />
                  <span style={{ fontSize: 11, color: '#CBD5E1', fontWeight: 600 }}>自我验证</span>
                </div>
                <div style={{ fontSize: 10, color: '#94A3B8' }}>
                  结果: {verifier?.overall || verifier?.latest?.overall || '--'} · 失败 {verifier?.failed?.length || verifier?.latest?.failed?.length || 0}
                </div>
                <div style={{ fontSize: 9, color: '#64748B', marginTop: 3 }}>
                  {verifier?.generated_at || verifier?.latest?.generated_at || '--'}
                </div>
              </div>
              <div style={{ background: '#0B0F1A', border: '1px solid #334155', borderRadius: 8, padding: 10 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                  <StatusDot status={memoryStats ? 'ok' : 'pending'} />
                  <span style={{ fontSize: 11, color: '#CBD5E1', fontWeight: 600 }}>记忆系统</span>
                </div>
                <div style={{ fontSize: 10, color: '#94A3B8' }}>
                  总数: {memoryStats?.total || 0} · 来源 {Object.keys(memoryStats?.sources || {}).length}
                </div>
                <div style={{ fontSize: 9, color: '#64748B', marginTop: 3 }}>
                  最新: {memoryStats?.latest_at || '--'}
                </div>
              </div>
              <div style={{ background: '#0B0F1A', border: '1px solid #334155', borderRadius: 8, padding: 10 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                  <StatusDot status={updates?.latest ? 'pending' : 'ok'} />
                  <span style={{ fontSize: 11, color: '#CBD5E1', fontWeight: 600 }}>受控更新</span>
                </div>
                <div style={{ fontSize: 10, color: '#94A3B8' }}>
                  待审: {updates?.pending || 0} · 风险 {updates?.latest?.risk || '--'}
                </div>
                <div style={{ fontSize: 9, color: '#64748B', marginTop: 3 }}>
                  {updates?.latest?.title || '仅生成提案, 不自动改代码'}
                </div>
              </div>
            </div>
          </Card>

          {/* 全球动态 */}
          <Card title="全球实时动态" icon={<Globe style={{ width: 14, height: 14 }} />} accent="#06B6D4">
            {global ? (
              <div>
                <div style={{ display: 'flex', gap: 12, marginBottom: 8, flexWrap: 'wrap' }}>
                  <div>
                    <span style={{ fontSize: 9, color: '#64748B' }}>风险等级</span>
                    <div style={{ fontSize: 14, fontWeight: 700,
                      color: global.risk_level === 'high' ? '#F87171' : global.risk_level === 'medium' ? '#FBBF24' : '#4ADE80' }}>
                      {global.risk_level === 'high' ? '高 🔴' : global.risk_level === 'medium' ? '中 🟡' : '低 🟢'}
                    </div>
                  </div>
                  <div>
                    <span style={{ fontSize: 9, color: '#64748B' }}>交易策略</span>
                    <div style={{ fontSize: 14, fontWeight: 700, color: '#E2E8F0' }}>{global.trade_policy}</div>
                  </div>
                </div>
                {global.risk_signals?.length > 0 && (
                  <div style={{ fontSize: 10, color: '#94A3B8' }}>
                    {global.risk_signals.map((s: string, i: number) => <div key={i}>⚠ {s}</div>)}
                  </div>
                )}
                {global.stale && (
                  <div style={{ fontSize: 10, color: '#FBBF24', marginTop: 6 }}>⚠ {global.error || '全球动态使用缓存数据'}</div>
                )}
                {/* 主要指数 — 按分类分组展示, 完整覆盖日韩等新增标的 */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
                  {Object.entries(global.global_indices || {}).map(([cat, items]: any) => {
                    const list = (items || []).filter(x => x && typeof x.chg_pct === 'number');
                    if (!list.length) return null;
                    return (
                      <div key={cat} style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                        <div style={{ fontSize: 9, color: '#475569', letterSpacing: 0.3 }}>{cat}</div>
                        <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                          {list.map((idx: any, i: number) => (
                            <span key={`${cat}-${i}-${idx.name}`} style={{ fontSize: 9, padding: '2px 6px', background: '#0B0F1A', borderRadius: 4,
                              color: idx.chg_pct >= 0 ? '#4ADE80' : '#F87171', fontFamily: 'JetBrains Mono, monospace' }}>
                              {idx.name}: {idx.chg_pct >= 0 ? '+' : ''}{Number(idx.chg_pct || 0).toFixed(2)}%
                            </span>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            ) : <div style={{ fontSize: 11, color: '#475569', textAlign: 'center', padding: '8px 0' }}>暂无全球动态数据</div>}
          </Card>
        </div>

        {/* 右列 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* 闭环时间线 */}
          <Card title="AI 闭环时间线" icon={<Activity style={{ width: 14, height: 14 }} />} accent="#A78BFA">
            <div style={{ fontSize: 9, color: '#475569', marginBottom: 8 }}>
              最近完成: {loopLatest?.finished_at?.slice(11, 19) || '--'} · 错误: {loopLatest?.errors?.length || 0}
            </div>
            <LoopTimeline progress={loopProgress} />
          </Card>

          {/* 经验记忆 */}
          <Card title="经验记忆 (最近 5 条)" icon={<Brain style={{ width: 14, height: 14 }} />} accent="#10B981">
            {memory?.summary?.summary && (
              <div style={{ fontSize: 10, color: '#A7F3D0', padding: '6px 8px', background: '#052E2B', borderRadius: 5, marginBottom: 6 }}>
                {String(memory.summary.summary).slice(0, 160)}
              </div>
            )}
            {lessons.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                {lessons.slice(-5).reverse().map((l: any, i: number) => (
                  <div key={i} style={{ fontSize: 10, color: '#94A3B8', padding: '4px 8px', background: '#0B0F1A', borderRadius: 5, borderLeft: '2px solid #10B981' }}>
                    <span style={{ color: '#64748B' }}>[{l.type || l.date}]</span> {l.content?.slice(0, 80)}
                  </div>
                ))}
              </div>
            ) : <div style={{ fontSize: 11, color: '#475569', textAlign: 'center', padding: '8px 0' }}>暂无经验记录</div>}
          </Card>
        </div>
      </div>
    </div>
  );
};

export default DashboardPanel;
