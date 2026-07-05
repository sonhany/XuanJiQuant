import React, { useState, useEffect, useCallback } from 'react';
import { Zap, RefreshCw, TrendingUp, TrendingDown, Wallet, Clock, AlertTriangle, Loader2 } from 'lucide-react';

const API_BASE = (import.meta as any).env?.VITE_API_BASE || '';
const API_TOKEN = (import.meta as any).env?.VITE_ALPHACOUNCIL_API_TOKEN || '';
const jsonHeaders = () => ({ 'Content-Type': 'application/json', ...(API_TOKEN ? { 'X-AlphaCouncil-Token': API_TOKEN } : {}) });
const ACCENT = '#FB923C';

async function api(body: any) {
  const r = await fetch(`${API_BASE}/api/execution`, { method: 'POST', headers: jsonHeaders(), body: JSON.stringify(body) });
  const d = await r.json();
  if (!d.success) throw new Error(d.error || '请求失败');
  return d.data;
}

const MetricCard = ({ label, value, color }: { label: string; value: string; color?: string }) => (
  <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, padding: '14px 16px' }}>
    <div style={{ fontSize: 10, color: '#475569', marginBottom: 6, letterSpacing: 0.5 }}>{label}</div>
    <div style={{ fontSize: 20, fontWeight: 700, fontFamily: 'JetBrains Mono, monospace', color: color || '#F1F5F9' }}>{value}</div>
  </div>
);

