import React, { useState, useEffect, useCallback } from 'react';
import {
  Bell, BellRing, RefreshCw, Loader2, AlertTriangle,
  CheckCircle, XCircle, Info, X, ChevronDown, Settings,
} from 'lucide-react';

const API_BASE = (import.meta as any).env?.VITE_API_BASE || '';
const API_TOKEN = (import.meta as any).env?.VITE_ALPHACOUNCIL_API_TOKEN || '';
const jsonHeaders = () => ({ 'Content-Type': 'application/json', ...(API_TOKEN ? { 'X-AlphaCouncil-Token': API_TOKEN } : {}) });
const ACCENT = '#FB7185';  // rose

async function api(body: any) {
  const r = await fetch(`${API_BASE}/api/alerts`, { method: 'POST', headers: jsonHeaders(), body: JSON.stringify(body) });
  const d = await r.json();
  if (!d.success) throw new Error(d.error || '请求失败');
  return d.data;
}

// ─── Helpers ────────────────────────────────────────────
const LEVEL_CONFIG = {
  critical: { color: '#EF4444', bg: '#EF444422', border: '#EF444444', label: '严重', Icon: XCircle },
  warning:  { color: '#F59E0B', bg: '#F59E0B22', border: '#F59E0B44', label: '警告', Icon: AlertTriangle },
  info:     { color: '#60A5FA', bg: '#60A5FA22', border: '#60A5FA44', label: '提示', Icon: Info },
};

const STATUS_CONFIG = {
  active:        { color: '#EF4444', label: '进行中' },
  acknowledged:  { color: '#F59E0B', label: '已确认' },
  resolved:      { color: '#22C55E', label: '已解决' },
};

const CATEGORY_LABELS: Record<string, string> = {
  system: '系统', risk: '风控', pnl: '盈亏', data: '数据', execution: '交易',
};

