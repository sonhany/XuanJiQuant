import React, { useState, useEffect, useCallback } from 'react';
import { BrainCircuit, Loader2, AlertTriangle, Play, List, Clock, ChevronRight, Zap, Trophy } from 'lucide-react';

const API_BASE = (import.meta as any).env?.VITE_API_BASE || '';
const API_TOKEN = (import.meta as any).env?.VITE_ALPHACOUNCIL_API_TOKEN || '';
const jsonHeaders = () => ({ 'Content-Type': 'application/json', ...(API_TOKEN ? { 'X-AlphaCouncil-Token': API_TOKEN } : {}) });
const ACCENT = '#34D399';

async function api(body: any) {
  const r = await fetch(`${API_BASE}/api/strategy`, { method: 'POST', headers: jsonHeaders(), body: JSON.stringify(body) });
  const d = await r.json();
  if (!d.success) throw new Error(d.error || '请求失败');
  return d.data;
}

interface StrategyMeta { [key: string]: { name: string; desc: string; params: { name: string; type: string; default: any; desc: string }[] }; }

const MetricCard = ({ label, value, color }: { label: string; value: string; color?: string }) => (
  <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, padding: '14px 16px' }}>
    <div style={{ fontSize: 10, color: '#475569', marginBottom: 6, letterSpacing: 0.5 }}>{label}</div>
    <div style={{ fontSize: 20, fontWeight: 700, fontFamily: 'JetBrains Mono, monospace', color: color || '#F1F5F9' }}>{value}</div>
  </div>
);