const ExecutionPanel: React.FC = () => {
  const [tab, setTab] = useState<'overview'|'orders'>('overview');
  const [status, setStatus] = useState<any>(null);
  const [positions, setPositions] = useState<any[]>([]);
  const [orders, setOrders] = useState<any[]>([]);
  const [code, setCode] = useState('600519');
  const [qty, setQty] = useState('100');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    try {
      const d = await api({ action: 'all' });
      setStatus(d.status); setPositions(d.positions || []); setOrders(d.orders || []);
    } catch (e: any) { setError(e.message); }
  }, []);

  useEffect(() => { refresh(); }, []);

  const placeOrder = useCallback(async (direction: 'buy' | 'sell') => {
    setLoading(true); setError('');
    try {
      const r = await api({ action: 'place_order', code: code.trim(), direction, quantity: parseInt(qty) || 100 });
      if (r && r.error) { setError(r.error); setLoading(false); return; }
      // 市价单已自动成交 (后端 _auto_fill_market_order)，无需前端再 fill。
      // 仅当订单未成交 (限价单) 时才手动取价并 fill。
      const oid = r && r.id ? r.id : null;
      const ord = r && r.order ? r.order : null;
      const alreadyFilled = (ord && ord.status === 'filled') || !oid;
      if (oid && !alreadyFilled) {
        try {
          const raw = await fetch(`${API_BASE}/api/data?action=klines&code=${code}&limit=1`).then(r => r.json());
          const price = raw?.data?.klines?.[0]?.close || 0;
          if (price) await api({ action: 'fill_order', order_id: oid, fill_price: parseFloat(price) });
        } catch (_) {}
      }
      await refresh();
    } catch (e: any) { setError(e.message); }
    setLoading(false);
  }, [code, qty, refresh]);

  const tabs = [
    { key: 'overview', label: '总览', icon: Wallet },
    { key: 'orders',   label: '订单历史', icon: Clock },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 22 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ width: 40, height: 40, borderRadius: 10, background: `${ACCENT}22`, border: `1px solid ${ACCENT}44`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Zap style={{ width: 20, height: 20, color: ACCENT }} />
          </div>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, color: '#F1F5F9' }}>交易执行</div>
            <div style={{ fontSize: 11, color: '#64748B' }}>手工模拟下单 · 与模拟盘共享账户 · AI 闭环不会从这里触发</div>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, background: '#111827', border: '1px solid #1E293B', borderRadius: 20, padding: '4px 12px' }}>
            <div style={{ width: 6, height: 6, borderRadius: '50%', background: '#4ADE80', boxShadow: '0 0 6px #4ADE80' }} />
            <span style={{ fontSize: 11, color: '#64748B' }}>模拟交易</span>
          </div>
          <button onClick={refresh}
            style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '7px 12px', background: '#111827', border: '1px solid #1E293B', borderRadius: 8, color: '#64748B', fontSize: 12, cursor: 'pointer' }}>
            <RefreshCw style={{ width: 12, height: 12 }} />刷新
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 4, background: '#111827', padding: 4, borderRadius: 10, border: '1px solid #1E293B', width: 'fit-content' }}>
        {tabs.map(t => {
          const Icon = t.icon;
          const is = tab === t.key;
          return (
            <button key={t.key} onClick={() => setTab(t.key as typeof tab)}
              style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 16px', borderRadius: 7, border: 'none', cursor: 'pointer', fontSize: 13, fontWeight: is ? 600 : 400,
                background: is ? `${ACCENT}18` : 'transparent', color: is ? ACCENT : '#64748B', transition: 'all 150ms' }}>
              <Icon style={{ width: 14, height: 14 }} />{t.label}
            </button>
          );
        })}
      </div>

      {error && <div style={{ padding: '10px 14px', background: '#EF444414', border: '1px solid #EF444433', borderRadius: 8, fontSize: 12, color: '#F87171' }}>
        <AlertTriangle style={{ width: 12, height: 12, display: 'inline', marginRight: 6 }} />{error}
      </div>}

      {/* Metrics */}
      {status && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
          <MetricCard label="总权益" value={`¥${(status.total_equity||0).toLocaleString()}`} color="#F1F5F9" />
          <MetricCard label="可用现金" value={`¥${(status.cash||0).toLocaleString()}`} color="#4ADE80" />
          <MetricCard label="持仓市值" value={`¥${(status.market_value||0).toLocaleString()}`} color="#60A5FA" />
          <MetricCard label="总盈亏" value={`${(status.total_pnl_pct||0)>=0?'+':''}${(status.total_pnl_pct||0).toFixed(2)}%`}
            color={(status.total_pnl||0)>=0?'#4ADE80':'#F87171'} />
        </div>
      )}

      {/* Trade input */}
      <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, padding: 16 }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: '#475569', marginBottom: 12 }}>快速下单</div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontSize: 10, color: '#475569', marginBottom: 5 }}>股票代码</div>
            <input value={code} onChange={e => setCode(e.target.value)}
              style={{ padding: '8px 12px', background: '#0B0F1A', border: '1px solid #1E293B', borderRadius: 8, color: '#E2E8F0', fontSize: 13, fontFamily: 'JetBrains Mono, monospace', width: 120, outline: 'none' }}
              onFocus={e => (e.target.style.borderColor = ACCENT)} onBlur={e => (e.target.style.borderColor = '#1E293B')} />
          </div>
          <div>
            <div style={{ fontSize: 10, color: '#475569', marginBottom: 5 }}>数量 (股)</div>
            <input value={qty} onChange={e => setQty(e.target.value)}
              style={{ padding: '8px 12px', background: '#0B0F1A', border: '1px solid #1E293B', borderRadius: 8, color: '#E2E8F0', fontSize: 13, fontFamily: 'JetBrains Mono, monospace', width: 100, outline: 'none' }}
              onFocus={e => (e.target.style.borderColor = ACCENT)} onBlur={e => (e.target.style.borderColor = '#1E293B')} />
          </div>
          <button onClick={() => placeOrder('buy')} disabled={loading}
            style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 20px', background: '#16A34A', border: 'none', borderRadius: 8, color: 'white', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>
            {loading ? <Loader2 style={{ width: 13, height: 13, animation: 'spin 1s linear infinite' }} /> : <TrendingUp style={{ width: 14, height: 14 }} />}买入
          </button>
          <button onClick={() => placeOrder('sell')} disabled={loading}
            style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 20px', background: '#DC2626', border: 'none', borderRadius: 8, color: 'white', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>
            {loading ? <Loader2 style={{ width: 13, height: 13, animation: 'spin 1s linear infinite' }} /> : <TrendingDown style={{ width: 14, height: 14 }} />}卖出
          </button>
        </div>
      </div>

      {/* Positions */}
      <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, overflow: 'hidden' }}>
        <div style={{ padding: '12px 16px', background: '#0B0F1A', borderBottom: '1px solid #1E293B', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Wallet style={{ width: 14, height: 14, color: '#475569' }} />
            <span style={{ fontSize: 12, fontWeight: 600, color: '#94A3B8' }}>当前持仓</span>
          </div>
          <span style={{ fontSize: 10, color: '#334155', background: '#1E293B', padding: '2px 8px', borderRadius: 10 }}>{positions.length} 只</span>
        </div>
        {positions.length === 0 ? (
          <div style={{ padding: '40px 0', display: 'flex', flexDirection: 'column', alignItems: 'center', color: '#334155' }}>
            <Wallet style={{ width: 36, height: 36, marginBottom: 8, opacity: 0.4 }} />
            <div style={{ fontSize: 13, color: '#475569' }}>暂无持仓</div>
          </div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead><tr style={{ borderBottom: '1px solid #1E293B' }}>
              {['代码','数量','成本价','现价','市值','盈亏'].map((h,i) => <th key={h} style={{ padding: '10px 14px', textAlign: i>=1?'right':'left', fontSize: 10, fontWeight: 600, color: '#475569' }}>{h}</th>)}
            </tr></thead>
            <tbody>
              {positions.map(p => (
                <tr key={p.code} style={{ borderBottom: '1px solid #1E293B44' }}>
                  <td style={{ padding: '10px 14px', fontFamily: 'JetBrains Mono, monospace', color: '#60A5FA', fontWeight: 600 }}>{p.code}</td>
                  <td style={{ padding: '10px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: '#94A3B8' }}>{p.quantity}</td>
                  <td style={{ padding: '10px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: '#64748B' }}>{Number(p.avg_price||0).toFixed(2)}</td>
                  <td style={{ padding: '10px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: '#64748B' }}>{Number(p.current_price||0).toFixed(2)}</td>
                  <td style={{ padding: '10px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: '#94A3B8' }}>¥{(p.market_value||0).toLocaleString()}</td>
                  <td style={{ padding: '10px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: (p.pnl||0)>=0?'#4ADE80':'#F87171', fontWeight: 600 }}>
                    {(p.pnl_pct||0)>=0?'+':''}{(p.pnl_pct||0).toFixed(2)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Orders tab */}
      {tab === 'orders' && (
        <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, overflow: 'hidden' }}>
          <div style={{ padding: '12px 16px', background: '#0B0F1A', borderBottom: '1px solid #1E293B', display: 'flex', alignItems: 'center', gap: 8 }}>
            <Clock style={{ width: 14, height: 14, color: '#475569' }} />
            <span style={{ fontSize: 12, fontWeight: 600, color: '#94A3B8' }}>订单历史</span>
            <span style={{ fontSize: 10, color: '#334155', background: '#1E293B', padding: '2px 8px', borderRadius: 10 }}>{orders.length} 笔</span>
          </div>
          {orders.length === 0 ? (
            <div style={{ padding: '40px 0', display: 'flex', flexDirection: 'column', alignItems: 'center', color: '#334155' }}>
              <Clock style={{ width: 36, height: 36, marginBottom: 8, opacity: 0.4 }} />
              <div style={{ fontSize: 13, color: '#475569' }}>暂无订单</div>
            </div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead><tr style={{ borderBottom: '1px solid #1E293B' }}>
                {['代码','方向','数量','价格','状态','时间'].map((h,i) => <th key={h} style={{ padding: '10px 14px', textAlign: i>=2?'right':'left', fontSize: 10, fontWeight: 600, color: '#475569' }}>{h}</th>)}
              </tr></thead>
              <tbody>
                {orders.map(o => (
                  <tr key={o.id} style={{ borderBottom: '1px solid #1E293B44' }}>
                    <td style={{ padding: '10px 14px', fontFamily: 'JetBrains Mono, monospace', color: '#94A3B8' }}>{o.code}</td>
                    <td style={{ padding: '10px 14px', fontWeight: 600, color: o.direction==='buy'?'#4ADE80':'#F87171' }}>{o.direction==='buy'?'买入':'卖出'}</td>
                    <td style={{ padding: '10px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: '#94A3B8' }}>{o.quantity}</td>
                    <td style={{ padding: '10px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: '#94A3B8' }}>{Number(o.price||0).toFixed(2)}</td>
                    <td style={{ padding: '10px 14px' }}>
                      <span style={{ padding: '2px 8px', borderRadius: 10, fontSize: 10, background: o.status==='filled'?'#4ADE8022':o.status==='pending'?'#FBBF2422':'#64748B22',
                        color: o.status==='filled'?'#4ADE80':o.status==='pending'?'#FBBF24':'#64748B', border: `1px solid ${o.status==='filled'?'#4ADE8033':o.status==='pending'?'#FBBF2433':'#64748B33'}` }}>
                        {o.status==='filled'?'已成交':o.status==='pending'?'挂单中':'已撤销'}
                      </span>
                    </td>
                    <td style={{ padding: '10px 14px', color: '#334155', fontSize: 11 }}>{o.created_at ? String(o.created_at).slice(0,19) : '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
};

export default ExecutionPanel;
