import React, { useCallback, useEffect, useState } from 'react';
import { Activity, FileSearch, RefreshCw, Server, Shield } from 'lucide-react';
import { apiHeaders, formatSystemField, statusLabel } from '../lib/workbench-state.mjs';
import { AsyncState, StatusBadge } from './WorkbenchStatus';
import { syncIntervalMs } from '../lib/data-sync-policy';

const API_BASE = (import.meta as any).env?.VITE_API_BASE || '';

async function riskApi(body: any) {
  const response = await fetch(`${API_BASE}/api/risk`, {
    method: 'POST',
    headers: apiHeaders(),
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.success === false) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload.data || payload;
}

function auditEventLabel(value: unknown) {
  const labels: Record<string, string> = {
    paper_run: '模拟组合运行',
    ai_decision: 'AI 决策',
    risk_decision: '风控决策',
    order: '订单',
    trade: '成交',
  };
  return labels[String(value || '')] || String(value || '事件');
}

const RiskPanel: React.FC = () => {
  const [tab, setTab] = useState<'portfolio' | 'system' | 'audit'>('portfolio');
  const [risk, setRisk] = useState<any>(null);
  const [health, setHealth] = useState<any>(null);
  const [replays, setReplays] = useState<any[]>([]);
  const [replay, setReplay] = useState<any>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    const results = await Promise.allSettled([
      riskApi({ action: 'portfolio_risk' }),
      riskApi({ action: 'system_health' }),
      riskApi({ action: 'audit_replays', limit: 20 }),
    ]);
    const nextErrors: Record<string, string> = {};
    if (results[0].status === 'fulfilled') setRisk(results[0].value);
    else { setRisk(null); nextErrors.portfolio = results[0].reason?.message || '组合风险数据不可用'; }
    if (results[1].status === 'fulfilled') setHealth(results[1].value);
    else { setHealth(null); nextErrors.system = results[1].reason?.message || '系统诊断数据不可用'; }
    if (results[2].status === 'fulfilled') setReplays(results[2].value || []);
    else { setReplays([]); nextErrors.audit = results[2].reason?.message || '审计回放数据不可用'; }
    setErrors(nextErrors);
    setLoading(false);
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const refreshPortfolio = useCallback(async () => {
    try {
      setRisk(await riskApi({ action: 'portfolio_risk' }));
      setErrors(current => ({ ...current, portfolio: '' }));
    } catch (err: any) {
      setErrors(current => ({ ...current, portfolio: err?.message || '组合风险数据不可用' }));
    }
  }, []);

  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const schedule = () => {
      const interval = syncIntervalMs('cockpit_risk', document.hidden ? 'background' : 'active');
      timer = setTimeout(async () => {
        if (!disposed) await refreshPortfolio();
        if (!disposed) schedule();
      }, interval);
    };
    schedule();
    return () => { disposed = true; if (timer) clearTimeout(timer); };
  }, [refreshPortfolio]);

  const loadReplay = async (row: any) => {
    setReplay(null);
    try {
      setReplay(await riskApi({ action: 'audit_replay', run_id: row.run_id, decision_id: row.decision_id, limit: 100 }));
      setErrors((current) => ({ ...current, replay: '' }));
    } catch (err: any) {
      setErrors((current) => ({ ...current, replay: err?.message || '回放数据不可用' }));
    }
  };

  const metrics = [
    ['VaR 95%', risk?.var_95 === null || risk?.var_95 === undefined ? '--' : `${Number(risk.var_95).toFixed(2)}%`, '1 日；历史组合快照法'],
    ['年化波动率', risk?.volatility_pct === null || risk?.volatility_pct === undefined ? '--' : `${Number(risk.volatility_pct).toFixed(2)}%`, '基于当前历史收益样本'],
    ['最大持仓集中度', risk?.concentration_pct === null || risk?.concentration_pct === undefined ? '--' : `${Number(risk.concentration_pct).toFixed(1)}%`, '最大单一证券市值占比'],
    ['总暴露', risk?.gross_exposure_pct === null || risk?.gross_exposure_pct === undefined ? '--' : `${Number(risk.gross_exposure_pct).toFixed(1)}%`, '多头市值 / 总权益'],
    ['净暴露', risk?.net_exposure_pct === null || risk?.net_exposure_pct === undefined ? '--' : `${Number(risk.net_exposure_pct).toFixed(1)}%`, '当前系统不提供卖空路径'],
    ['Expected Shortfall', risk?.expected_shortfall_pct === null || risk?.expected_shortfall_pct === undefined ? '--' : `${Number(risk.expected_shortfall_pct).toFixed(2)}%`, '当前风险引擎未提供时明确显示不可用'],
    ['风险预算占用', risk?.risk_budget_usage_pct === null || risk?.risk_budget_usage_pct === undefined ? '--' : `${Number(risk.risk_budget_usage_pct).toFixed(1)}%`, '单票集中度与总暴露相对上限的较高占用'],
    ['压力测试', risk?.stress_loss_pct === null || risk?.stress_loss_pct === undefined ? '--' : `${Number(risk.stress_loss_pct).toFixed(2)}%`, risk?.stress_scenario || '未配置压力场景时不使用伪造数值'],
    ['持仓数量', risk?.position_count ?? '--', '执行账本持仓'],
  ];
  const replayTimeline = replay ? [
    ...(replay.decisions || []).map((item: any) => ({ ...item, stage: '决策' })),
    ...(replay.risk_events || []).map((item: any) => ({ ...item, stage: '风控' })),
    ...(replay.orders || []).map((item: any) => ({ ...item, stage: '订单' })),
    ...(replay.trades || []).map((item: any) => ({ ...item, stage: '成交' })),
  ].sort((a: any, b: any) => String(a.created_at || a.time || '').localeCompare(String(b.created_at || b.time || ''))) : [];

  return (
    <div className="risk-page">
      <style>{`
        .risk-page { display: flex; flex-direction: column; gap: 14px; }
        .risk-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
        .risk-title { display: flex; align-items: center; gap: 10px; }
        .risk-title svg { width: 18px; color: #38BDF8; }
        .risk-title h1 { margin: 0; color: #F8FAFC; font-size: var(--font-page-title); }
        .risk-title p { margin: 4px 0 0; color: #64748B; font-size: var(--font-body); line-height: 1.5; }
        .risk-refresh { min-width: 72px; height: 36px; display: inline-flex; align-items: center; justify-content: center; flex: 0 0 auto; gap: 6px; padding: 0 11px; border: 1px solid #2A374B; border-radius: 6px; color: #94A3B8; background: #111827; cursor: pointer; font-size: var(--font-body); white-space: nowrap; }
        .risk-refresh svg { width: 13px; }
        .risk-tabs { display: flex; gap: 3px; padding: 3px; border: 1px solid #1E293B; border-radius: 7px; background: #111827; width: fit-content; }
        .risk-tabs button { min-height: 36px; display: inline-flex; align-items: center; gap: 6px; padding: 0 12px; border: 0; border-radius: 5px; color: #64748B; background: transparent; cursor: pointer; font-size: var(--font-body); }
        .risk-tabs button.active { color: #F8FAFC; background: #1C2738; }
        .risk-tabs svg { width: 13px; }
        .risk-metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
        .risk-metric { min-height: 106px; padding: 13px; border: 1px solid #1E293B; border-radius: 7px; background: #111827; }
        .risk-metric span, .risk-metric strong, .risk-metric small { display: block; }
        .risk-metric span { color: #64748B; font-size: var(--font-meta); }
        .risk-metric strong { margin-top: 12px; color: #F8FAFC; font: 750 var(--font-kpi) "JetBrains Mono", Consolas, monospace; }
        .risk-metric small { margin-top: 9px; color: #526076; font-size: var(--font-meta); line-height: 1.5; }
        .risk-note { padding: 10px 12px; border-left: 2px solid #FBBF24; color: #94A3B8; background: #141B26; font-size: 11px; line-height: 1.7; }
        .health-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
        .health-item { padding: 12px; border: 1px solid #1E293B; border-radius: 7px; background: #111827; }
        .health-item header { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 10px; }
        .health-item header strong { color: #CBD5E1; font-size: var(--font-section); }
        .health-item dl { display: grid; gap: 6px; margin: 0; }
        .health-item dl div { display: grid; grid-template-columns: minmax(112px, .65fr) minmax(0, 1.35fr); align-items: start; gap: 12px; font-size: var(--font-meta); }
        .health-item dt { color: #526076; } .health-item dd { min-width: 0; margin: 0; color: #94A3B8; text-align: right; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
        .audit-grid { display: grid; grid-template-columns: minmax(270px, 360px) minmax(0, 1fr); gap: 10px; }
        .audit-list, .audit-detail { min-height: 300px; padding: 10px; border: 1px solid #1E293B; border-radius: 7px; background: #111827; }
        .audit-list { display: grid; align-content: start; gap: 6px; }
        .audit-list button { padding: 9px; border: 1px solid #1E293B; border-radius: 5px; color: #CBD5E1; background: #0D1422; cursor: pointer; text-align: left; }
        .audit-list button strong, .audit-list button span { display: block; overflow-wrap: anywhere; }
        .audit-list button strong { font-size: 12px; } .audit-list button span { margin-top: 4px; color: #64748B; font-size: 11px; }
        .replay-counts { display: grid; grid-template-columns: repeat(4, 1fr); gap: 7px; }
        .replay-counts div { padding: 10px; border: 1px solid #1E293B; background: #0D1422; }
        .replay-counts span, .replay-counts strong { display: block; }
        .replay-counts span { color: #64748B; font-size: 11px; } .replay-counts strong { margin-top: 6px; color: #F8FAFC; font-size: 18px; }
        .evidence-timeline { display: grid; gap: 6px; margin-top: 12px; }
        .evidence-row { display: grid; grid-template-columns: 64px minmax(0, 1fr) auto; gap: 9px; padding: 10px; border-left: 2px solid #38BDF8; background: #0D1422; font-size: var(--font-meta); line-height: 1.5; }
        .evidence-row strong { color: #CBD5E1; } .evidence-row span { color: #64748B; overflow-wrap: anywhere; }
        @media (max-width: 850px) { .risk-metrics { grid-template-columns: repeat(2, 1fr); } .health-grid, .audit-grid { grid-template-columns: 1fr; } }
        @media (max-width: 520px) { .risk-metrics { grid-template-columns: 1fr; } .risk-tabs { width: 100%; } .risk-tabs button { flex: 1; justify-content: center; padding: 0 6px; } }
      `}</style>
      <header className="risk-head">
        <div className="risk-title"><Shield /><div><h1>风险与审计</h1><p>组合风险、系统诊断和决策回放分别展示，任何失败都不会被解释为正常。</p></div></div>
        <button className="risk-refresh" type="button" onClick={refresh}><RefreshCw style={{ animation: loading ? 'spin 1s linear infinite' : undefined }} />刷新</button>
      </header>
      <nav className="risk-tabs">
        <button className={tab === 'portfolio' ? 'active' : ''} onClick={() => setTab('portfolio')}><Shield />组合风险</button>
        <button className={tab === 'system' ? 'active' : ''} onClick={() => setTab('system')}><Server />系统诊断</button>
        <button className={tab === 'audit' ? 'active' : ''} onClick={() => setTab('audit')}><FileSearch />审计回放</button>
      </nav>

      {tab === 'portfolio' && (
        errors.portfolio ? <AsyncState state="error" message={`组合风险数据不可用：${errors.portfolio}`} /> :
        !risk ? <AsyncState state={loading ? 'loading' : 'unknown'} /> :
        <>
          <div className="risk-metrics">{metrics.map(([label, value, note]) => <div className="risk-metric" key={label}><span>{label}</span><strong>{value}</strong><small>{note}</small></div>)}</div>
          <div className="risk-note">VaR 仅为历史组合快照法的统计估计，不代表最大可能损失；模型版本、观察窗口和数据截至时间缺失时，应视为研究指标，不应用于放宽硬风控。</div>
        </>
      )}

      {tab === 'system' && (
        errors.system ? <AsyncState state="error" message={`系统诊断数据不可用：${errors.system}`} /> :
        !health ? <AsyncState state={loading ? 'loading' : 'unknown'} /> :
        <>
          <StatusBadge label={`总体 ${statusLabel(health.overall)} · 检查 ${health.checked_at || '--'}`} tone={health.overall === 'ok' ? 'ok' : 'error'} />
          <div className="health-grid">{Object.entries(health).filter(([key]) => !['overall', 'checked_at'].includes(key)).map(([key, value]: [string, any]) => (
            <div className="health-item" key={key}><header><strong>{formatSystemField(key, '').label}</strong><StatusBadge label={statusLabel(value?.status)} tone={value?.status === 'ok' ? 'ok' : 'error'} /></header><dl>{Object.entries(value || {}).filter(([field]) => field !== 'status').map(([field, fieldValue]) => { const formatted = formatSystemField(field, fieldValue); return <div key={field}><dt>{formatted.label}</dt><dd>{formatted.value}</dd></div>; })}</dl></div>
          ))}</div>
        </>
      )}

      {tab === 'audit' && (
        errors.audit ? <AsyncState state="error" message={`审计回放数据不可用：${errors.audit}`} /> :
        <div className="audit-grid">
          <div className="audit-list">{replays.map((row: any, index) => <button key={`${row.run_id || row.decision_id || "audit"}-${row.created_at || "time"}-${index}`} onClick={() => loadReplay(row)}><strong>{row.run_id || row.decision_id || '未命名运行'}</strong><span>{auditEventLabel(row.event_type)} · {row.created_at || '--'}</span></button>)}{!replays.length && <AsyncState state={loading ? 'loading' : 'empty'} compact />}</div>
          <div className="audit-detail">{errors.replay ? <AsyncState state="error" message={errors.replay} compact /> : !replay ? <AsyncState state="unknown" message="选择左侧运行记录查看决策、风控、订单与成交证据。" /> : <>
            <div className="replay-counts">{[['决策', replay.decisions?.length || 0], ['风险事件', replay.risk_events?.length || 0], ['订单', replay.orders?.length || 0], ['成交', replay.trades?.length || 0]].map(([label, value]) => <div key={String(label)}><span>{label}</span><strong>{value}</strong></div>)}</div>
            <div className="evidence-timeline"><strong style={{ color: '#CBD5E1', fontSize: 12 }}>证据时间线</strong>{replayTimeline.map((item: any, index: number) => <div className="evidence-row" key={`${item.stage}-${item.id || index}`}><strong>{item.stage}</strong><span>{item.reason || item.summary || item.event_type || item.status || item.code || '记录'}</span><span>{item.created_at || item.time || '--'}</span></div>)}{!replayTimeline.length ? <AsyncState state="empty" message="该运行只有汇总计数，尚无可展开的逐事件证据。" compact /> : null}</div>
          </>}</div>
        </div>
      )}
    </div>
  );
};

export default RiskPanel;
