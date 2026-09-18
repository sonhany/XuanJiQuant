import React, { useState, useEffect, useCallback } from 'react';
import { BrainCircuit, Loader2, AlertTriangle, BarChart3, LineChart, Grid3X3, Trophy, RefreshCw } from 'lucide-react';
import { ResearchBoundary } from './ResearchBoundary';

const API_BASE = (import.meta as any).env?.VITE_API_BASE || '';
const API_TOKEN = (import.meta as any).env?.VITE_XUANJI_API_TOKEN || '';
const jsonHeaders = () => ({ 'Content-Type': 'application/json', ...(API_TOKEN ? { 'X-XuanJi-Token': API_TOKEN } : {}) });
const ACCENT = '#818CF8';

async function api(body: any) {
  const r = await fetch(`${API_BASE}/api/factor`, { method: 'POST', headers: jsonHeaders(), body: JSON.stringify(body) });
  const d = await r.json();
  if (!d.success) throw new Error(d.error || '请求失败');
  return d.data;
}

interface Factor { name: string; label: string; chinese_name: string; desc: string; category: string; }
interface ICResult { mean: number; std: number; ir: number; positive_ratio: number; n_periods?: number; }
interface SegmentMetrics {
  summary?: ICResult | null;
  decay?: Record<string, ICResult>;
  date_range?: [string | null, string | null];
  n_dates?: number;
  n_stocks?: number;
}

const irColor = (ir: number) => Math.abs(ir) > 0.5 ? '#4ADE80' : Math.abs(ir) > 0.3 ? '#FBBF24' : '#64748B';
const fmtPct = (value?: number | null) => typeof value === 'number' && Number.isFinite(value) ? `${value >= 0 ? '+' : ''}${(value * 100).toFixed(2)}%` : '--';
const fmtNum = (value?: number | null, digits = 3) => typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '--';
const displayCompactDate = (value: unknown) => {
  const compact = String(value || '').replace(/-/g, '').slice(0, 8);
  return /^\d{8}$/.test(compact) ? `${compact.slice(0, 4)}-${compact.slice(4, 6)}-${compact.slice(6, 8)}` : '--';
};

const MetricCard = ({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) => (
  <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, padding: '14px 16px' }}>
    <div style={{ fontSize: 12, color: '#475569', marginBottom: 6, letterSpacing: 0.5 }}>{label}</div>
    <div style={{ fontSize: 22, fontWeight: 700, fontFamily: 'JetBrains Mono, monospace', color: color || '#F1F5F9' }}>{value}</div>
    {sub && <div style={{ fontSize: 12, color: '#334155', marginTop: 4 }}>{sub}</div>}
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