function timeAgo(ts: number): string {
  const diff = (Date.now() / 1000) - ts;
  if (diff < 60) return `${Math.floor(diff)}s 前`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m 前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h 前`;
  return `${Math.floor(diff / 86400)}d 前`;
}

// ─── Alert Row ─────────────────────────────────────────
const AlertRow: React.FC<{
  alert: any;
  onAck: (id: string) => void;
  onResolve: (id: string) => void;
}> = ({ alert, onAck, onResolve }) => {
  const cfg = LEVEL_CONFIG[alert.level] || LEVEL_CONFIG.info;
  const StatusCfg = STATUS_CONFIG[alert.status] || STATUS_CONFIG.active;
  const Icon = cfg.Icon;
  const catLabel = CATEGORY_LABELS[alert.category] || alert.category;

  return (
    <div style={{
      background: alert.status === 'active' ? cfg.bg : '#111827',
      border: `1px solid ${alert.status === 'active' ? cfg.border : '#1E293B'}`,
      borderRadius: 10,
      padding: '12px 14px',
      display: 'flex',
      alignItems: 'flex-start',
      gap: 12,
      transition: 'all 150ms',
    }}>
      {/* Icon */}
      <div style={{
        width: 32, height: 32, borderRadius: 8,
        background: `${cfg.color}22`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        flexShrink: 0, marginTop: 1,
      }}>
        <Icon style={{ width: 16, height: 16, color: cfg.color }} />
      </div>

      {/* Content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: '#E2E8F0' }}>{alert.title}</span>
          <span style={{ fontSize: 10, padding: '1px 7px', borderRadius: 10, background: `${cfg.color}22`, color: cfg.color, fontWeight: 600, border: `1px solid ${cfg.color}44` }}>
            {cfg.label}
          </span>
          <span style={{ fontSize: 10, padding: '1px 7px', borderRadius: 10, background: '#1E293B', color: '#64748B' }}>
            {catLabel}
          </span>
          <span style={{ fontSize: 10, padding: '1px 7px', borderRadius: 10, background: '#1E293B', color: StatusCfg.color, border: `1px solid ${StatusCfg.color}44` }}>
            {StatusCfg.label}
          </span>
        </div>
        <div style={{ fontSize: 12, color: '#64748B', marginBottom: 6 }}>{alert.message}</div>
        <div style={{ fontSize: 11, color: '#475569' }}>
          {alert.created_at_str && <span>{alert.created_at_str}</span>}
          {alert.acknowledged_at && <span style={{ marginLeft: 10 }}>确认: {timeAgo(alert.acknowledged_at)}</span>}
          {alert.resolved_at && <span style={{ marginLeft: 10 }}>解决: {timeAgo(alert.resolved_at)}</span>}
          {!alert.acknowledged_at && !alert.resolved_at && <span>{timeAgo(alert.created_at)}</span>}
        </div>
      </div>

      {/* Actions */}
      {alert.status === 'active' && (
        <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
          <button onClick={() => onAck(alert.id)}
            style={{ padding: '5px 10px', borderRadius: 6, border: '1px solid #1E293B', background: '#1E293B', color: '#94A3B8', fontSize: 11, cursor: 'pointer' }}>
            确认
          </button>
          <button onClick={() => onResolve(alert.id)}
            style={{ padding: '5px 10px', borderRadius: 6, border: '1px solid #22C55E44', background: '#22C55E22', color: '#4ADE80', fontSize: 11, cursor: 'pointer' }}>
            解决
          </button>
        </div>
      )}
      {alert.status === 'acknowledged' && (
        <button onClick={() => onResolve(alert.id)}
          style={{ padding: '5px 10px', borderRadius: 6, border: '1px solid #22C55E44', background: '#22C55E22', color: '#4ADE80', fontSize: 11, cursor: 'pointer', flexShrink: 0 }}>
          解决
        </button>
      )}
    </div>
  );
};

// ─── Stats Bar ──────────────────────────────────────────
const StatsBar: React.FC<{ stats: any }> = ({ stats }) => (
  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
    {[
      { label: '活跃告警', value: stats?.active || 0, color: '#F87171', critical: true },
      { label: '严重告警', value: stats?.critical_active || 0, color: '#EF4444', critical: true },
      { label: '已解决 (24h)', value: stats?.resolved_24h || 0, color: '#22C55E' },
      { label: '总记录', value: stats?.total || 0, color: '#94A3B8' },
    ].map(({ label, value, color, critical }) => (
      <div key={label} style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, padding: '14px 16px', textAlign: 'center' }}>
        <div style={{ fontSize: 10, color: '#475569', marginBottom: 6 }}>{label}</div>
        <div style={{ fontSize: 28, fontWeight: 800, fontFamily: 'JetBrains Mono, monospace', color }}>
          {value}
          {critical && (value as number) > 0 && (
            <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: '#EF4444', marginLeft: 6, boxShadow: '0 0 6px #EF4444' }} />
          )}
        </div>
      </div>
    ))}
  </div>
);

// ─── Rule Item ─────────────────────────────────────────
const RuleItem: React.FC<{ rule: any; onToggle: (id: string, enabled: boolean) => void; onSilence: (id: string) => void }> =
  ({ rule, onToggle, onSilence }) => {
    const cfg = LEVEL_CONFIG[rule.level] || LEVEL_CONFIG.info;
    return (
      <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 10, padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: '#E2E8F0' }}>{rule.name}</span>
            <span style={{ fontSize: 10, padding: '1px 7px', borderRadius: 10, background: `${cfg.color}22`, color: cfg.color, fontWeight: 600, border: `1px solid ${cfg.color}44` }}>
              {cfg.label}
            </span>
          </div>
          <div style={{ fontSize: 11, color: '#475569' }}>{rule.desc}</div>
        </div>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', flexShrink: 0 }}>
          <span style={{ fontSize: 11, color: '#475569' }}>{rule.enabled ? '启用' : '禁用'}</span>
          <div
            onClick={() => onToggle(rule.id, !rule.enabled)}
            style={{
              width: 36, height: 20, borderRadius: 10,
              background: rule.enabled ? '#22C55E' : '#334155',
              position: 'relative', transition: 'background 200ms', cursor: 'pointer',
            }}>
            <div style={{
              width: 16, height: 16, borderRadius: '50%',
              background: 'white',
              position: 'absolute', top: 2,
              left: rule.enabled ? 18 : 2,
              transition: 'left 200ms',
            }} />
          </div>
        </label>
        <button onClick={() => onSilence(rule.id)}
          style={{ padding: '4px 8px', borderRadius: 6, border: '1px solid #1E293B', background: '#1E293B', color: '#64748B', fontSize: 10, cursor: 'pointer' }}>
          静默
        </button>
      </div>
    );
  };

// ─── Alert Panel ────────────────────────────────────────
const AlertPanel: React.FC = () => {
  const [tab, setTab] = useState<'alerts'|'rules'>('alerts');
  const [alerts, setAlerts] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [activeCount, setActiveCount] = useState(0);
  const [criticalCount, setCriticalCount] = useState(0);
  const [stats, setStats] = useState<any>({});
  const [rules, setRules] = useState<any[]>([]);
  const [filter, setFilter] = useState<'all'|'active'|'acknowledged'|'resolved'>('all');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const loadStats = useCallback(async () => {
    try {
      const d = await api({ action: 'stats' });
      setStats(d);
      setActiveCount(d.active || 0);
      setCriticalCount(d.critical_active || 0);
    } catch (_) {}
  }, []);

  const loadAlerts = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const body: any = { action: 'list', limit: 50 };
      if (filter !== 'all') body.status = filter;
      const d = await api(body);
      setAlerts(d.alerts || []);
      setTotal(d.total || 0);
      setActiveCount(d.active_count || 0);
      setCriticalCount(d.critical_count || 0);
    } catch (e: any) { setError(e.message); }
    setLoading(false);
  }, [filter]);

  const loadRules = useCallback(async () => {
    try {
      const d = await api({ action: 'rules' });
      setRules(d || []);
    } catch (_) {}
  }, []);

  useEffect(() => { loadStats(); loadAlerts(); loadRules(); }, []);

  const handleCheck = useCallback(async () => {
    setLoading(true);
    try {
      await api({ action: 'check' });
      await loadAlerts();
      await loadStats();
    } catch (e: any) { setError(e.message); }
    setLoading(false);
  }, [loadAlerts, loadStats]);

  const handleAck = useCallback(async (id: string) => {
    try { await api({ action: 'acknowledge', alert_id: id }); await loadAlerts(); await loadStats(); }
    catch (e: any) { setError(e.message); }
  }, [loadAlerts, loadStats]);

  const handleResolve = useCallback(async (id: string) => {
    try { await api({ action: 'resolve', alert_id: id }); await loadAlerts(); await loadStats(); }
    catch (e: any) { setError(e.message); }
  }, [loadAlerts, loadStats]);

  const handleToggleRule = useCallback(async (id: string, enabled: boolean) => {
    try { await api({ action: 'update_rule', id, enabled }); await loadRules(); }
    catch (e: any) { setError(e.message); }
  }, [loadRules]);

  const handleSilence = useCallback(async (id: string) => {
    try { await api({ action: 'silence', rule_id: id, duration: 3600 }); await loadRules(); }
    catch (e: any) { setError(e.message); }
  }, [loadRules]);

  const filteredAlerts = alerts;

  const tabs = [
    { key: 'alerts', label: '告警记录', count: activeCount },
    { key: 'rules',  label: '告警规则', count: rules.length },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 22 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ width: 40, height: 40, borderRadius: 10, background: `${ACCENT}22`, border: `1px solid ${ACCENT}44`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            {criticalCount > 0
              ? <BellRing style={{ width: 20, height: 20, color: ACCENT }} />
              : <Bell style={{ width: 20, height: 20, color: ACCENT }} />}
          </div>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, color: '#F1F5F9' }}>监控告警</div>
            <div style={{ fontSize: 11, color: '#64748B' }}>系统健康 · 持仓风险 · 盈亏预警 · 追踪止损</div>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {criticalCount > 0 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, background: '#EF444422', border: '1px solid #EF444444', borderRadius: 20, padding: '4px 12px' }}>
              <div style={{ width: 6, height: 6, borderRadius: '50%', background: '#EF4444', animation: 'pulse 1.5s infinite' }} />
              <span style={{ fontSize: 11, color: '#F87171', fontWeight: 600 }}>{criticalCount} 严重告警</span>
            </div>
          )}
          <button onClick={handleCheck} disabled={loading}
            style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '7px 14px', background: '#111827', border: '1px solid #1E293B', borderRadius: 8, color: '#64748B', fontSize: 12, cursor: 'pointer' }}>
            <RefreshCw style={{ width: 12, height: 12, animation: loading ? 'spin 1s linear infinite' : 'none' }} />
            扫描告警
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 4, background: '#111827', padding: 4, borderRadius: 10, border: '1px solid #1E293B', width: 'fit-content' }}>
        {tabs.map(t => {
          const is = tab === t.key;
          return (
            <button key={t.key} onClick={() => setTab(t.key as typeof tab)}
              style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 16px', borderRadius: 7, border: 'none', cursor: 'pointer', fontSize: 13, fontWeight: is ? 600 : 400,
                background: is ? `${ACCENT}18` : 'transparent', color: is ? ACCENT : '#64748B', transition: 'all 150ms' }}>
              {t.label}
              {t.count > 0 && (
                <span style={{ fontSize: 10, background: is ? `${ACCENT}33` : '#1E293B', color: is ? ACCENT : '#64748B', padding: '1px 6px', borderRadius: 10, fontWeight: 700 }}>
                  {t.count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Error */}
      {error && (
        <div style={{ padding: '10px 14px', background: '#EF444414', border: '1px solid #EF444433', borderRadius: 8, fontSize: 12, color: '#F87171' }}>
          <AlertTriangle style={{ width: 12, height: 12, display: 'inline', marginRight: 6 }} />{error}
          <button onClick={() => setError('')} style={{ marginLeft: 10, background: 'none', border: 'none', color: '#F87171', cursor: 'pointer', fontSize: 12 }}>×</button>
        </div>
      )}

      {/* ── 告警记录 ── */}
      {tab === 'alerts' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <StatsBar stats={stats} />

          {/* Filter bar */}
          <div style={{ display: 'flex', gap: 6 }}>
            {(['all','active','acknowledged','resolved'] as const).map(f => (
              <button key={f} onClick={() => { setFilter(f); }}
                style={{ padding: '5px 12px', borderRadius: 20, border: '1px solid', cursor: 'pointer', fontSize: 12, fontWeight: 500,
                  borderColor: filter === f ? ACCENT : '#1E293B',
                  background: filter === f ? `${ACCENT}18` : 'transparent',
                  color: filter === f ? ACCENT : '#475569', transition: 'all 150ms' }}>
                {f === 'all' ? '全部' : f === 'active' ? '进行中' : f === 'acknowledged' ? '已确认' : '已解决'}
              </button>
            ))}
          </div>

          {/* Alert list */}
          {loading ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: 40, color: '#64748B', fontSize: 13, justifyContent: 'center' }}>
              <Loader2 style={{ width: 14, height: 14, animation: 'spin 1s linear infinite' }} />加载中
            </div>
          ) : filteredAlerts.length === 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '60px 0', color: '#334155' }}>
              <CheckCircle style={{ width: 48, height: 48, marginBottom: 12, opacity: 0.3 }} />
              <div style={{ fontSize: 14, fontWeight: 600, color: '#475569' }}>暂无告警</div>
              <div style={{ fontSize: 12, color: '#334155', marginTop: 4 }}>所有指标正常，系统运行平稳</div>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {filteredAlerts.map(alert => (
                <AlertRow key={alert.id} alert={alert} onAck={handleAck} onResolve={handleResolve} />
              ))}
              {total > filteredAlerts.length && (
                <div style={{ textAlign: 'center', padding: '12px 0', fontSize: 12, color: '#475569' }}>
                  显示 {filteredAlerts.length} / {total} 条
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── 告警规则 ── */}
      {tab === 'rules' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ fontSize: 12, color: '#475569', marginBottom: 4 }}>点击开关启用/禁用规则，静默按钮可在 1 小时内忽略该规则</div>
          {rules.map(rule => (
            <RuleItem key={rule.id} rule={rule} onToggle={handleToggleRule} onSilence={handleSilence} />
          ))}
        </div>
      )}

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
      `}</style>
    </div>
  );
};

export default AlertPanel;
