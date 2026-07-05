import React, { useState, useEffect, useCallback } from 'react';
import { BrainCircuit, Loader2, AlertTriangle, BarChart3, LineChart, Grid3X3, Trophy, RefreshCw } from 'lucide-react';

const API_BASE = (import.meta as any).env?.VITE_API_BASE || '';
const API_TOKEN = (import.meta as any).env?.VITE_ALPHACOUNCIL_API_TOKEN || '';
const jsonHeaders = () => ({ 'Content-Type': 'application/json', ...(API_TOKEN ? { 'X-AlphaCouncil-Token': API_TOKEN } : {}) });
const ACCENT = '#818CF8';

async function api(body: any) {
  const r = await fetch(`${API_BASE}/api/factor`, { method: 'POST', headers: jsonHeaders(), body: JSON.stringify(body) });
  const d = await r.json();
  if (!d.success) throw new Error(d.error || '请求失败');
  return d.data;
}

interface Factor { name: string; label: string; desc: string; category: string; }
interface ICResult { mean: number; std: number; ir: number; positive_ratio: number; }

const irColor = (ir: number) => Math.abs(ir) > 0.5 ? '#4ADE80' : Math.abs(ir) > 0.3 ? '#FBBF24' : '#64748B';

const MetricCard = ({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) => (
  <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, padding: '14px 16px' }}>
    <div style={{ fontSize: 10, color: '#475569', marginBottom: 6, letterSpacing: 0.5 }}>{label}</div>
    <div style={{ fontSize: 22, fontWeight: 700, fontFamily: 'JetBrains Mono, monospace', color: color || '#F1F5F9' }}>{value}</div>
    {sub && <div style={{ fontSize: 10, color: '#334155', marginTop: 4 }}>{sub}</div>}
  </div>
);

const ICBar: React.FC<{ name: string; mean: number }> = ({ name, mean }) => {
  const pct = Math.min(Math.abs(mean) * 400, 100);
  const color = mean > 0 ? '#4ADE80' : '#F87171';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <div style={{ width: 72, fontSize: 11, color: '#94A3B8', fontFamily: 'JetBrains Mono, monospace', textAlign: 'right' }}>{name}</div>
      <div style={{ flex: 1, height: 20, background: '#0B0F1A', borderRadius: 4, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: `${color}33`, borderRight: `2px solid ${color}`, borderRadius: 4, transition: 'width 600ms ease' }} />
      </div>
      <div style={{ width: 72, fontSize: 11, fontFamily: 'JetBrains Mono, monospace', color }}>{mean >= 0 ? '+' : ''}{(mean * 100).toFixed(2)}%</div>
    </div>
  );
};

