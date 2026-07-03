import React, { useState, useEffect, useCallback } from 'react';
import { Activity, RefreshCw, Play, Square, Zap, Globe, Shield, AlertTriangle, CheckCircle, XCircle, Clock, Loader2, Cpu, Layers, Database, TrendingUp, Brain, Bot, ChevronRight } from 'lucide-react';

const API_BASE = 'http://localhost:3334';

async function api(body: any) {
  const r = await fetch(`${API_BASE}/api/paper`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const d = await r.json();
  return d;  // 原样返回, 不抛错 (驾驶舱要容忍部分失败)
}

const fmt = (n: number | undefined) => (n ?? 0).toLocaleString();
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
const STEP_LABELS = ['全球动态', 'L1数据层', 'L2因子工厂', 'L3策略工厂', 'L4执行建议', 'L5风控验证', 'AI总控汇总', '触发交易'];

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
interface LayerInfo { name: string; icon: React.ReactNode; accent: string; data: any; lastRun: string; }

const LayerCard: React.FC<{ info: LayerInfo }> = ({ info }) => {
  const { name, icon, accent, data, lastRun } = info;
  const hasData = !!data;
  const isOk = hasData && (data.success !== false);
  return (
    <div style={{ background: '#0B0F1A', border: `1px solid ${accent}33`, borderRadius: 8, padding: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
        <span style={{ color: accent }}>{icon}</span>
        <span style={{ fontSize: 11, fontWeight: 600, color: '#CBD5E1', flex: 1 }}>{name}</span>
        <StatusDot status={hasData ? (isOk ? 'ok' : 'error') : 'pending'} />
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
  const [loading, setLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState('');

  const refresh = useCallback(async () => {
    setLoading(true);
    // 并行拉取, 容忍部分失败
    const [all, wd, sched, us] = await Promise.all([
      api({ action: 'ai_all_status' }),
      api({ action: 'watchdog_status' }),
      api({ action: 'ai_scheduler_status' }),
      api({ action: 'llm_usage', days: 1 }),
    ]);
    if (all?.success) setAllStatus(all.data);
    if (wd?.success) setWatchdog(wd.data);
    if (sched?.success) setScheduler(sched.data);
    if (us?.success) setUsage(us.data);
    setLoading(false);
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 15000);  // 15s 轮询
    return () => clearInterval(t);
  }, [refresh]);

  const doAction = useCallback(async (action: string, label: string) => {
    setActionLoading(label);
    try { await api({ action }); } catch { /* 静默 */ }
    setTimeout(refresh, 1000);
    setActionLoading('');
  }, [refresh]);

  const schedRunning = scheduler?.daemon_running;
  const schedEnabled = scheduler?.config?.enabled;
  const global = allStatus?.global;
  const operator = allStatus?.operator;
  const loopLatest = allStatus?.loop?.latest;
  const loopProgress = allStatus?.loop?.progress || [];
  const lessons = allStatus?.lessons || [];
  const todayTokens = usage?.today?.totals;

  const tradePolicy = loopLatest?.final?.trade_policy || operator?.trade_policy || operator?.plan?.trade_policy;
  const needHuman = tradePolicy && tradePolicy !== 'normal';

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

      {/* 调度器操作按钮 */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {schedRunning ? (
          <button onClick={() => doAction('ai_scheduler_stop', 'stop')} disabled={actionLoading === 'stop'}
            style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '6px 14px', background: '#7F1D1D', border: '1px solid #EF4444', borderRadius: 6, color: '#FECACA', fontSize: 11, cursor: 'pointer' }}>
            {actionLoading === 'stop' ? <Loader2 style={{ width: 12, height: 12, animation: 'spin 1s linear infinite' }} /> : <Square style={{ width: 12, height: 12 }} />}
            停止自主调度
          </button>
        ) : (
          <button onClick={() => doAction('ai_scheduler_start', 'start')} disabled={actionLoading === 'start'}
            style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '6px 14px', background: '#064E3B', border: '1px solid #10B981', borderRadius: 6, color: '#A7F3D0', fontSize: 11, cursor: 'pointer' }}>
            {actionLoading === 'start' ? <Loader2 style={{ width: 12, height: 12, animation: 'spin 1s linear infinite' }} /> : <Play style={{ width: 12, height: 12 }} />}
            启动自主调度
          </button>
        )}
        <button onClick={() => doAction('ai_scheduler_run_once', 'once')} disabled={!!actionLoading}
          style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '6px 14px', background: '#1E1B4B', border: '1px solid #6366F1', borderRadius: 6, color: '#C7D2FE', fontSize: 11, cursor: 'pointer' }}>
          <RefreshCw style={{ width: 12, height: 12 }} />
          立即巡检一轮
        </button>
        <button onClick={() => doAction('ai_loop_run', 'loop')} disabled={!!actionLoading}
          style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '6px 14px', background: '#1E1B4B', border: '1px solid #7C3AED', borderRadius: 6, color: '#DDD6FE', fontSize: 11, cursor: 'pointer' }}>
          {actionLoading === 'loop' ? <Loader2 style={{ width: 12, height: 12, animation: 'spin 1s linear infinite' }} /> : <Layers style={{ width: 12, height: 12 }} />}
          跑完整闭环
        </button>
      </div>

      {/* 主体: 左 5层 + 全球 | 右 闭环时间线 + 经验 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 14 }}>
        {/* 左列 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* 5 层状态 */}
          <Card title="五层系统状态" icon={<Layers style={{ width: 14, height: 14 }} />} accent="#38BDF8">
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              <LayerCard info={{ name: 'L1 数据层', icon: <Database style={{ width: 13, height: 13 }} />, accent: '#F59E0B',
                data: L1 ? `新鲜度: ${L1.data_layer?.status || L1.integrity?.summary ? '已检查' : '--'} · ${L1.integrity?.summary ? Object.values(L1.integrity.summary).reduce((a:number,b:number)=>a+b,0)+' 只' : ''}` : null,
                lastRun: L1?.collected_at || L1?.checked_at || '' }} />
              <LayerCard info={{ name: 'L2 因子工厂', icon: <TrendingUp style={{ width: 13, height: 13 }} />, accent: '#818CF8',
                data: L2 ? `已批准: ${L2.approved?.length || 0} · 候选: ${L2.candidates?.length || 0}` : null,
                lastRun: L2?.candidates?.[0]?.evaluated_at || '' }} />
              <LayerCard info={{ name: 'L3 策略工厂', icon: <Brain style={{ width: 13, height: 13 }} />, accent: '#34D399',
                data: L3 ? `已批准: ${L3.approved?.length || 0} · 候选: ${L3.candidates?.length || 0}` : null,
                lastRun: L3?.candidates?.[0]?.evaluated_at || '' }} />
              <LayerCard info={{ name: 'L4 执行层', icon: <Zap style={{ width: 13, height: 13 }} />, accent: '#FB923C',
                data: L4 ? `持仓 ${L4.positions?.length || 0} · 建议 ${L4.proposed_orders?.length || 0} 条` : null,
                lastRun: L4?.generated_at || '' }} />
              <LayerCard info={{ name: 'L5 风控监控', icon: <Shield style={{ width: 13, height: 13 }} />, accent: '#F472B6',
                data: L5 ? `风控: ${L5.pre_trade?.trade_allowed ? '允许交易' : '限制中'}` : null,
                lastRun: L5?.generated_at || L5?.checked_at || '' }} />
              <LayerCard info={{ name: 'L0 总控', icon: <Bot style={{ width: 13, height: 13 }} />, accent: '#A78BFA',
                data: operator ? `策略: ${operator.trade_policy || operator.plan?.trade_policy || '--'} · 建议 ${operator.actions?.length || 0} 条` : null,
                lastRun: operator?.generated_at || operator?.latest?.generated_at || '' }} />
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
