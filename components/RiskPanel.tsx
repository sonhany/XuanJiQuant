import React, { useState, useEffect, useCallback } from 'react';
import { Shield, RefreshCw, Server, Database, BrainCircuit, Zap, CheckCircle, XCircle, AlertCircle, FileSearch } from 'lucide-react';

const API_BASE = (import.meta as any).env?.VITE_API_BASE || '';
const API_TOKEN = (import.meta as any).env?.VITE_ALPHACOUNCIL_API_TOKEN || '';
const jsonHeaders = () => ({ 'Content-Type': 'application/json', ...(API_TOKEN ? { 'X-AlphaCouncil-Token': API_TOKEN } : {}) });
const ACCENT = '#F472B6';

async function api(body: any) {
  const r = await fetch(`${API_BASE}/api/risk`, { method: 'POST', headers: jsonHeaders(), body: JSON.stringify(body) });
  const d = await r.json();
  if (!d.success) throw new Error(d.error || '请求失败');
  return d.data;
}

const MetricCard = ({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) => (
  <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, padding: '14px 16px' }}>
    <div style={{ fontSize: 10, color: '#475569', marginBottom: 6, letterSpacing: 0.5 }}>{label}</div>
    <div style={{ fontSize: 20, fontWeight: 700, fontFamily: 'JetBrains Mono, monospace', color: color || '#F1F5F9' }}>{value}</div>
    {sub && <div style={{ fontSize: 10, color: '#334155', marginTop: 4 }}>{sub}</div>}
  </div>
);

const StatusBadge = ({ status }: { status: string }) => {
  const cfg: Record<string, { color: string; bg: string; label: string }> = {
    ok: { color: '#4ADE80', bg: '#4ADE8022', label: '正常' },
    warning: { color: '#FBBF24', bg: '#FBBF2422', label: '警告' },
    error: { color: '#F87171', bg: '#F8717122', label: '异常' },
  };
  const c = cfg[status] || cfg.warning;
  return (
    <span style={{ padding: '2px 8px', borderRadius: 10, fontSize: 10, background: c.bg, color: c.color, fontWeight: 600, border: `1px solid ${c.color}44` }}>
      {c.label}
    </span>
  );
};

const layerIcons: Record<string, any> = {
  data_layer: Database, factor_layer: BrainCircuit, strategy_layer: Zap,
  execution_layer: Server, system: Server,
};
const layerLabels: Record<string, string> = {
  data_layer: '数据层', factor_layer: '因子层', strategy_layer: '策略层',
  execution_layer: '执行层', system: '系统',
};