const SegmentStabilityTable: React.FC<{ data: any }> = ({ data }) => {
  const segments: Record<string, SegmentMetrics> = data?.segments || {};
  const rows = [
    ['训练集', segments.train],
    ['验证集', segments.valid],
    ['测试集', segments.test],
    ['全样本', segments.all],
  ] as const;
  return (
    <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, padding: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 12, fontWeight: 700, color: '#E2E8F0' }}>Qlib 分段稳定性</div>
          <div style={{ fontSize: 12, color: '#64748B', marginTop: 3 }}>训练集 / 验证集 / 测试集分段 IC，用于观察因子是否只在全样本里偶然有效</div>
        </div>
        <div style={{ fontSize: 12, color: '#475569', fontFamily: 'JetBrains Mono, monospace' }}>{data?.factor_name || '--'}</div>
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 760 }}>
          <thead>
            <tr style={{ color: '#64748B', fontSize: 12, textAlign: 'right', borderBottom: '1px solid #1E293B' }}>
              <th style={{ textAlign: 'left', padding: '8px 6px' }}>数据分段</th>
              <th style={{ textAlign: 'left', padding: '8px 6px' }}>日期范围</th>
              <th style={{ padding: '8px 6px' }}>IC 均值</th>
              <th style={{ padding: '8px 6px' }}>IR</th>
              <th style={{ padding: '8px 6px' }}>正值占比</th>
              <th style={{ padding: '8px 6px' }}>1D IC</th>
              <th style={{ padding: '8px 6px' }}>5D IC</th>
              <th style={{ padding: '8px 6px' }}>样本期数</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([label, seg]) => {
              const summary = seg?.summary || null;
              const d1 = seg?.decay?.['1d'];
              const d5 = seg?.decay?.['5d'];
              const mean = summary?.mean ?? null;
              const ir = summary?.ir ?? null;
              return (
                <tr key={label} style={{ borderBottom: '1px solid #1E293B66', color: '#CBD5E1', fontSize: 11 }}>
                  <td style={{ padding: '9px 6px', color: label === '全样本' ? ACCENT : '#E2E8F0', fontWeight: 700, textAlign: 'left' }}>{label}</td>
                  <td style={{ padding: '9px 6px', color: '#64748B', fontFamily: 'JetBrains Mono, monospace', textAlign: 'left' }}>
                    {seg?.date_range?.[0] || '--'} - {seg?.date_range?.[1] || '--'}
                  </td>
                  <td style={{ padding: '9px 6px', color: typeof mean === 'number' && mean >= 0 ? '#4ADE80' : '#F87171', fontFamily: 'JetBrains Mono, monospace', textAlign: 'right' }}>{fmtPct(mean)}</td>
                  <td style={{ padding: '9px 6px', color: irColor(ir || 0), fontFamily: 'JetBrains Mono, monospace', textAlign: 'right' }}>{fmtNum(ir)}</td>
                  <td style={{ padding: '9px 6px', fontFamily: 'JetBrains Mono, monospace', textAlign: 'right' }}>{fmtPct(summary?.positive_ratio)}</td>
                  <td style={{ padding: '9px 6px', fontFamily: 'JetBrains Mono, monospace', textAlign: 'right' }}>{fmtPct(d1?.mean)}</td>
                  <td style={{ padding: '9px 6px', fontFamily: 'JetBrains Mono, monospace', textAlign: 'right' }}>{fmtPct(d5?.mean)}</td>
                  <td style={{ padding: '9px 6px', color: '#94A3B8', fontFamily: 'JetBrains Mono, monospace', textAlign: 'right' }}>{summary?.n_periods ?? seg?.n_dates ?? 0}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
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
  const [segmentResult, setSegmentResult] = useState<any>(null);
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
        list.push({
          name,
          label: info.label || info.chinese_name || name,
          chinese_name: info.chinese_name || info.label || name,
          desc: info.desc || '',
          category: info.category || 'other'
        });
      });
      setFactors(list);
    }).catch(() => {}).finally(() => setMetaLoading(false));
  }, []);

  // 英文因子名 -> 中文名映射 (供市场榜单显示)
  const factorZhMap = React.useMemo(() => {
    const m: Record<string, string> = {};
    factors.forEach(f => { m[f.name] = f.chinese_name || f.label || f.name; });
    return m;
  }, [factors]);
  const factorZh = (key: string): string => factorZhMap[key] || key;

  const runEval = useCallback(async () => {
    setEvalLoading(true); setEvalError('');
    setSegmentResult(null);
    try {
      const codeList = codes.split(',').map(s => s.trim()).filter(Boolean);
      const [d, segments] = await Promise.all([
        api({ action: 'evaluate', codes: codeList, factor_name: fname }),
        api({ action: 'evaluate_segments', codes: codeList, factor_name: fname, fwd_horizons: [1, 5, 10, 20] }),
      ]);
      setEvalResult(d);
      setSegmentResult(segments);
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
      <ResearchBoundary source="本地行情库与因子引擎" asOf={marketEval?.generated_at || marketEval?.data_latest_date} error={marketError} />
      {marketEval?.research_refresh?.state === 'refreshing' && marketEval?.is_current === false && (
        <div style={{ padding: '10px 12px', background: '#0C4A6E33', border: '1px solid #38BDF844', borderRadius: 8, color: '#7DD3FC', fontSize: 12 }}>
          正在更新目标日期 {displayCompactDate(marketEval.research_refresh.target_date)}，当前展示上一完整版本；完成指针切换前不会混用新旧因子产物。
        </div>
      )}
      {marketEval?.is_current === false && marketEval?.research_refresh?.state !== 'refreshing' && (
        <div style={{ padding: '10px 12px', background: '#451A0322', border: '1px solid #F59E0B55', borderRadius: 8, color: '#FBBF24', fontSize: 12 }}>
          因子评估已过期：当前结果截至 {displayCompactDate(marketEval.data_end_date || marketEval.data_latest_date)}，等待下一次确定性研究流水线完成；现有排名仅供历史参考。
        </div>
      )}
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ width: 40, height: 40, borderRadius: 10, background: `${ACCENT}22`, border: `1px solid ${ACCENT}44`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <BrainCircuit style={{ width: 20, height: 20, color: ACCENT }} />
        </div>
        <div>
          <div style={{ fontSize: 'var(--font-page-title)', fontWeight: 700, color: '#F1F5F9' }}>因子引擎</div>
          <div style={{ fontSize: 11, color: '#64748B' }}>{factors.length || '--'} 个已登记因子 · IC评估 · 多周期衰减分析</div>
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8 }}>
        {[
          ['评估区间', marketEval?.data_start_date && marketEval?.data_end_date
            ? `${marketEval.data_start_date} 至 ${marketEval.data_end_date}`
            : (marketEval?.date_range
              ? `${marketEval.date_range[0]} 至 ${marketEval.date_range[1]}`
              : (marketEval?.data_latest_date || '--'))],
          ['股票池定义', marketEval?.universe || `全市场 ${marketEval?.n_stocks || '--'} 只`],
          ['中性化', marketEval?.neutralization || '未提供'],
          ['交易成本', marketEval?.cost_bps == null ? '未计入' : `${marketEval.cost_bps} bps`],
          ['换手率', marketEval?.turnover_pct == null ? '未提供' : `${marketEval.turnover_pct}%`],
          ['缺失率', marketEval?.missing_pct == null ? '未提供' : `${marketEval.missing_pct}%`],
          ['当前可评估股票', marketEval?.eligible_count == null ? '--' : `${marketEval.eligible_count} 只`],
          ['绑定数据版本', marketEval?.data_version ? String(marketEval.data_version).slice(0, 12) : '--'],
          ['股票池规则', marketEval?.universe_policy === 'current_tradeable_v1' ? '当前可交易股票池 v1' : (marketEval?.universe_policy || '--')],
          ['产物权限', marketEval?.promotion_state === 'research_only' ? '仅限研究，不具备交易权限' : (marketEval?.promotion_state || '--')],
          ['相关性', '组合前检查因子冗余'],
        ].map(([label, value]) => <div key={String(label)} style={{ padding: 9, border: '1px solid #1E293B', borderRadius: 6, background: '#111827' }}><div style={{ color: '#526076', fontSize: 11 }}>{label}</div><div style={{ marginTop: 5, color: '#CBD5E1', fontSize: 12 }}>{value}</div></div>)}
      </div>

      {/* 基本面因子 PIT 风险警告 */}
      <div style={{ padding: '8px 12px', background: '#451A03', border: '1px solid #F59E0B', borderRadius: 8, fontSize: 11, color: '#FDE68A', display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontWeight: 700 }}>⚠ 基本面因子风险提示：</span>
        <span>基本面因子（ROE/ROA/增速等）含未来函数(PIT)风险，因财务报告披露时点未做严格滞后处理，IC 评估结果可能偏乐观。<b style={{ color: '#FCA5A5' }}>实盘使用前必须叠加财报发布日滞后</b>，否则会高估因子收益。技术/量价因子不受此影响。</span>
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
                <button onClick={() => loadFactorStocks(f.factor)} title={`${factorZh(f.factor)} · 点击查看多空选股明细`}
                  style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '5px 0', width: '100%', border: 'none', background: isSelected ? `${ACCENT}10` : 'transparent', cursor: 'pointer', borderRadius: 4, transition: 'background 150ms' }}>
                  <div style={{ width: 160, display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 0 }}>
                    <div style={{ fontSize: 11, color: '#CBD5E1', textAlign: 'right', lineHeight: 1.2 }}>{factorZh(f.factor)}</div>
                    <div style={{ fontSize: 11, color: '#64748B', fontFamily: 'JetBrains Mono, monospace', textAlign: 'right', lineHeight: 1.1 }}>{f.factor}</div>
                  </div>
                  <div style={{ flex: 1, height: 22, background: '#0B0F1A', borderRadius: 4, overflow: 'hidden', position: 'relative' }}>
                    <div style={{ width: `${pct}%`, height: '100%', background: `${color}33`, borderRight: `2px solid ${color}`, borderRadius: 4, transition: 'width 600ms ease' }} />
                  </div>
                  <div style={{ width: 64, fontSize: 11, fontFamily: 'JetBrains Mono, monospace', color, textAlign: 'right' }}>{f.ic_1d >= 0 ? '+' : ''}{(f.ic_1d * 100).toFixed(2)}%</div>
                  <div style={{ width: 56, fontSize: 11, fontFamily: 'JetBrains Mono, monospace', color: irColor(f.ir_1d), textAlign: 'right' }}>{f.ir_1d >= 0 ? '+' : ''}{f.ir_1d.toFixed(3)}</div>
                  <div style={{ width: 50, fontSize: 12, color: '#475569', textAlign: 'right' }}>{(f.positive_1d * 100).toFixed(0)}%</div>
                  <div style={{ width: 16, fontSize: 11, color: isSelected ? ACCENT : '#334155', textAlign: 'center' }}>{isSelected ? '▼' : '▶'}</div>
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
                          <div style={{ width: 18, fontSize: 11, color: '#475569' }}>{idx+1}</div>
                          <div style={{ width: 56, fontSize: 11, color: '#E2E8F0', fontFamily: 'JetBrains Mono, monospace' }}>{s.code}</div>
                          <div style={{ flex: 1, fontSize: 11, color: '#94A3B8' }}>{s.name || s.code}</div>
                          <div style={{ width: 70, fontSize: 11, fontFamily: 'JetBrains Mono, monospace', color: isLong ? '#4ADE80' : '#F87171', textAlign: 'right' }}>{s.factor_value}</div>
                          <div style={{ width: 56, fontSize: 12, color: '#64748B', textAlign: 'right' }}>{s.close}</div>
                          <div style={{ width: 52, fontSize: 12, fontFamily: 'JetBrains Mono, monospace', color: s.change_pct >= 0 ? '#4ADE80' : '#F87171', textAlign: 'right' }}>{s.change_pct >= 0 ? '+' : ''}{s.change_pct}%</div>
                        </div>
                      );
                      return (
                        <>
                          <div style={{ fontSize: 12, color: '#475569', marginBottom: 8, lineHeight: 1.7 }}>
                            <div>全市场 {factorStocks.n_stocks} 只 · 按最新截面 {f.factor} 值排序</div>
                            <div>
                              排序依据: {factorStocks.sort_basis === 'latest_cross_section_factor_value' ? '最新日K截面因子值' : (factorStocks.sort_basis || '--')}
                              {factorStocks.factor_definition ? ` · 定义: ${factorStocks.factor_definition}` : ''}
                            </div>
                            <div>
                              截面生成: {factorStocks.snapshot_generated_at || '--'} · 数据日期: {factorStocks.data_latest_date || '--'} · 来源: {factorStocks.snapshot_source || '--'}
                            </div>
                            <div>
                              数据版本: {factorStocks.data_version ? String(factorStocks.data_version).slice(0, 12) : '--'} · 股票池: {factorStocks.universe_policy === 'current_tradeable_v1' ? '当前可交易股票池 v1' : (factorStocks.universe_policy || '--')} · 状态: {factorStocks.promotion_state === 'research_only' ? '仅限研究' : (factorStocks.promotion_state || '--')}
                            </div>
                            {factorStocks.is_stale && (
                              <div style={{ color: '#F59E0B' }}>
                                {factorStocks.freshness_warning || '因子截面数据已过期，当前排名仅供历史参考。'}
                              </div>
                            )}
                          </div>
                          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                            <div>
                              <div style={{ fontSize: 12, fontWeight: 600, color: '#4ADE80', marginBottom: 4 }}>▲ 多头（数值最大的前 15 只）</div>
                              {top.map((s, i) => renderStock(s, i, true))}
                            </div>
                            <div>
                              <div style={{ fontSize: 12, fontWeight: 600, color: '#F87171', marginBottom: 4 }}>▼ 空头（数值最小的后 15 只）</div>
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
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '4px 0', fontSize: 12, color: '#475569', letterSpacing: 0.5 }}>
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
                  <div key={f.name} title={f.desc} style={{ padding: '6px 10px', background: '#1E293B', borderRadius: 6, fontSize: 11, color: '#94A3B8', display: 'flex', flexDirection: 'column', gap: 3, maxWidth: 170, minWidth: 120 }}>
                    <span style={{ fontFamily: 'JetBrains Mono, monospace', color: ACCENT, fontSize: 12 }}>{f.name}</span>
                    <span style={{ color: '#CBD5E1', fontSize: 12, fontWeight: 600 }}>{f.chinese_name || f.label}</span>
                    <span style={{ color: '#64748B', fontSize: 12, lineHeight: 1.35 }}>{f.desc}</span>
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
              <div style={{ fontSize: 12, color: '#475569', marginBottom: 5 }}>因子名称</div>
              <select value={fname} onChange={e => setFname(e.target.value)}
                style={{ padding: '8px 12px', background: '#0B0F1A', border: '1px solid #1E293B', borderRadius: 8, color: '#E2E8F0', fontSize: 13, width: 240, outline: 'none' }}
                onFocus={e => (e.target.style.borderColor = ACCENT)} onBlur={e => (e.target.style.borderColor = '#1E293B')}>
                {factors.map(f => (
                  <option key={f.name} value={f.name}>{f.name} · {f.chinese_name || f.label}</option>
                ))}
              </select>
            </div>
            <div style={{ flex: 1, minWidth: 200 }}>
              <div style={{ fontSize: 12, color: '#475569', marginBottom: 5 }}>股票代码</div>
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

          {evalResult && (() => {
            const summary = evalResult?.summary;
            const hasSummary = summary && typeof summary.mean === 'number';
            return (
            <>
              {!hasSummary && (
                <div style={{ padding: '12px 16px', background: '#FBBF2414', border: '1px solid #FBBF2433', borderRadius: 10, fontSize: 12, color: '#FBBF24', display: 'flex', alignItems: 'center', gap: 8 }}>
                  <AlertTriangle style={{ width: 14, height: 14 }} />
                  <span>该因子在所选股票中无有效数据 (可能为基本面因子且财务数据缺失/全 NaN)。请尝试换用技术或量价因子，或补充财务数据。</span>
                </div>
              )}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
                <MetricCard label="IC 均值" value={hasSummary ? `${summary.mean >= 0 ? '+' : ''}${(summary.mean * 100).toFixed(2)}%` : '--'}
                  color={hasSummary && summary.mean > 0 ? '#4ADE80' : '#F87171'} sub="Mean IC" />
                <MetricCard label="IC 标准差" value={hasSummary ? summary.std.toFixed(4) : '--'} color="#94A3B8" sub="Std" />
                <MetricCard label="IR" value={hasSummary ? summary.ir.toFixed(3) : '--'} color={hasSummary ? irColor(summary.ir) : '#64748B'} sub="Information Ratio" />
                <MetricCard label="IC > 0 占比" value={hasSummary ? `${(summary.positive_ratio * 100).toFixed(1)}%` : '--'}
                  color={hasSummary && summary.positive_ratio > 0.5 ? '#4ADE80' : '#F87171'} sub="Positive Ratio" />
              </div>
              <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, padding: 16 }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: '#94A3B8', marginBottom: 14 }}>IC 周期衰减</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {(Object.entries(evalResult.decay || {}).length > 0
                    ? Object.entries(evalResult.decay)
                        .sort(([a], [b]) => parseInt(a.replace('fwd_','')) - parseInt(b.replace('fwd_','')))
                        .map(([k, v]: [string, ICResult]) => <ICBar key={k} name={k} mean={v?.mean ?? 0} />)
                    : [<div key="none" style={{ fontSize: 11, color: '#475569', textAlign: 'center', padding: '8px 0' }}>无衰减数据</div>]
                  )}
                </div>
              </div>
              {segmentResult && <SegmentStabilityTable data={segmentResult} />}
            </>
            );
          })()}
        </div>
      )}

      {/* ── Batch IC ── */}
      {tab === 'batch' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, padding: 16, display: 'flex', gap: 12, alignItems: 'flex-end' }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 12, color: '#475569', marginBottom: 5 }}>股票列表 (逗号分隔)</div>
              <input value={batchCodes} onChange={e => setBatchCodes(e.target.value)}
                style={{ padding: '8px 12px', background: '#0B0F1A', border: '1px solid #1E293B', borderRadius: 8, color: '#E2E8F0', fontSize: 12, width: '100%', outline: 'none' }}
                onFocus={e => (e.target.style.borderColor = ACCENT)} onBlur={e => (e.target.style.borderColor = '#1E293B')} />
            </div>
            <button onClick={runBatch} disabled={batchLoading}
              style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 18px', background: ACCENT, border: 'none', borderRadius: 8, color: '#0B0F1A', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>
              {batchLoading ? <Loader2 style={{ width: 13, height: 13, animation: 'spin 1s linear infinite' }} /> : <BarChart3 style={{ width: 13, height: 13 }} />}
              批量评估全部{factors.length || ''}因子
            </button>
          </div>

          {batchError && <div style={{ padding: '10px 14px', background: '#EF444414', border: '1px solid #EF444433', borderRadius: 8, fontSize: 12, color: '#F87171' }}>
            <AlertTriangle style={{ width: 12, height: 12, display: 'inline', marginRight: 6 }} />{batchError}
          </div>}

          {batchResult && (
            <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, overflow: 'hidden' }}>
              <div style={{ padding: '10px 16px', background: '#0B0F1A', borderBottom: '1px solid #1E293B', fontSize: 12, fontWeight: 600, color: '#94A3B8' }}>
                {factors.length || ''}因子 IC 排行 — fwd_1
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