const StrategyPanel: React.FC = () => {
  const [tab, setTab] = useState<'scan'|'list'|'run'>('scan');
  const [meta, setMeta] = useState<StrategyMeta | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [selected, setSelected] = useState('factor_rank');
  const [codes, setCodes] = useState('000001,600036,601318,000858,600519');
  const [params, setParams] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<any>(null);
  // 全市场扫描结果
  const [scan, setScan] = useState<any>(null);
  const [scanLoading, setScanLoading] = useState(false);
  const [scanError, setScanError] = useState('');

  const loadScan = useCallback(async () => {
    setScanLoading(true); setScanError('');
    try { setScan(await api({ action: 'market_scan' })); }
    catch (e: any) { setScanError(e.message); }
    setScanLoading(false);
  }, []);

  useEffect(() => {
    api({ action: 'meta' }).then(setMeta).catch(() => {});
    loadScan();
  }, [loadScan]);

  useEffect(() => {
    if (meta && meta[selected]) {
      const defaults: Record<string, any> = {};
      meta[selected].params.forEach((p: any) => { defaults[p.name] = p.default; });
      setParams(defaults);
      setResult(null);
    }
  }, [selected, meta]);

  const handleRun = useCallback(async () => {
    setLoading(true); setError(''); setResult(null);
    try {
      const d = await api({ action: 'run', name: selected, params, codes: codes.split(',').map(s => s.trim()).filter(Boolean) });
      setResult(d);
    } catch (e: any) { setError(e.message); }
    setLoading(false);
  }, [selected, params, codes]);

  const summary = result?.backtest?.summary;
  const perStock = result?.backtest?.per_stock || {};
  const details = result?.backtest?.details || [];

  const tabs = [
    { key: 'scan', label: '市场扫描', icon: Trophy },
    { key: 'list', label: '策略列表', icon: List },
    { key: 'run',  label: '策略运行', icon: Play },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 22 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ width: 40, height: 40, borderRadius: 10, background: `${ACCENT}22`, border: `1px solid ${ACCENT}44`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <BrainCircuit style={{ width: 20, height: 20, color: ACCENT }} />
        </div>
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, color: '#F1F5F9' }}>策略引擎</div>
          <div style={{ fontSize: 11, color: '#64748B' }}>多因子策略 · 因子排名 · 回测分析</div>
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

      {/* ── 市场扫描 (全市场策略回测) ── */}
      {tab === 'scan' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {scanLoading && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: 30, color: '#64748B', fontSize: 13 }}>
              <Loader2 style={{ width: 14, height: 14, animation: 'spin 1s linear infinite' }} />加载全市场扫描结果...
            </div>
          )}
          {scanError && (
            <div style={{ padding: '12px 16px', background: '#FBBF2414', border: '1px solid #FBBF2433', borderRadius: 10, fontSize: 12, color: '#FBBF24', display: 'flex', alignItems: 'center', gap: 8 }}>
              <AlertTriangle style={{ width: 14, height: 14 }} /><span>{scanError}</span>
              <button onClick={loadScan} style={{ marginLeft: 'auto', padding: '4px 10px', background: '#FBBF2422', border: 'none', borderRadius: 6, color: '#FBBF24', fontSize: 11, cursor: 'pointer' }}>重试</button>
            </div>
          )}
          {scan && !scanLoading && (() => {
            const strategies: any[] = (scan.strategies || []).slice().sort((a, b) => b.sharpe - a.sharpe);
            const profit = strategies.filter(s => s.annual_return_pct > 0);
            const best = strategies[0];
            const renderRow = (s: any, idx: number) => {
              const retColor = s.annual_return_pct >= 0 ? '#4ADE80' : '#F87171';
              const sharpeColor = Math.abs(s.sharpe) > 1 ? '#4ADE80' : Math.abs(s.sharpe) > 0.5 ? '#FBBF24' : '#64748B';
              const ddColor = s.max_drawdown_pct < -30 ? '#F87171' : s.max_drawdown_pct < -15 ? '#FBBF24' : '#94A3B8';
              return (
                <div key={s.factor + idx} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0', borderBottom: '1px solid #1E293B44' }}>
                  <div style={{ width: 24, fontSize: 11, fontWeight: 700, color: idx < 3 ? ACCENT : '#475569', textAlign: 'center' }}>{idx + 1}</div>
                  <div style={{ width: 140, fontSize: 11, color: '#E2E8F0', fontFamily: 'JetBrains Mono, monospace' }}>{s.factor}</div>
                  <div style={{ width: 90, fontSize: 10, color: '#64748B' }}>{s.direction}</div>
                  <div style={{ width: 80, fontSize: 12, fontFamily: 'JetBrains Mono, monospace', color: retColor, textAlign: 'right', fontWeight: 600 }}>{s.annual_return_pct >= 0 ? '+' : ''}{s.annual_return_pct.toFixed(1)}%</div>
                  <div style={{ width: 64, fontSize: 12, fontFamily: 'JetBrains Mono, monospace', color: sharpeColor, textAlign: 'right' }}>{s.sharpe >= 0 ? '+' : ''}{s.sharpe.toFixed(2)}</div>
                  <div style={{ width: 70, fontSize: 11, fontFamily: 'JetBrains Mono, monospace', color: ddColor, textAlign: 'right' }}>{s.max_drawdown_pct.toFixed(1)}%</div>
                  <div style={{ width: 52, fontSize: 11, color: '#94A3B8', textAlign: 'right' }}>{s.win_rate_pct.toFixed(0)}%</div>
                </div>
              );
            };
            return (
              <>
                {/* 概览 */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
                  <MetricCard label="评估股票数" value={(scan.n_stocks || 0).toLocaleString()} color="#60A5FA" />
                  <MetricCard label="盈利策略" value={`${profit.length}/${strategies.length}`} color={profit.length > strategies.length/2 ? '#4ADE80' : '#F87171'} />
                  <MetricCard label="最佳夏普" value={best ? best.sharpe.toFixed(2) : '-'} color={best && best.sharpe > 0 ? '#4ADE80' : '#94A3B8'} />
                  <MetricCard label="扫描时间" value={(scan.scanned_at || '').slice(5, 16)} color="#94A3B8" />
                </div>
                {/* 风险提示 */}
                <div style={{ padding: '10px 14px', background: '#FBBF2410', border: '1px solid #FBBF2433', borderRadius: 8, fontSize: 11, color: '#FBBF24', display: 'flex', alignItems: 'center', gap: 8 }}>
                  <AlertTriangle style={{ width: 12, height: 12 }} />
                  回测含幸存者偏差/未计涨跌停，实盘收益通常打3-5折。夏普&gt;1且回撤可控的策略更可信。
                </div>
                {/* 表头 */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '4px 0', fontSize: 10, color: '#475569', letterSpacing: 0.5, borderBottom: '1px solid #1E293B' }}>
                  <div style={{ width: 24, textAlign: 'center' }}>#</div>
                  <div style={{ width: 140 }}>策略</div>
                  <div style={{ width: 90 }}>方向</div>
                  <div style={{ width: 80, textAlign: 'right' }}>年化</div>
                  <div style={{ width: 64, textAlign: 'right' }}>夏普</div>
                  <div style={{ width: 70, textAlign: 'right' }}>回撤</div>
                  <div style={{ width: 52, textAlign: 'right' }}>胜率</div>
                </div>
                {/* 盈利策略 (绿框) */}
                {profit.length > 0 && (
                  <div style={{ background: '#111827', border: '1px solid #4ADE8033', borderRadius: 12, padding: '8px 16px' }}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: '#4ADE80', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 6 }}>
                      <Trophy style={{ width: 12, height: 12 }} /> 盈利策略 ({profit.length}) · 按夏普排序
                    </div>
                    {profit.map(renderRow)}
                  </div>
                )}
                {/* 亏损策略 (灰框) */}
                {strategies.length > profit.length && (
                  <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, padding: '8px 16px' }}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: '#64748B', marginBottom: 6 }}>亏损策略 ({strategies.length - profit.length})</div>
                    {strategies.filter(s => s.annual_return_pct <= 0).map((s, i) => renderRow(s, profit.length + i))}
                  </div>
                )}
              </>
            );
          })()}
        </div>
      )}

      {/* ── 策略列表 ── */}
      {tab === 'list' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {meta ? Object.entries(meta).map(([id, s]) => (
            <div key={id} style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, overflow: 'hidden' }}>
              <button
                onClick={() => setExpanded(p => ({ ...p, [id]: !p[id] }))}
                style={{ width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 16px', background: 'transparent', border: 'none', cursor: 'pointer', textAlign: 'left' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <ChevronRight style={{ width: 14, height: 14, color: '#475569', transform: expanded[id] ? 'rotate(90deg)' : 'none', transition: 'transform 150ms' }} />
                  <span style={{ fontSize: 14, fontWeight: 600, color: '#E2E8F0' }}>{s.name}</span>
                  <span style={{ fontSize: 10, fontFamily: 'JetBrains Mono, monospace', color: '#334155', background: '#1E293B', padding: '2px 8px', borderRadius: 4 }}>{id}</span>
                </div>
              </button>
              {expanded[id] && (
                <div style={{ padding: '0 16px 16px 40px', borderTop: '1px solid #1E293B' }}>
                  <p style={{ fontSize: 12, color: '#64748B', margin: '12px 0 10px' }}>{s.desc}</p>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                    {s.params.map((p: any) => (
                      <div key={p.name} style={{ display: 'flex', gap: 10, alignItems: 'flex-start', fontSize: 11 }}>
                        <span style={{ fontFamily: 'JetBrains Mono, monospace', color: ACCENT, background: `${ACCENT}18`, padding: '2px 8px', borderRadius: 4, whiteSpace: 'nowrap', minWidth: 90 }}>{p.name}</span>
                        <span style={{ color: '#475569' }}>{String(p.default)}</span>
                        <span style={{ color: '#334155' }}>— {p.desc}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: 30, color: '#64748B', fontSize: 13 }}>
              <Loader2 style={{ width: 14, height: 14, animation: 'spin 1s linear infinite' }} />加载中
            </div>
          )}
        </div>
      )}

      {/* ── 策略运行 ── */}
      {tab === 'run' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Config */}
          <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, padding: 16, display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <div>
              <div style={{ fontSize: 10, color: '#475569', marginBottom: 5 }}>策略</div>
              <select value={selected} onChange={e => setSelected(e.target.value)}
                style={{ padding: '8px 12px', background: '#0B0F1A', border: '1px solid #1E293B', borderRadius: 8, color: '#E2E8F0', fontSize: 13, outline: 'none', cursor: 'pointer' }}>
                {meta && Object.entries(meta).map(([id, s]) => <option key={id} value={id}>{s.name}</option>)}
              </select>
            </div>
            <div style={{ flex: 1, minWidth: 200 }}>
              <div style={{ fontSize: 10, color: '#475569', marginBottom: 5 }}>股票列表</div>
              <input value={codes} onChange={e => setCodes(e.target.value)}
                style={{ padding: '8px 12px', background: '#0B0F1A', border: '1px solid #1E293B', borderRadius: 8, color: '#E2E8F0', fontSize: 12, width: '100%', outline: 'none', fontFamily: 'JetBrains Mono, monospace' }}
                onFocus={e => (e.target.style.borderColor = ACCENT)} onBlur={e => (e.target.style.borderColor = '#1E293B')} />
            </div>
            <button onClick={handleRun} disabled={loading}
              style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 18px', background: ACCENT, border: 'none', borderRadius: 8, color: '#0B0F1A', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>
              {loading ? <Loader2 style={{ width: 13, height: 13, animation: 'spin 1s linear infinite' }} /> : <Zap style={{ width: 13, height: 13 }} />}
              运行策略
            </button>
          </div>

          {/* Dynamic params */}
          {meta && meta[selected] && meta[selected].params.length > 0 && (
            <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, padding: 14, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              {meta[selected].params.map((p: any) => (
                <div key={p.name}>
                  <div style={{ fontSize: 10, color: '#475569', marginBottom: 4 }}>{p.name}</div>
                  <input value={params[p.name] ?? ''} onChange={e => setParams(prev => ({ ...prev, [p.name]: e.target.value }))}
                    placeholder={String(p.default)}
                    style={{ padding: '6px 10px', background: '#0B0F1A', border: '1px solid #1E293B', borderRadius: 6, color: '#E2E8F0', fontSize: 12, width: 100, outline: 'none', fontFamily: 'JetBrains Mono, monospace' }}
                    onFocus={e => (e.target.style.borderColor = ACCENT)} onBlur={e => (e.target.style.borderColor = '#1E293B')} />
                </div>
              ))}
            </div>
          )}

          {error && <div style={{ padding: '10px 14px', background: '#EF444414', border: '1px solid #EF444433', borderRadius: 8, fontSize: 12, color: '#F87171' }}>
            <AlertTriangle style={{ width: 12, height: 12, display: 'inline', marginRight: 6 }} />{error}
          </div>}

          {/* Results */}
          {result && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {result.elapsed && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Clock style={{ width: 12, height: 12, color: '#475569' }} />
                  <span style={{ fontSize: 11, color: '#475569' }}>耗时 {(result.elapsed).toFixed(1)}s</span>
                </div>
              )}
              {summary && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
                  <MetricCard label="总收益率" value={`${(summary.total_return_pct ?? 0) >= 0 ? '+' : ''}${(summary.total_return_pct ?? 0).toFixed(2)}%`}
                    color={(summary.total_return_pct ?? 0) >= 0 ? '#4ADE80' : '#F87171'} />
                  <MetricCard label="平均收益" value={`${(summary.avg_return_pct ?? 0).toFixed(2)}%`}
                    color={(summary.avg_return_pct ?? 0) >= 0 ? '#4ADE80' : '#F87171'} />
                  <MetricCard label="胜率" value={`${(summary.win_rate_pct ?? 0).toFixed(1)}%`} color="#60A5FA" />
                  <MetricCard label="交易次数" value={String(summary.total_trades ?? 0)} color="#94A3B8" />
                </div>
              )}

              {/* Per-stock */}
              {Object.keys(perStock).length > 0 && (
                <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, overflow: 'hidden' }}>
                  <div style={{ padding: '10px 16px', background: '#0B0F1A', borderBottom: '1px solid #1E293B', fontSize: 12, fontWeight: 600, color: '#94A3B8' }}>个股表现</div>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                    <thead><tr style={{ borderBottom: '1px solid #1E293B' }}>
                      {['代码','交易次数','总收益','胜率','均笔收益'].map((h,i) => <th key={h} style={{ padding: '9px 14px', textAlign: i>=1?'right':'left', fontSize: 10, fontWeight: 600, color: '#475569' }}>{h}</th>)}
                    </tr></thead>
                    <tbody>
                      {Object.entries(perStock).map(([code, ps]: [string, any]) => (
                        <tr key={code} style={{ borderBottom: '1px solid #1E293B44' }}>
                          <td style={{ padding: '9px 14px', fontFamily: 'JetBrains Mono, monospace', color: ACCENT, fontSize: 12 }}>{code}</td>
                          <td style={{ padding: '9px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: '#94A3B8', fontSize: 11 }}>{ps.trade_count}</td>
                          <td style={{ padding: '9px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: ps.total_return_pct >= 0 ? '#4ADE80' : '#F87171', fontWeight: 600, fontSize: 11 }}>
                            {ps.total_return_pct >= 0 ? '+' : ''}{ps.total_return_pct.toFixed(2)}%
                          </td>
                          <td style={{ padding: '9px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: '#94A3B8', fontSize: 11 }}>{(ps.win_rate_pct).toFixed(1)}%</td>
                          <td style={{ padding: '9px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: '#94A3B8', fontSize: 11 }}>{(ps.avg_win_pct || 0) >= 0 ? '+' : ''}{(ps.avg_win_pct || 0).toFixed(2)}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Recent trades */}
              {details.length > 0 && (
                <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, overflow: 'hidden' }}>
                  <div style={{ padding: '10px 16px', background: '#0B0F1A', borderBottom: '1px solid #1E293B', fontSize: 12, fontWeight: 600, color: '#94A3B8' }}>
                    最近交易 (共 {details.length} 笔)
                  </div>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                    <thead><tr style={{ borderBottom: '1px solid #1E293B' }}>
                      {['入场日期','代码','入场价','出场价','天数','收益率'].map((h,i) => <th key={h} style={{ padding: '9px 14px', textAlign: i>=2?'right':'left', fontSize: 10, fontWeight: 600, color: '#475569' }}>{h}</th>)}
                    </tr></thead>
                    <tbody>
                      {details.slice(0, 40).map((t: any, i: number) => (
                        <tr key={i} style={{ borderBottom: '1px solid #1E293B44' }}>
                          <td style={{ padding: '8px 14px', color: '#475569', fontSize: 11, fontFamily: 'JetBrains Mono, monospace' }}>{String(t.entry_date || '').slice(0, 10)}</td>
                          <td style={{ padding: '8px 14px', fontFamily: 'JetBrains Mono, monospace', color: ACCENT, fontSize: 11 }}>{t.code}</td>
                          <td style={{ padding: '8px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: '#94A3B8', fontSize: 11 }}>{Number(t.entry_price||0).toFixed(2)}</td>
                          <td style={{ padding: '8px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: '#94A3B8', fontSize: 11 }}>{Number(t.exit_price||0).toFixed(2)}</td>
                          <td style={{ padding: '8px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: '#475569', fontSize: 11 }}>{t.holding_days}</td>
                          <td style={{ padding: '8px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: (t.pnl_pct||0) >= 0 ? '#4ADE80' : '#F87171', fontWeight: 600, fontSize: 11 }}>
                            {(t.pnl_pct||0) >= 0 ? '+' : ''}{(t.pnl_pct||0).toFixed(2)}%
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {!result && !loading && (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '60px 0', color: '#334155' }}>
              <BrainCircuit style={{ width: 48, height: 48, marginBottom: 12, opacity: 0.3 }} />
              <div style={{ fontSize: 14, fontWeight: 600, color: '#475569' }}>配置策略参数后运行回测</div>
              <div style={{ fontSize: 12, color: '#334155', marginTop: 4 }}>回测耗时约 30-90 秒</div>
            </div>
          )}

          {loading && (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '60px 0', color: '#475569' }}>
              <Loader2 style={{ width: 36, height: 36, color: ACCENT, animation: 'spin 1s linear infinite', marginBottom: 12 }} />
              <div style={{ fontSize: 14, color: '#64748B' }}>策略回测运行中...</div>
            </div>
          )}
        </div>
      )}

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
};

export default StrategyPanel;