const RiskPanel: React.FC = () => {
  const [risk, setRisk] = useState<any>(null);
  const [health, setHealth] = useState<any>(null);
  const [replays, setReplays] = useState<any[]>([]);
  const [replay, setReplay] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [r, h, a] = await Promise.all([
        api({ action: 'portfolio_risk' }),
        api({ action: 'system_health' }),
        api({ action: 'audit_replays', limit: 12 }),
      ]);
      setRisk(r); setHealth(h); setReplays(a || []);
    } catch (e: any) { setError(e.message); }
    setLoading(false);
  }, []);

  useEffect(() => { refresh(); }, []);

  const loadReplay = async (row: any) => {
    setLoading(true); setError('');
    try {
      const data = await api({ action: 'audit_replay', run_id: row?.run_id, decision_id: row?.decision_id, limit: 80 });
      setReplay(data);
    } catch (e: any) { setError(e.message); }
    setLoading(false);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 22 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ width: 40, height: 40, borderRadius: 10, background: `${ACCENT}22`, border: `1px solid ${ACCENT}44`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Shield style={{ width: 20, height: 20, color: ACCENT }} />
          </div>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, color: '#F1F5F9' }}>风控监控</div>
            <div style={{ fontSize: 11, color: '#64748B' }}>系统健康 · 组合风险 · 实时监控</div>
          </div>
        </div>
        <button onClick={refresh} disabled={loading}
          style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '7px 14px', background: '#111827', border: '1px solid #1E293B', borderRadius: 8, color: '#64748B', fontSize: 12, cursor: 'pointer' }}>
          <RefreshCw style={{ width: 12, height: 12, animation: loading ? 'spin 1s linear infinite' : 'none' }} />刷新
        </button>
      </div>

      {error && <div style={{ padding: '10px 14px', background: '#EF444414', border: '1px solid #EF444433', borderRadius: 8, fontSize: 12, color: '#F87171' }}>
        <AlertCircle style={{ width: 12, height: 12, display: 'inline', marginRight: 6 }} />{error}
      </div>}

      {/* System Health */}
      {health && (
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
            <Server style={{ width: 14, height: 14, color: '#475569' }} />
            <span style={{ fontSize: 13, fontWeight: 600, color: '#94A3B8' }}>系统健康</span>
            <StatusBadge status={health.overall || 'ok'} />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12 }}>
            {Object.entries(health).filter(([k]) => k !== 'overall').map(([layer, info]: [string, any]) => {
              const Icon = layerIcons[layer] || Server;
              return (
                <div key={layer} style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, padding: 14 }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <Icon style={{ width: 14, height: 14, color: ACCENT }} />
                      <span style={{ fontSize: 12, fontWeight: 600, color: '#E2E8F0' }}>{layerLabels[layer] || layer}</span>
                    </div>
                    <StatusBadge status={info.status || 'ok'} />
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    {Object.entries(info).filter(([k]) => !['status'].includes(k)).map(([k, v]) => (
                      <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
                        <span style={{ color: '#475569' }}>{k.replace(/_/g, ' ')}</span>
                        <span style={{ fontFamily: 'JetBrains Mono, monospace', color: '#94A3B8' }}>{String(v)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Portfolio Risk */}
      {risk && (
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
            <Shield style={{ width: 14, height: 14, color: '#475569' }} />
            <span style={{ fontSize: 13, fontWeight: 600, color: '#94A3B8' }}>组合风险</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 12 }}>
            <MetricCard label="VaR 95%" value={`${(risk.var_95||0).toFixed(2)}%`}
              color={(risk.var_95||0) < 0 ? '#F87171' : '#4ADE80'} sub="日 VaR" />
            <MetricCard label="年化波动" value={`${(risk.volatility_pct||0).toFixed(2)}%`}
              color="#FBBF24" sub="年化波动率" />
            <MetricCard label="集中度" value={`${(risk.concentration_pct||0).toFixed(1)}%`}
              color={(risk.concentration_pct||0) > 50 ? '#F87171' : '#94A3B8'} sub="最大持仓占比" />
            <MetricCard label="总暴露" value={`${(risk.gross_exposure_pct||0).toFixed(1)}%`}
              color={(risk.gross_exposure_pct||0) > 100 ? '#F87171' : '#94A3B8'} sub="多头/权益" />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
            <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, padding: 16, textAlign: 'center' }}>
              <div style={{ fontSize: 10, color: '#475569', marginBottom: 6 }}>持仓数量</div>
              <div style={{ fontSize: 28, fontWeight: 800, fontFamily: 'JetBrains Mono, monospace', color: '#F1F5F9' }}>{risk.position_count || 0}</div>
              <div style={{ fontSize: 10, color: '#334155', marginTop: 4 }}>只股票</div>
            </div>
            <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, padding: 16, textAlign: 'center' }}>
              <div style={{ fontSize: 10, color: '#475569', marginBottom: 6 }}>总权益</div>
              <div style={{ fontSize: 22, fontWeight: 800, fontFamily: 'JetBrains Mono, monospace', color: '#F1F5F9' }}>¥{(risk.total_equity||0).toLocaleString()}</div>
              <div style={{ fontSize: 10, color: '#334155', marginTop: 4 }}>实时权益</div>
            </div>
            <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, padding: 16, textAlign: 'center' }}>
              <div style={{ fontSize: 10, color: '#475569', marginBottom: 6 }}>净暴露</div>
              <div style={{ fontSize: 28, fontWeight: 800, fontFamily: 'JetBrains Mono, monospace', color: (risk.net_exposure_pct||0) >= 0 ? '#4ADE80' : '#F87171' }}>
                {(risk.net_exposure_pct||0) >= 0 ? '+' : ''}{(risk.net_exposure_pct||0).toFixed(1)}%
              </div>
              <div style={{ fontSize: 10, color: '#334155', marginTop: 4 }}>多头-空头</div>
            </div>
          </div>
        </div>
      )}

      {/* Audit Replay */}
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
          <FileSearch style={{ width: 14, height: 14, color: '#475569' }} />
          <span style={{ fontSize: 13, fontWeight: 600, color: '#94A3B8' }}>AI 决策回放</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(260px, 360px) 1fr', gap: 12 }}>
          <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 8, padding: 12, minHeight: 180 }}>
            <div style={{ fontSize: 11, color: '#64748B', marginBottom: 10 }}>最近运行</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {(replays || []).slice(0, 10).map((r: any, idx: number) => (
                <button key={`${r.run_id || idx}-${r.created_at}`} onClick={() => loadReplay(r)}
                  style={{ textAlign: 'left', background: replay?.run_id === r.run_id ? '#172554' : '#0B1220', border: '1px solid #1E293B', borderRadius: 6, padding: 8, color: '#CBD5E1', cursor: 'pointer' }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: '#E2E8F0', overflowWrap: 'anywhere' }}>{r.run_id || r.decision_id || 'latest'}</div>
                  <div style={{ fontSize: 10, color: '#64748B', marginTop: 3 }}>{r.event_type} · {r.created_at}</div>
                </button>
              ))}
              {(!replays || replays.length === 0) && <div style={{ fontSize: 12, color: '#475569' }}>暂无可回放记录</div>}
            </div>
          </div>
          <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 8, padding: 12, minHeight: 180 }}>
            {!replay ? (
              <div style={{ fontSize: 12, color: '#475569' }}>选择左侧运行记录查看当时决策、风控原因、订单与成交。</div>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(120px, 1fr))', gap: 10 }}>
                {[
                  ['决策', replay.decisions?.length || 0],
                  ['风控事件', replay.risk_events?.length || 0],
                  ['订单', replay.orders?.length || 0],
                  ['成交', replay.trades?.length || 0],
                ].map(([label, value]: any) => (
                  <div key={label} style={{ border: '1px solid #1E293B', borderRadius: 6, padding: 10 }}>
                    <div style={{ fontSize: 10, color: '#64748B' }}>{label}</div>
                    <div style={{ fontSize: 20, color: '#F8FAFC', fontWeight: 800 }}>{value}</div>
                  </div>
                ))}
                <div style={{ gridColumn: '1 / -1', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                  <div>
                    <div style={{ fontSize: 11, color: '#94A3B8', marginBottom: 6 }}>风控拒单解释</div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 220, overflow: 'auto' }}>
                      {(replay.risk_events || []).map((e: any, idx: number) => (
                        <div key={idx} style={{ border: '1px solid #1E293B', borderRadius: 6, padding: 8, fontSize: 11 }}>
                          <div style={{ color: e.approved ? '#4ADE80' : '#F87171', fontWeight: 700 }}>{e.code || '--'} {e.direction || ''} · {e.reason || '--'}</div>
                          <div style={{ color: '#64748B', marginTop: 3, overflowWrap: 'anywhere' }}>{(e.payload?.reasons || []).join(', ') || e.created_at}</div>
                        </div>
                      ))}
                      {(!replay.risk_events || replay.risk_events.length === 0) && <div style={{ fontSize: 12, color: '#475569' }}>本次无风控事件</div>}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: '#94A3B8', marginBottom: 6 }}>订单与成交</div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 220, overflow: 'auto' }}>
                      {[...(replay.orders || []), ...(replay.trades || [])].slice(0, 40).map((e: any, idx: number) => (
                        <div key={idx} style={{ border: '1px solid #1E293B', borderRadius: 6, padding: 8, fontSize: 11 }}>
                          <div style={{ color: '#E2E8F0', fontWeight: 700 }}>{e.order_id || e.trade_id || e.id || '--'} · {e.code || '--'} {e.direction || ''}</div>
                          <div style={{ color: '#64748B', marginTop: 3 }}>{e.status || 'trade'} · {e.created_at}</div>
                        </div>
                      ))}
                      {(!replay.orders?.length && !replay.trades?.length) && <div style={{ fontSize: 12, color: '#475569' }}>本次无订单或成交</div>}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {!health && !risk && !error && (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '60px 0', color: '#334155' }}>
          <Shield style={{ width: 48, height: 48, marginBottom: 12, opacity: 0.3 }} />
          <div style={{ fontSize: 14, fontWeight: 600, color: '#475569' }}>点击刷新获取监控数据</div>
        </div>
      )}

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
};

export default RiskPanel;
