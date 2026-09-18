import React, { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, Bell, RefreshCw, Settings } from 'lucide-react';
import { apiHeaders, isTestAlert, statusLabel } from '../lib/workbench-state.mjs';
import { AsyncState, StatusBadge } from './WorkbenchStatus';
import { syncIntervalMs } from '../lib/data-sync-policy';

const API_BASE = (import.meta as any).env?.VITE_API_BASE || '';

async function alertApi(body: any) {
  const response = await fetch(`${API_BASE}/api/alerts`, {
    method: 'POST',
    headers: apiHeaders(),
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.success === false) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload.data || payload;
}

function alertIsStale(alert: any) {
  const raw = alert?.created_at_str || alert?.created_at;
  if (!raw) return false;
  const timestamp = typeof raw === 'number' ? raw * 1000 : Date.parse(String(raw).replace(' ', 'T'));
  return Number.isFinite(timestamp) && Date.now() - timestamp > 24 * 60 * 60 * 1000;
}

const AlertPanel: React.FC = () => {
  const [tab, setTab] = useState<'alerts' | 'rules'>('alerts');
  const [stats, setStats] = useState<any>(null);
  const [alerts, setAlerts] = useState<any[] | null>(null);
  const [rules, setRules] = useState<any[] | null>(null);
  const [filter, setFilter] = useState('active');
  const [alertClass, setAlertClass] = useState<'business' | 'test'>('business');
  const [pendingAction, setPendingAction] = useState<any>(null);
  const [operator, setOperator] = useState('');
  const [reason, setReason] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const listBody: any = { action: 'list', limit: 100 };
      if (filter !== 'all') listBody.status = filter;
      const [nextStats, nextAlerts, nextRules] = await Promise.all([
        alertApi({ action: 'stats' }),
        alertApi(listBody),
        alertApi({ action: 'rules' }),
      ]);
      setStats(nextStats);
      setAlerts(nextAlerts?.alerts || []);
      setRules(nextRules || []);
      setError('');
    } catch (err: any) {
      setError(err?.message || '告警数据不可用');
      setStats(null);
      setAlerts(null);
      setRules(null);
    } finally {
      if (!silent) setLoading(false);
    }
  }, [filter]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const schedule = () => {
      const interval = syncIntervalMs('alerts', document.hidden ? 'background' : 'active');
      timer = setTimeout(async () => {
        if (!disposed) await load(true);
        if (!disposed) schedule();
      }, interval);
    };
    schedule();
    return () => { disposed = true; if (timer) clearTimeout(timer); };
  }, [load]);

  const mutateAlert = async (alert: any, action: 'acknowledge' | 'resolve') => {
    const label = action === 'acknowledge' ? '确认告警' : '解决告警';
    if (alert.level === 'critical' && !window.confirm(`这是严重告警。确认执行“${label}”？`)) return;
    setPendingAction({ kind: 'alert', target: alert, action, label });
    setOperator('');
    setReason('');
  };

  const applyAlertAction = async (alert: any, action: 'acknowledge' | 'resolve', audit: any) => {
    const label = action === 'acknowledge' ? '确认告警' : '解决告警';
    try {
      await alertApi({ action, alert_id: alert.id, ...audit });
      await load();
    } catch (err: any) {
      setError(err?.message || `${label}失败`);
    }
  };

  const mutateRule = async (rule: any, action: 'toggle' | 'silence') => {
    const label = action === 'toggle' ? `${rule.enabled ? '禁用' : '启用'}规则` : '静默规则';
    if ((rule.level === 'critical' || action === 'silence') && !window.confirm(`该操作可能降低风险可见性。确认${label}“${rule.name}”？`)) return;
    setPendingAction({ kind: 'rule', target: rule, action, label });
    setOperator('');
    setReason('');
  };

  const applyRuleAction = async (rule: any, action: 'toggle' | 'silence', audit: any) => {
    const label = action === 'toggle' ? `${rule.enabled ? '禁用' : '启用'}规则` : '静默规则';
    try {
      await alertApi(action === 'toggle'
        ? { action: 'update_rule', id: rule.id, enabled: !rule.enabled, ...audit }
        : { action: 'silence', rule_id: rule.id, duration: 3600, ...audit });
      await load();
    } catch (err: any) {
      setError(err?.message || `${label}失败`);
    }
  };

  const submitAuditAction = async () => {
    if (!pendingAction || !operator.trim() || !reason.trim()) return;
    const audit = { operator: operator.trim(), reason: reason.trim() };
    if (pendingAction.kind === 'alert') {
      await applyAlertAction(pendingAction.target, pendingAction.action, audit);
    } else {
      await applyRuleAction(pendingAction.target, pendingAction.action, audit);
    }
    setPendingAction(null);
  };

  const visibleAlerts = (alerts || []).filter((alert) => alertClass === 'test' ? isTestAlert(alert) : !isTestAlert(alert));
  const businessCount = (alerts || []).filter((alert) => !isTestAlert(alert)).length;
  const testCount = (alerts || []).filter(isTestAlert).length;

  return (
    <div className="alert-page">
      <style>{`
        .alert-page { display: flex; flex-direction: column; gap: 14px; }
        .alert-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
        .alert-title { display: flex; align-items: center; gap: 10px; }
        .alert-title svg { width: 18px; color: #38BDF8; }
        .alert-title h1 { margin: 0; color: #F8FAFC; font-size: var(--font-page-title); }
        .alert-title p { margin: 4px 0 0; color: #64748B; font-size: var(--font-body); line-height: 1.5; }
        .alert-refresh { min-width: 72px; height: 36px; display: inline-flex; align-items: center; justify-content: center; flex: 0 0 auto; gap: 6px; padding: 0 11px; border: 1px solid #2A374B; border-radius: 6px; color: #94A3B8; background: #111827; cursor: pointer; font-size: var(--font-body); white-space: nowrap; }
        .alert-refresh svg { width: 13px; }
        .alert-tabs { display: flex; gap: 3px; width: fit-content; padding: 3px; border: 1px solid #1E293B; border-radius: 7px; background: #111827; }
        .alert-tabs button { min-height: 36px; display: inline-flex; align-items: center; gap: 6px; padding: 0 12px; border: 0; border-radius: 5px; color: #64748B; background: transparent; cursor: pointer; font-size: var(--font-body); }
        .alert-tabs button.active { color: #F8FAFC; background: #1C2738; }
        .alert-tabs svg { width: 13px; }
        .alert-stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
        .alert-stat { padding: 12px; border: 1px solid #1E293B; border-radius: 7px; background: #111827; }
        .alert-stat span, .alert-stat strong { display: block; }
        .alert-stat span { color: #64748B; font-size: var(--font-meta); }
        .alert-stat strong { margin-top: 10px; color: #F8FAFC; font: 750 var(--font-kpi) "JetBrains Mono", Consolas, monospace; }
        .alert-filters { display: flex; gap: 6px; flex-wrap: wrap; }
        .alert-filters button { min-height: 32px; padding: 0 10px; border: 1px solid #263449; border-radius: 6px; color: #64748B; background: transparent; cursor: pointer; font-size: var(--font-meta); }
        .alert-filters button.active { color: #F8FAFC; border-color: #38BDF8; background: #38BDF810; }
        .alert-list { display: grid; gap: 7px; }
        .alert-row { display: grid; grid-template-columns: 34px minmax(0, 1fr) auto; gap: 10px; padding: 11px; border: 1px solid #1E293B; border-radius: 7px; background: #111827; }
        .alert-icon { width: 34px; height: 34px; display: grid; place-items: center; border-radius: 6px; color: #FBBF24; background: #FBBF2412; }
        .alert-icon svg { width: 16px; }
        .alert-copy header { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }
        .alert-copy header strong { color: #E2E8F0; font-size: var(--font-section); }
        .alert-copy p { margin: 6px 0; color: #718096; font-size: var(--font-body); line-height: 1.55; }
        .alert-copy time { color: #526076; font-size: var(--font-meta); }
        .alert-actions { display: flex; align-items: center; gap: 6px; }
        .alert-actions button, .rule-actions button { min-height: 32px; padding: 0 10px; border: 1px solid #2A374B; border-radius: 5px; color: #94A3B8; background: #0D1422; cursor: pointer; font-size: var(--font-meta); }
        .rule-list { display: grid; gap: 7px; }
        .rule-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px; padding: 11px; border: 1px solid #1E293B; border-radius: 7px; background: #111827; }
        .rule-row strong, .rule-row span { display: block; }
        .rule-row strong { color: #E2E8F0; font-size: 11px; }
        .rule-row span { margin-top: 5px; color: #64748B; font-size: 11px; }
        .rule-actions { display: flex; align-items: center; gap: 6px; }
        .audit-guidance { padding: 9px 10px; border-left: 2px solid #38BDF8; color: #718096; background: #111827; font-size: 11px; line-height: 1.6; }
        .audit-dialog-backdrop { position: fixed; inset: 0; z-index: 120; display: grid; place-items: center; padding: 16px; background: rgba(2,6,23,.72); }
        .audit-dialog { width: min(440px, 100%); padding: 16px; border: 1px solid #334155; border-radius: 7px; background: #111827; box-shadow: 0 20px 60px rgba(0,0,0,.45); }
        .audit-dialog h2 { margin: 0; color: #F8FAFC; font-size: 15px; }
        .audit-dialog p { color: #64748B; font-size: 12px; line-height: 1.6; }
        .audit-dialog label { display: block; margin-top: 10px; color: #94A3B8; font-size: 12px; }
        .audit-dialog input, .audit-dialog textarea { width: 100%; margin-top: 5px; padding: 9px 10px; border: 1px solid #334155; border-radius: 6px; color: #E2E8F0; background: #0B1220; outline: none; }
        .audit-dialog textarea { min-height: 88px; resize: vertical; }
        .audit-dialog-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; }
        .audit-dialog-actions button { min-height: 34px; padding: 0 12px; border: 1px solid #334155; border-radius: 6px; color: #CBD5E1; background: #172235; cursor: pointer; }
        @media (max-width: 720px) { .alert-stats { grid-template-columns: repeat(2, 1fr); } .alert-row { grid-template-columns: 30px minmax(0, 1fr); } .alert-actions { grid-column: 1 / -1; justify-content: flex-end; } }
      `}</style>
      <header className="alert-head">
        <div className="alert-title"><Bell /><div><h1>告警中心</h1><p>告警确认、解决、禁用与静默均要求操作员和处理原因。</p></div></div>
        <button className="alert-refresh" type="button" onClick={load}><RefreshCw style={{ animation: loading ? 'spin 1s linear infinite' : undefined }} />刷新</button>
      </header>
      <div className="alert-tabs"><button className={tab === 'alerts' ? 'active' : ''} onClick={() => setTab('alerts')}><Bell />告警记录</button><button className={tab === 'rules' ? 'active' : ''} onClick={() => setTab('rules')}><Settings />告警规则</button></div>
      {error ? <AsyncState state="error" message={`告警数据不可用：${error}`} /> : null}
      {!error && loading && stats === null ? <AsyncState state="loading" /> : null}

      {!error && stats !== null && tab === 'alerts' ? (
        <>
          <div className="alert-stats">
            {[['业务告警', stats.business_active ?? businessCount], ['测试/演练', stats.test_active ?? testCount], ['业务严重告警', stats.business_critical_active ?? stats.critical_active], ['24h 已解决', stats.resolved_24h]].map(([label, value]) => <div className="alert-stat" key={String(label)}><span>{label}</span><strong>{value ?? '--'}</strong></div>)}
          </div>
          <div className="alert-filters">{[['active', '进行中'], ['acknowledged', '已确认'], ['resolved', '已解决'], ['all', '全部']].map(([key, label]) => <button className={filter === key ? 'active' : ''} key={key} onClick={() => setFilter(key)}>{label}</button>)}</div>
          <div className="alert-filters"><button className={alertClass === 'business' ? 'active' : ''} onClick={() => setAlertClass('business')}>业务告警</button><button className={alertClass === 'test' ? 'active' : ''} onClick={() => setAlertClass('test')}>测试/演练</button></div>
          <div className="alert-list">
            {visibleAlerts.map((alert: any, index) => (
              <article className="alert-row" key={alert.id || index}>
                <div className="alert-icon"><AlertTriangle /></div>
                <div className="alert-copy">
                  <header><strong>{alert.title || '未命名告警'}</strong><StatusBadge label={statusLabel(alert.level)} tone={alert.level === 'critical' ? 'error' : alert.level === 'warning' ? 'warn' : 'neutral'} /><StatusBadge label={statusLabel(alert.status)} tone={alert.status === 'resolved' ? 'ok' : 'neutral'} />{alert.status !== 'resolved' && alertIsStale(alert) ? <StatusBadge label="陈旧未处置" tone="warn" /> : null}</header>
                  <p>{alert.message || '无详细说明'}</p>
                  <time>{alert.created_at_str || alert.created_at || '--'}</time>
                </div>
                <div className="alert-actions">
                  {alert.status === 'active' ? <button onClick={() => mutateAlert(alert, 'acknowledge')}>确认</button> : null}
                  {alert.status !== 'resolved' ? <button onClick={() => mutateAlert(alert, 'resolve')}>解决</button> : null}
                </div>
              </article>
            ))}
            {visibleAlerts.length === 0 ? <AsyncState state="empty" message="当前筛选条件下没有告警记录。" /> : null}
          </div>
        </>
      ) : null}

      {!error && tab === 'rules' && rules !== null ? (
        <>
          <div className="audit-guidance">严重规则和静默操作会降低风险可见性，因此必须二次确认。操作员与处理原因会随请求提交，后端可据此扩展审计留痕。</div>
          <div className="rule-list">{rules.map((rule: any, index) => <article className="rule-row" key={rule.id || index}><div><strong>{rule.name || rule.id}</strong><span>{rule.desc || '无说明'} · {rule.enabled ? '已启用' : '已禁用'} · {statusLabel(rule.level)}</span></div><div className="rule-actions"><button onClick={() => mutateRule(rule, 'toggle')}>{rule.enabled ? '禁用' : '启用'}</button><button onClick={() => mutateRule(rule, 'silence')}>静默 1 小时</button></div></article>)}</div>
        </>
      ) : null}
      {pendingAction ? (
        <div className="audit-dialog-backdrop" role="presentation" onMouseDown={() => setPendingAction(null)}>
          <div className="audit-dialog" role="dialog" aria-modal="true" aria-labelledby="audit-action-title" onMouseDown={(event) => event.stopPropagation()}>
            <h2 id="audit-action-title">{pendingAction.label}</h2>
            <p>该操作会改变告警或规则状态。操作员与处理原因将随请求提交并用于审计。</p>
            <label>操作员<input autoFocus value={operator} onChange={(event) => setOperator(event.target.value)} placeholder="姓名或代号" /></label>
            <label>处理原因<textarea value={reason} onChange={(event) => setReason(event.target.value)} placeholder="填写可复核的处置依据" /></label>
            <div className="audit-dialog-actions">
              <button type="button" onClick={() => setPendingAction(null)}>取消</button>
              <button type="button" disabled={!operator.trim() || !reason.trim()} onClick={submitAuditAction}>确认提交</button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
};

export default AlertPanel;