const FactorPanel: React.FC = () => {
  const [tab, setTab] = useState<'list'|'eval'|'batch'|'market'>('market');
  const [factors, setFactors] = useState<Factor[]>([]);
  const [metaLoading, setMetaLoading] = useState(true);
  const [codes, setCodes] = useState('000001,600036,601318,000858,600519');
  const [fname, setFname] = useState('ret_1');
  const [evalResult, setEvalResult] = useState<any>(null);
  const [evalLoading, setEvalLoading] = useState(false);
  const [evalError, setEvalError] = useState('');
  const [batchCodes, setBatchCodes] = useState('000001,600036,601318,000858,600519');
  const [batchResult, setBatchResult] = useState<any>(null);
  const [batchLoading, setBatchLoading] = useState(false);
  const [batchError, setBatchError] = useState('');
  // 全市场有效因子榜单
  const [marketEval, setMarketEval] = useState<any>(null);
  const [marketLoading, setMarketLoading] = useState(false);
  const [marketError, setMarketError] = useState('');
  // 因子多空选股明细
  const [selectedFactor, setSelectedFactor] = useState<string | null>(null);
  const [factorStocks, setFactorStocks] = useState<any>(null);
  const [fsLoading, setFsLoading] = useState(false);

  const tabs = [
    { key: 'market', label: '市场榜单', icon: Trophy },
    { key: 'list',  label: '因子列表', icon: Grid3X3 },
    { key: 'eval',  label: 'IC评估',   icon: LineChart },
    { key: 'batch', label: '批量IC',   icon: BarChart3 },
  ];

  const loadFactorStocks = useCallback(async (fname: string) => {
    if (selectedFactor === fname && factorStocks) {
      setSelectedFactor(null); setFactorStocks(null); return;  // 再次点击收起
    }
    setSelectedFactor(fname); setFsLoading(true); setFactorStocks(null);
    try {
      const d = await api({ action: 'factor_stocks', factor_name: fname, top_n: 15, bottom_n: 15 });
      setFactorStocks(d);
    } catch (e: any) { setFactorStocks({ error: e.message }); }
    setFsLoading(false);
  }, [selectedFactor, factorStocks]);

  const loadMarketEval = useCallback(async () => {
    setMarketLoading(true); setMarketError('');
    try {
      const d = await api({ action: 'market_eval' });
      setMarketEval(d);
    } catch (e: any) { setMarketError(e.message); }
    setMarketLoading(false);
  }, []);

  useEffect(() => { loadMarketEval(); }, [loadMarketEval]);

  useEffect(() => {
    api({ action: 'meta' }).then(d => {
      const list: Factor[] = [];
      Object.entries(d as Record<string, any>).forEach(([name, info]: [string, any]) => {
        list.push({ name, label: info.label || name, desc: info.desc || '', category: info.category || 'other' });
      });
      setFactors(list);
    }).catch(() => {}).finally(() => setMetaLoading(false));
  }, []);

  const runEval = useCallback(async () => {
    setEvalLoading(true); setEvalError('');
    try {
      const d = await api({ action: 'evaluate', codes: codes.split(',').map(s => s.trim()).filter(Boolean), factor_name: fname });
      setEvalResult(d);
    } catch (e: any) { setEvalError(e.message); }
    setEvalLoading(false);
  }, [codes, fname]);

  const runBatch = useCallback(async () => {
    setBatchLoading(true); setBatchError('');
    try {
      const d = await api({ action: 'evaluate_all', codes: batchCodes.split(',').map(s => s.trim()).filter(Boolean) });
      setBatchResult(d);
    } catch (e: any) { setBatchError(e.message); }
    setBatchLoading(false);
  }, [batchCodes]);

  const grouped: Record<string, Factor[]> = {};
  factors.forEach(f => { if (!grouped[f.category]) grouped[f.category] = []; grouped[f.category].push(f); });

  const sortedBatch = batchResult
    ? Object.entries(batchResult).sort(([,a], [,b]) => Math.abs((b as any).fwd_1?.mean || 0) - Math.abs((a as any).fwd_1?.mean || 0))
    : [];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 22 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ width: 40, height: 40, borderRadius: 10, background: `${ACCENT}22`, border: `1px solid ${ACCENT}44`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <BrainCircuit style={{ width: 20, height: 20, color: ACCENT }} />
        </div>
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, color: '#F1F5F9' }}>因子引擎</div>
          <div style={{ fontSize: 11, color: '#64748B' }}>47量化因子 · IC评估 · 多周期衰减分析</div>
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

      {/* ── 市场榜单 (全市场有效因子) ── */}
      {tab === 'market' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {marketLoading && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: 30, color: '#64748B', fontSize: 13 }}>
              <Loader2 style={{ width: 14, height: 14, animation: 'spin 1s linear infinite' }} />加载全市场评估结果...
            </div>
          )}
          {marketError && (
            <div style={{ padding: '12px 16px', background: '#FBBF2414', border: '1px solid #FBBF2433', borderRadius: 10, fontSize: 12, color: '#FBBF24', display: 'flex', alignItems: 'center', gap: 8 }}>
              <AlertTriangle style={{ width: 14, height: 14 }} />
              <span>{marketError}</span>
              <button onClick={loadMarketEval} style={{ marginLeft: 'auto', padding: '4px 10px', background: '#FBBF2422', border: 'none', borderRadius: 6, color: '#FBBF24', fontSize: 11, cursor: 'pointer' }}>重试</button>
            </div>
          )}
          {marketEval && !marketLoading && (() => {
            const allFactors: any[] = (marketEval.factors || []).slice().sort((a, b) => b.abs_ic_1d - a.abs_ic_1d);
            const strong = allFactors.filter(f => f.abs_ic_1d >= 0.03);
            const moderate = allFactors.filter(f => f.abs_ic_1d >= 0.02 && f.abs_ic_1d < 0.03);
            const weak = allFactors.filter(f => f.abs_ic_1d < 0.02);
            const renderRow = (f: any) => {
              const pct = Math.min(f.abs_ic_1d * 600, 100);
              const color = f.ic_1d > 0 ? '#4ADE80' : '#F87171';
              const isSelected = selectedFactor === f.factor;
              return (
                <div key={f.factor}>
                <button onClick={() => loadFactorStocks(f.factor)} title="点击查看多空选股明细"
                  style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '5px 0', width: '100%', border: 'none', background: isSelected ? `${ACCENT}10` : 'transparent', cursor: 'pointer', borderRadius: 4, transition: 'background 150ms' }}>
                  <div style={{ width: 120, fontSize: 11, color: ACCENT, fontFamily: 'JetBrains Mono, monospace', textAlign: 'right' }}>{f.factor}</div>
                  <div style={{ flex: 1, height: 22, background: '#0B0F1A', borderRadius: 4, overflow: 'hidden', position: 'relative' }}>
                    <div style={{ width: `${pct}%`, height: '100%', background: `${color}33`, borderRight: `2px solid ${color}`, borderRadius: 4, transition: 'width 600ms ease' }} />
                  </div>
                  <div style={{ width: 64, fontSize: 11, fontFamily: 'JetBrains Mono, monospace', color, textAlign: 'right' }}>{f.ic_1d >= 0 ? '+' : ''}{(f.ic_1d * 100).toFixed(2)}%</div>
                  <div style={{ width: 56, fontSize: 11, fontFamily: 'JetBrains Mono, monospace', color: irColor(f.ir_1d), textAlign: 'right' }}>{f.ir_1d >= 0 ? '+' : ''}{f.ir_1d.toFixed(3)}</div>
                  <div style={{ width: 50, fontSize: 10, color: '#475569', textAlign: 'right' }}>{(f.positive_1d * 100).toFixed(0)}%</div>
                  <div style={{ width: 16, fontSize: 9, color: isSelected ? ACCENT : '#334155', textAlign: 'center' }}>{isSelected ? '▼' : '▶'}</div>
                </button>
                {/* 多空选股明细 (选中时展开) */}
                {isSelected && (
                  <div style={{ margin: '6px 0 10px 130px', padding: '12px 16px', background: '#0B0F1A', border: `1px solid ${ACCENT}33`, borderRadius: 8 }}>
                    {fsLoading && <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#64748B', fontSize: 12 }}><Loader2 style={{ width: 12, height: 12, animation: 'spin 1s linear infinite' }} />计算 {f.factor} 全市场截面选股...</div>}
                    {factorStocks?.error && <div style={{ fontSize: 11, color: '#F87171' }}>{factorStocks.error}</div>}
                    {factorStocks && !fsLoading && !factorStocks.error && (() => {
                      const top: any[] = factorStocks.top || [];
                      const bottom: any[] = factorStocks.bottom || [];
                      const renderStock = (s: any, idx: number, isLong: boolean) => (
                        <div key={s.code} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '3px 0' }}>
                          <div style={{ width: 18, fontSize: 9, color: '#475569' }}>{idx+1}</div>
                          <div style={{ width: 56, fontSize: 11, color: '#E2E8F0', fontFamily: 'JetBrains Mono, monospace' }}>{s.code}</div>
                          <div style={{ flex: 1, fontSize: 11, color: '#94A3B8' }}>{s.name}</div>
                          <div style={{ width: 70, fontSize: 11, fontFamily: 'JetBrains Mono, monospace', color: isLong ? '#4ADE80' : '#F87171', textAlign: 'right' }}>{s.factor_value}</div>
                          <div style={{ width: 56, fontSize: 10, color: '#64748B', textAlign: 'right' }}>{s.close}</div>
                          <div style={{ width: 52, fontSize: 10, fontFamily: 'JetBrains Mono, monospace', color: s.change_pct >= 0 ? '#4ADE80' : '#F87171', textAlign: 'right' }}>{s.change_pct >= 0 ? '+' : ''}{s.change_pct}%</div>
                        </div>
                      );
                      return (
                        <>
                          <div style={{ fontSize: 10, color: '#475569', marginBottom: 6 }}>全市场 {factorStocks.n_stocks} 只 · 按最新截面 {f.factor} 值排序</div>
                          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                            <div>
                              <div style={{ fontSize: 10, fontWeight: 600, color: '#4ADE80', marginBottom: 4 }}>▲ 多头 (值最大 Top15)</div>
                              {top.map((s, i) => renderStock(s, i, true))}
                            </div>
                            <div>
                              <div style={{ fontSize: 10, fontWeight: 600, color: '#F87171', marginBottom: 4 }}>▼ 空头 (值最小 Bottom15)</div>
                              {bottom.map((s, i) => renderStock(s, i, false))}
                            </div>
                          </div>
                        </>
                      );
                    })()}
                  </div>
                )}
                </div>
              );
            };
            return (
              <>
                {/* 概览卡片 */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
                  <MetricCard label="评估股票数" value={marketEval.n_stocks?.toLocaleString() || '-'} sub="全A股" color="#60A5FA" />
                  <MetricCard label="强有效因子" value={`${strong.length}`} sub="|IC|≥0.03" color="#4ADE80" />
                  <MetricCard label="中等有效" value={`${moderate.length}`} sub="0.02≤|IC|<0.03" color="#FBBF24" />
                  <MetricCard label="评估时间" value={(marketEval.evaluated_at || '').slice(5, 16)} sub="MM-DD HH:MM" color="#94A3B8" />
                </div>
                {/* 列头 */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '4px 0', fontSize: 10, color: '#475569', letterSpacing: 0.5 }}>
                  <div style={{ width: 120, textAlign: 'right' }}>因子</div>
                  <div style={{ flex: 1, textAlign: 'center' }}>IC 强度</div>
                  <div style={{ width: 64, textAlign: 'right' }}>IC_1d</div>
                  <div style={{ width: 56, textAlign: 'right' }}>IR_1d</div>
                  <div style={{ width: 50, textAlign: 'right' }}>胜率</div>
                </div>
                {/* 强有效 */}
                {strong.length > 0 && (
                  <div style={{ background: '#111827', border: '1px solid #4ADE8033', borderRadius: 12, padding: '12px 16px' }}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: '#4ADE80', marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
                      <Trophy style={{ width: 12, height: 12 }} /> 强有效因子 ({strong.length}) · |IC| ≥ 0.03
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>{strong.map(renderRow)}</div>
                  </div>
                )}
                {/* 中等有效 */}
                {moderate.length > 0 && (
                  <div style={{ background: '#111827', border: '1px solid #FBBF2433', borderRadius: 12, padding: '12px 16px' }}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: '#FBBF24', marginBottom: 10 }}>中等有效因子 ({moderate.length}) · 0.02 ≤ |IC| &lt; 0.03</div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>{moderate.map(renderRow)}</div>
                  </div>
                )}
                {/* 弱/无效 (折叠显示前5) */}
                {weak.length > 0 && (
                  <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, padding: '12px 16px' }}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: '#64748B', marginBottom: 10 }}>弱/无效因子 ({weak.length}) · |IC| &lt; 0.02 {weak.length > 5 && <span style={{ color: '#334155' }}>· 仅显示前5</span>}</div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>{weak.slice(0, 5).map(renderRow)}</div>
                  </div>
                )}
              </>
            );
          })()}
        </div>
      )}

      {/* ── Factor List ── */}
      {tab === 'list' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {metaLoading ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: 30, color: '#64748B', fontSize: 13 }}>
              <Loader2 style={{ width: 14, height: 14, animation: 'spin 1s linear infinite' }} />加载中
            </div>
          ) : Object.entries(grouped).map(([cat, fs]) => (
            <div key={cat} style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, overflow: 'hidden' }}>
              <div style={{ padding: '10px 16px', background: '#0B0F1A', borderBottom: '1px solid #1E293B', fontSize: 11, fontWeight: 600, color: ACCENT, letterSpacing: 0.5 }}>
                {cat.toUpperCase()} ({fs.length})
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, padding: 12 }}>
                {fs.map(f => (
                  <div key={f.name} style={{ padding: '5px 10px', background: '#1E293B', borderRadius: 6, fontSize: 11, color: '#94A3B8', display: 'flex', flexDirection: 'column', gap: 2, maxWidth: 150 }}>
                    <span style={{ fontFamily: 'JetBrains Mono, monospace', color: ACCENT, fontSize: 10 }}>{f.name}</span>
                    <span style={{ color: '#475569', fontSize: 10 }}>{f.label}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── IC 评估 ── */}
      {tab === 'eval' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, padding: 16, display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <div>
              <div style={{ fontSize: 10, color: '#475569', marginBottom: 5 }}>因子名称</div>
              <input value={fname} onChange={e => setFname(e.target.value)}
                style={{ padding: '8px 12px', background: '#0B0F1A', border: '1px solid #1E293B', borderRadius: 8, color: '#E2E8F0', fontSize: 13, fontFamily: 'JetBrains Mono, monospace', width: 140, outline: 'none' }}
                onFocus={e => (e.target.style.borderColor = ACCENT)} onBlur={e => (e.target.style.borderColor = '#1E293B')} />
            </div>
            <div style={{ flex: 1, minWidth: 200 }}>
              <div style={{ fontSize: 10, color: '#475569', marginBottom: 5 }}>股票列表</div>
              <input value={codes} onChange={e => setCodes(e.target.value)}
                style={{ padding: '8px 12px', background: '#0B0F1A', border: '1px solid #1E293B', borderRadius: 8, color: '#E2E8F0', fontSize: 12, width: '100%', outline: 'none' }}
                onFocus={e => (e.target.style.borderColor = ACCENT)} onBlur={e => (e.target.style.borderColor = '#1E293B')} />
            </div>
            <button onClick={runEval} disabled={evalLoading}
              style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 18px', background: ACCENT, border: 'none', borderRadius: 8, color: '#0B0F1A', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>
              {evalLoading ? <Loader2 style={{ width: 13, height: 13, animation: 'spin 1s linear infinite' }} /> : <BarChart3 style={{ width: 13, height: 13 }} />}
              运行评估
            </button>
          </div>

          {evalError && <div style={{ padding: '10px 14px', background: '#EF444414', border: '1px solid #EF444433', borderRadius: 8, fontSize: 12, color: '#F87171' }}>
            <AlertTriangle style={{ width: 12, height: 12, display: 'inline', marginRight: 6 }} />{evalError}
          </div>}

          {evalResult && (
            <>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
                <MetricCard label="IC 均值" value={`${evalResult.summary.mean >= 0 ? '+' : ''}${(evalResult.summary.mean * 100).toFixed(2)}%`}
                  color={evalResult.summary.mean > 0 ? '#4ADE80' : '#F87171'} sub="Mean IC" />
                <MetricCard label="IC 标准差" value={evalResult.summary.std.toFixed(4)} color="#94A3B8" sub="Std" />
                <MetricCard label="IR" value={evalResult.summary.ir.toFixed(3)} color={irColor(evalResult.summary.ir)} sub="Information Ratio" />
                <MetricCard label="IC > 0 占比" value={`${(evalResult.summary.positive_ratio * 100).toFixed(1)}%`}
                  color={evalResult.summary.positive_ratio > 0.5 ? '#4ADE80' : '#F87171'} sub="Positive Ratio" />
              </div>
              <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, padding: 16 }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: '#94A3B8', marginBottom: 14 }}>IC 周期衰减</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {Object.entries(evalResult.decay || {})
                    .sort(([a], [b]) => parseInt(a.replace('fwd_','')) - parseInt(b.replace('fwd_','')))
                    .map(([k, v]: [string, ICResult]) => <ICBar key={k} name={k} mean={v.mean} />)
                  }
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {/* ── Batch IC ── */}
      {tab === 'batch' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, padding: 16, display: 'flex', gap: 12, alignItems: 'flex-end' }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 10, color: '#475569', marginBottom: 5 }}>股票列表 (逗号分隔)</div>
              <input value={batchCodes} onChange={e => setBatchCodes(e.target.value)}
                style={{ padding: '8px 12px', background: '#0B0F1A', border: '1px solid #1E293B', borderRadius: 8, color: '#E2E8F0', fontSize: 12, width: '100%', outline: 'none' }}
                onFocus={e => (e.target.style.borderColor = ACCENT)} onBlur={e => (e.target.style.borderColor = '#1E293B')} />
            </div>
            <button onClick={runBatch} disabled={batchLoading}
              style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 18px', background: ACCENT, border: 'none', borderRadius: 8, color: '#0B0F1A', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>
              {batchLoading ? <Loader2 style={{ width: 13, height: 13, animation: 'spin 1s linear infinite' }} /> : <BarChart3 style={{ width: 13, height: 13 }} />}
              批量评估全部47因子
            </button>
          </div>

          {batchError && <div style={{ padding: '10px 14px', background: '#EF444414', border: '1px solid #EF444433', borderRadius: 8, fontSize: 12, color: '#F87171' }}>
            <AlertTriangle style={{ width: 12, height: 12, display: 'inline', marginRight: 6 }} />{batchError}
          </div>}

          {batchResult && (
            <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, overflow: 'hidden' }}>
              <div style={{ padding: '10px 16px', background: '#0B0F1A', borderBottom: '1px solid #1E293B', fontSize: 12, fontWeight: 600, color: '#94A3B8' }}>
                47因子 IC 排行 — fwd_1
              </div>
              <div style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
                {sortedBatch.map(([fname, fdata]: [string, any]) => {
                  const mean = fdata?.fwd_1?.mean || 0;
                  const ir = fdata?.fwd_1?.ir || 0;
                  const pct = Math.min(Math.abs(mean) * 400, 100);
                  const color = mean > 0 ? '#4ADE80' : '#F87171';
                  return (
                    <div key={fname} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <div style={{ width: 100, fontSize: 11, color: ACCENT, fontFamily: 'JetBrains Mono, monospace', textAlign: 'right' }}>{fname}</div>
                      <div style={{ flex: 1, height: 22, background: '#0B0F1A', borderRadius: 4, overflow: 'hidden' }}>
                        <div style={{ width: `${pct}%`, height: '100%', background: `${color}33`, borderRight: `2px solid ${color}`, borderRadius: 4 }} />
                      </div>
                      <div style={{ width: 60, fontSize: 11, fontFamily: 'JetBrains Mono, monospace', color }}>{mean >= 0 ? '+' : ''}{(mean * 100).toFixed(2)}%</div>
                      <div style={{ width: 60, fontSize: 11, fontFamily: 'JetBrains Mono, monospace', color: irColor(ir) }}>{ir.toFixed(3)}</div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
};

export default FactorPanel;
