import React, { useState, useEffect, useCallback } from 'react';
import { BrainCircuit, Loader2, AlertTriangle, Play, List, Clock, ChevronRight, Zap, Trophy, Layers, Settings2 } from 'lucide-react';
import PaperStrategyConfig from './PaperStrategyConfig';
import { ResearchBoundary } from './ResearchBoundary';

const API_BASE = (import.meta as any).env?.VITE_API_BASE || '';
const API_TOKEN = (import.meta as any).env?.VITE_XUANJI_API_TOKEN || '';
const jsonHeaders = () => ({ 'Content-Type': 'application/json', ...(API_TOKEN ? { 'X-XuanJi-Token': API_TOKEN } : {}) });
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
    <div style={{ fontSize: 12, color: '#475569', marginBottom: 6, letterSpacing: 0.5 }}>{label}</div>
    <div style={{ fontSize: 20, fontWeight: 700, fontFamily: 'JetBrains Mono, monospace', color: color || '#F1F5F9' }}>{value}</div>
  </div>
);

const displayCompactDate = (value: unknown) => {
  const compact = String(value || '').replace(/-/g, '').slice(0, 8);
  return /^\d{8}$/.test(compact)
    ? `${compact.slice(0, 4)}-${compact.slice(4, 6)}-${compact.slice(6, 8)}`
    : '--';
};

// 纯 SVG 净值曲线 + 回撤图 (零依赖, 与 K线图风格一致)
const EquityCurve: React.FC<{ snapshots: any[] }> = ({ snapshots }) => {
  if (!snapshots || snapshots.length < 2) return null;
  const W = 760, H = 180, PAD = 28;
  const initial = snapshots[0].equity || 1;
  // 净值 = equity / initial
  const navs = snapshots.map(s => (Number(s.equity) || initial) / initial);
  const dds = snapshots.map(s => Number(s.drawdown || 0)); // 回撤百分比 (负值)
  const xOf = (i: number) => PAD + (i / (snapshots.length - 1)) * (W - 2 * PAD);
  const navMin = Math.min(...navs), navMax = Math.max(...navs);
  const navRange = Math.max(0.001, navMax - navMin);
  const yNav = (v: number) => (H * 0.55) - ((v - navMin) / navRange) * (H * 0.45) + PAD * 0.3;
  const ddMin = Math.min(...dds, -1), ddMax = 0;
  const yDd = (v: number) => H - PAD - ((v - ddMin) / (ddMax - ddMin)) * (H * 0.25);

  const navPath = navs.map((v, i) => `${i === 0 ? 'M' : 'L'} ${xOf(i).toFixed(1)} ${yNav(v).toFixed(1)}`).join(' ');
  // 回撤面积 (从 0 线向下)
  const ddZero = yDd(0);
  const ddPath = dds.map((v, i) => `${i === 0 ? 'M' : 'L'} ${xOf(i).toFixed(1)} ${yDd(v).toFixed(1)}`).join(' ');
  const ddArea = `${ddPath} L ${xOf(snapshots.length - 1).toFixed(1)} ${ddZero} L ${xOf(0).toFixed(1)} ${ddZero} Z`;
  const upColor = navs[navs.length - 1] >= 1 ? '#4ADE80' : '#F87171';
  const finalNav = (navs[navs.length - 1] - 1) * 100;
  const maxDd = Math.min(...dds);

  return (
    <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, padding: '12px 16px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: '#94A3B8' }}>净值曲线 / 回撤</div>
        <div style={{ display: 'flex', gap: 16, fontSize: 11, fontFamily: 'JetBrains Mono, monospace' }}>
          <span style={{ color: upColor }}>期末净值 {(navs[navs.length - 1]).toFixed(4)} ({finalNav >= 0 ? '+' : ''}{finalNav.toFixed(2)}%)</span>
          <span style={{ color: '#F87171' }}>最大回撤 {maxDd.toFixed(2)}%</span>
          <span style={{ color: '#475569' }}>{snapshots.length} 日</span>
        </div>
      </div>
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: 'block' }}>
        {/* 回撤面积 (红色半透明, 在下方) */}
        <path d={ddArea} fill="#F8717122" stroke="none" />
        <path d={ddPath} fill="none" stroke="#F87171" strokeWidth="1" opacity="0.7" />
        {/* 0 线 (净值基准) */}
        <line x1={PAD} y1={yNav(1)} x2={W - PAD} y2={yNav(1)} stroke="#334155" strokeWidth="0.5" strokeDasharray="3 3" />
        {/* 净值曲线 */}
        <path d={navPath} fill="none" stroke={upColor} strokeWidth="1.5" />
        {/* Y 轴标签 */}
        <text x={4} y={yNav(navMax)} fontSize="9" fill="#64748B" fontFamily="monospace">{navMax.toFixed(2)}</text>
        <text x={4} y={yNav(navMin)} fontSize="9" fill="#64748B" fontFamily="monospace">{navMin.toFixed(2)}</text>
        <text x={4} y={ddZero - 2} fontSize="9" fill="#475569" fontFamily="monospace">0%</text>
        <text x={4} y={yDd(ddMin)} fontSize="9" fill="#F87171" fontFamily="monospace">{ddMin.toFixed(1)}%</text>
        {/* X 轴首尾日期 */}
        <text x={PAD} y={H - 4} fontSize="9" fill="#475569" fontFamily="monospace">{snapshots[0].date}</text>
        <text x={W - PAD - 50} y={H - 4} fontSize="9" fill="#475569" fontFamily="monospace">{snapshots[snapshots.length - 1].date}</text>
      </svg>
      <div style={{ fontSize: 11, color: '#475569', marginTop: 4 }}>
        上：净值曲线（基准 = 初始权益 1.0）；下：回撤面积（红色，相对历史最高净值的回撤）。仅基于历史回测快照，不代表未来。
      </div>
    </div>
  );
};

const StrategyPanel: React.FC = () => {
  const [tab, setTab] = useState<'scan'|'combo'|'list'|'run'|'paper'>('scan');
  const [paperDirty, setPaperDirty] = useState(false);
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
  const [researchSelection, setResearchSelection] = useState<any>(null);
  const [selectionLoading, setSelectionLoading] = useState(false);
  const [selectionError, setSelectionError] = useState('');
  // 多因子组合
  const [comboFactors, setComboFactors] = useState<Array<{name: string, weight: number}>>([
    { name: 'net_margin', weight: 0.3 },
    { name: 'volatility_20', weight: 0.25 },
    { name: 'turnover_5', weight: 0.2 },
    { name: 'roa', weight: 0.15 },
    { name: 'ret_60', weight: 0.1 },
  ]);
  const [comboCodes, setComboCodes] = useState('000001,600036,601318,000858,600519,601398,000725,600276,601012,002594,300750,688981');
  const [comboHold, setComboHold] = useState(5);
  const [comboLoading, setComboLoading] = useState(false);
  const [comboError, setComboError] = useState('');
  const [comboResult, setComboResult] = useState<any>(null);
  const [factorList, setFactorList] = useState<string[]>([]);

  const loadScan = useCallback(async () => {
    setScanLoading(true); setScanError('');
    try { setScan(await api({ action: 'market_scan' })); }
    catch (e: any) { setScanError(e.message); }
    setScanLoading(false);
  }, []);

  const loadResearchSelection = useCallback(async () => {
    setSelectionLoading(true); setSelectionError('');
    try { setResearchSelection(await api({ action: 'research_selection' })); }
    catch (e: any) { setSelectionError(e.message); }
    setSelectionLoading(false);
  }, []);

  useEffect(() => {
    api({ action: 'meta' }).then(setMeta).catch(() => {});
    loadScan();
    loadResearchSelection();
    // 加载因子列表供多因子组合选择
    fetch(`${API_BASE}/api/factor`, { method: 'POST', headers: jsonHeaders(), body: JSON.stringify({ action: 'meta' }) })
      .then(r => r.json()).then(d => { if (d.success && d.data) setFactorList(Object.keys(d.data)); }).catch(() => {});
  }, [loadScan, loadResearchSelection]);

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

  const runCombo = useCallback(async () => {
    setComboLoading(true); setComboError(''); setComboResult(null);
    try {
      const factors = comboFactors.map(f => f.name).join(',');
      const weights = comboFactors.map(f => f.weight).join(',');
      const d = await api({ action: 'run', name: 'multi_factor', params: { factors, weights, hold_days: comboHold }, codes: comboCodes.split(',').map(s => s.trim()).filter(Boolean) });
      setComboResult(d);
    } catch (e: any) { setComboError(e.message); }
    setComboLoading(false);
  }, [comboFactors, comboCodes, comboHold]);

  const totalWeight = comboFactors.reduce((s, f) => s + f.weight, 0);

  const summary = result?.backtest?.summary;
  const perStock = result?.backtest?.per_stock || {};
  const details = result?.backtest?.details || [];
  const snapshots: any[] = result?.backtest?.daily_snapshots || [];

  const tabs = [
    { key: 'scan', label: 'F4 组合验证', icon: Trophy },
    { key: 'combo', label: '诊断：多因子', icon: Layers },
    { key: 'list', label: '策略列表', icon: List },
    { key: 'run',  label: '诊断：策略回测', icon: Play },
    { key: 'paper', label: '历史模拟配置', icon: Settings2 },
  ];

  const selectTab = (nextTab: typeof tab) => {
    if (tab === 'paper' && nextTab !== 'paper' && paperDirty) {
      const leave = window.confirm('模拟交易配置尚未保存，确认离开并放弃当前修改？');
      if (!leave) return;
    }
    setTab(nextTab);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 22 }}>
      <ResearchBoundary source="确定性策略研究、F4 组合验证与诊断回测" />
      <div style={{ padding: '9px 12px', borderLeft: '2px solid #38BDF8', background: '#111827', color: '#718096', fontSize: 12, lineHeight: 1.6 }}>
        样本外状态、交易成本、容量与冲击、基准和股票池定义必须同时可验证，历史年化与夏普才可用于策略比较；缺失项按“未提供”处理。
      </div>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ width: 40, height: 40, borderRadius: 10, background: `${ACCENT}22`, border: `1px solid ${ACCENT}44`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <BrainCircuit style={{ width: 20, height: 20, color: ACCENT }} />
        </div>
        <div>
          <div style={{ fontSize: 'var(--font-page-title)', fontWeight: 700, color: '#F1F5F9' }}>F4 策略与组合验证</div>
          <div style={{ fontSize: 11, color: '#64748B' }}>确定性样本外验证 · 组合约束 · 研究门禁</div>
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, background: '#111827', padding: 4, borderRadius: 8, border: '1px solid #1E293B', width: 'fit-content', maxWidth: '100%' }}>
        {tabs.map(t => {
          const Icon = t.icon;
          const is = tab === t.key;
          return (
            <button key={t.key} onClick={() => selectTab(t.key as typeof tab)}
              style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 16px', borderRadius: 7, border: 'none', cursor: 'pointer', fontSize: 13, fontWeight: is ? 600 : 400,
                background: is ? `${ACCENT}18` : 'transparent', color: is ? ACCENT : '#64748B', transition: 'all 150ms' }}>
              <Icon style={{ width: 14, height: 14 }} />{t.label}
              {t.key === 'paper' && paperDirty && <span title="有未保存更改" style={{ width: 6, height: 6, borderRadius: '50%', background: '#FBBF24' }} />}
            </button>
          );
        })}
      </div>

      {/* ── F4 策略与组合级验证（只读研究证据） ── */}
      {tab === 'scan' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {scanLoading && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: 30, color: '#64748B', fontSize: 13 }}>
              <Loader2 style={{ width: 14, height: 14, animation: 'spin 1s linear infinite' }} />加载 F4 验证证据...
            </div>
          )}
          {scanError && (
            <div style={{ padding: '12px 16px', background: '#FBBF2414', border: '1px solid #FBBF2433', borderRadius: 10, fontSize: 12, color: '#FBBF24', display: 'flex', alignItems: 'center', gap: 8 }}>
              <AlertTriangle style={{ width: 14, height: 14 }} /><span>{scanError}</span>
              <button onClick={loadScan} style={{ marginLeft: 'auto', padding: '4px 10px', background: '#FBBF2422', border: 'none', borderRadius: 6, color: '#FBBF24', fontSize: 11, cursor: 'pointer' }}>重试</button>
            </div>
          )}
          {scan && !scanLoading && (() => {
            const statusLabels: Record<string, string> = {
              f4_blocked: '数据门禁阻断',
              f4_rejected: '未通过组合门禁',
              f4_rejected_exhausted: '候选已穷尽，未通过门禁',
              f4_research_candidate: '研究候选',
            };
            const reasonLabels: Record<string, string> = {
              pit_manifest_incomplete: '六年 PIT 数据清单未完成',
              pit_quality_failed: 'PIT 数据质量门禁未通过',
              pit_quality_missing: '缺少 PIT 数据质量报告',
              pit_industry_missing: '缺少有效日期行业历史',
              benchmark_missing: '缺少可版本化基准数据',
              benchmark_coverage_failed: '基准交易日覆盖率不足',
              f3_evidence_missing: '缺少 F3 因子证据',
              f4_validation_inputs_missing: '尚未生成真实走样本外窗口指标',
              insufficient_windows: '样本外窗口不足',
              window_count_below_4: '完整样本外窗口少于 4 个',
              positive_excess_window_ratio_below_0_60: '正超额窗口占比低于 60%',
              after_cost_excess_return_not_positive: '聚合费后超额收益不为正',
              sharpe_below_0_80: '聚合夏普低于 0.80',
              max_drawdown_below_minus_0_20: '最差窗口最大回撤低于 -20%',
              double_cost_excess_return_not_positive: '双倍成本下超额收益不为正',
              portfolio_constraint_failed: '组合目标硬约束存在违规',
              future_data_detected: '检测到未来数据或拟合日期越界',
            };
            const metrics = scan.metrics || {};
            const windows: any[] = scan.window_metrics || scan.windows || [];
            const stressMetrics = scan.stress_metrics || {};
            const inputStatus = scan.input_status || {};
            const reasons: string[] = scan.reasons || (scan.reason_code ? [scan.reason_code] : []);
            const visibleStatus = scan.display_status || scan.status;
            const readiness = scan.readiness || {};
            const readinessLabels: Record<string, string> = {
              blocked: '阻断',
              ready: '已就绪 · 等待事件补跑',
              current: '当前证据已同步',
            };
            const selectedPolicies: any[] = scan.candidate_spec?.selected_policies || [];
            const candidatePolicies: any[] = scan.candidate_spec?.registry || selectedPolicies;
            const familyLabels: Record<string, string> = {
              momentum: '动量',
              reversal: '反转',
              defensive: '防御',
              liquidity: '流动性',
              ensemble: '组合增强',
              qlib: 'Qlib 模型',
            };
            const familyRows = Object.entries(scan.family_diagnostics || {}).map(([family, value]: [string, any]) => ({ family, ...(value || {}) }));
            const formatReasonCounts = (reasons: unknown) => {
              const entries = Object.entries((reasons && typeof reasons === 'object') ? reasons as Record<string, unknown> : {});
              return entries.length ? entries.map(([reason, count]) => `${reason} × ${count}`).join('；') : '无';
            };
            const numberValue = (value: unknown, digits = 2) => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : '--';
            const maxWindowValue = (field: string) => windows.reduce((maximum, window) => Math.max(maximum, Number(window?.[field]) || 0), 0);
            const totalWindowValue = (field: string) => windows.reduce((total, window) => total + (Number(window?.[field]) || 0), 0);
            const maxCandidatePolicyValue = (field: string) => candidatePolicies.reduce((maximum, policy) => Math.max(maximum, Number(policy?.[field]) || 0), 0);
            const candidatePolicyPct = (field: string) => candidatePolicies.length ? `${numberValue(maxCandidatePolicyValue(field) * 100, 1)}%` : '--';
            return (
              <>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 12 }}>
                  <MetricCard label="F4 状态" value={statusLabels[visibleStatus] || visibleStatus || '建设中'} color={scan.status === 'f4_research_candidate' ? '#4ADE80' : '#FBBF24'} />
                  <MetricCard label="每日因子/选股日" value={readiness.daily_market_date || displayCompactDate(researchSelection?.selection_date)} color="#34D399" />
                  <MetricCard label="PIT 数据可用日" value={readiness.pit_market_date || '--'} color="#60A5FA" />
                  <MetricCard label="最新完成 F4 证据日" value={readiness.f4_evidence_market_date || scan.market_date || '--'} color="#94A3B8" />
                  <MetricCard label="当前重验准备状态" value={readinessLabels[readiness.status] || readiness.status || '--'} color={readiness.status === 'current' ? '#4ADE80' : '#FBBF24'} />
                  <MetricCard label="样本外窗口" value={String(windows.length)} color="#94A3B8" />
                  <MetricCard label="生成时间" value={(scan.generated_at || '').replace('T', ' ').slice(5, 16) || '--'} color="#94A3B8" />
                </div>

                {readiness.status !== 'current' && (
                  <div style={{ padding: '12px 14px', background: '#FBBF2410', border: '1px solid #FBBF2433', borderRadius: 8, fontSize: 12, color: '#FBBF24', lineHeight: 1.7 }}>
                    <div style={{ fontWeight: 700 }}>当前重新验证状态</div>
                    <div>{reasonLabels[readiness.reason_code] || readiness.reason_code || '等待上游数据完成'}</div>
                    {readiness.pit_progress?.requested > 0 && <div style={{ color: '#94A3B8' }}>PIT 进度：{readiness.pit_progress.processed}/{readiness.pit_progress.requested}</div>}
                    {readiness.trigger_required && <div style={{ color: '#7DD3FC' }}>PIT 完整代发布后将使用同周幂等键进行一次事件补跑；周日主任务仍保留。</div>}
                  </div>
                )}

                <div style={{ padding: '12px 14px', background: '#38BDF810', border: '1px solid #38BDF833', borderRadius: 8, fontSize: 12, color: '#7DD3FC', display: 'flex', alignItems: 'center', gap: 8 }}>
                  <AlertTriangle style={{ width: 12, height: 12 }} />
                  <strong>仅供研究。</strong> 研究结果，不代表已获交易权限；F4 结果不构成目标持仓、买卖信号或执行授权，所有状态的 execution_authority 均为 false。
                </div>

                {scan.status !== 'f4_research_candidate' && reasons.length > 0 && (
                  <div style={{ padding: '12px 14px', background: '#FBBF2410', border: '1px solid #FBBF2433', borderRadius: 8, fontSize: 12, color: '#FBBF24' }}>
                    <div style={{ fontWeight: 700, marginBottom: 5 }}>{scan.status === 'f4_blocked' ? '当前无法进入组合评估' : '本轮未通过 F4 研究门禁'}</div>
                    {reasons.map(reason => <div key={reason}>· {reasonLabels[reason] || reason} <span style={{ color: '#64748B' }}>({reason})</span></div>)}
                  </div>
                )}

                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 12 }}>
                  <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, padding: 16 }}>
                    <div style={{ color: '#E2E8F0', fontWeight: 700, marginBottom: 4 }}>历史 F4 证据门禁</div>
                    <div style={{ color: '#64748B', fontSize: 11, marginBottom: 8 }}>对应最新完成 F4 证据日 {readiness.f4_evidence_market_date || scan.market_date || '--'}，不代表当前 PIT 已完成。</div>
                    <div style={{ color: '#94A3B8', fontSize: 12, lineHeight: 1.9 }}>
                      <div>F3 因子证据：{inputStatus.f3_evidence || 'missing'}</div>
                      <div>六年 PIT 清单：{inputStatus.pit_manifest || 'missing'}</div>
                      <div>PIT 质量报告：{scan.pit_quality_report_id || inputStatus.pit_quality || 'missing'}</div>
                      <div>历史行业版本：{scan.industry_version || inputStatus.pit_industry || 'missing'}</div>
                      <div>基准版本：{scan.benchmark_version || 'missing'}</div>
                    </div>
                  </div>
                  <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, padding: 16 }}>
                    <div style={{ color: '#E2E8F0', fontWeight: 700, marginBottom: 10 }}>研究身份</div>
                    <div style={{ color: '#94A3B8', fontSize: 12, lineHeight: 1.9, overflowWrap: 'anywhere' }}>
                      <div>候选规格：{scan.candidate_spec_version || '--'}</div>
                      <div>{scan.factory_version === 'f4-multi-alpha-candidate-factory-v2' ? '24 个预登记候选' : `候选数量：${scan.candidate_count ?? scan.candidate_spec?.registry?.length ?? '--'}（固定有界）`}</div>
                      <div>逐窗口胜出规格：{selectedPolicies.length ? selectedPolicies.map(item => `Top${item.top_k}/${item.rebalance_bars}日`).join('，') : '--'}</div>
                      <div>候选工厂：{scan.candidate_factory_status === 'exhausted' ? '已穷尽，等待下一数据版本或周度重评' : (scan.candidate_factory_status || '--')}</div>
                      <div>工厂 ID：{scan.factory_run_id || '--'}</div>
                      <div>组合规则：{scan.portfolio_policy_version || '--'}</div>
                      <div>成本模型：{scan.cost_model_version || '--'}</div>
                      <div>验证 ID：{scan.validation_id || '--'}</div>
                    </div>
                  </div>
                </div>

                {familyRows.length > 0 && (
                  <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, padding: 16, overflowX: 'auto' }}>
                    <div style={{ color: '#E2E8F0', fontWeight: 700, marginBottom: 10 }}>候选族</div>
                    <table style={{ width: '100%', minWidth: 720, borderCollapse: 'collapse', color: '#94A3B8', fontSize: 12 }}>
                      <thead>
                        <tr style={{ color: '#64748B', textAlign: 'left', borderBottom: '1px solid #1E293B' }}>
                          <th style={{ padding: '8px 6px' }}>候选族</th>
                          <th style={{ padding: '8px 6px' }}>登记</th>
                          <th style={{ padding: '8px 6px' }}>可用</th>
                          <th style={{ padding: '8px 6px' }}>不可用</th>
                          <th style={{ padding: '8px 6px' }}>验证胜出窗口</th>
                          <th style={{ padding: '8px 6px' }}>不可用原因</th>
                        </tr>
                      </thead>
                      <tbody>
                        {familyRows.map(row => (
                          <tr key={row.family} style={{ borderBottom: '1px solid #1E293B88' }}>
                            <td style={{ padding: '8px 6px', color: '#E2E8F0' }}>{familyLabels[row.family] || row.family}</td>
                            <td style={{ padding: '8px 6px' }}>{row.registered ?? '--'}</td>
                            <td style={{ padding: '8px 6px', color: '#4ADE80' }}>{row.available ?? '--'}</td>
                            <td style={{ padding: '8px 6px', color: row.unavailable ? '#FBBF24' : '#64748B' }}>{row.unavailable ?? '--'}</td>
                            <td style={{ padding: '8px 6px' }}>{row.validation_wins ?? '--'}</td>
                            <td style={{ padding: '8px 6px', overflowWrap: 'anywhere' }}>{formatReasonCounts(row.reason_counts)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, padding: 16 }}>
                  <div style={{ color: '#E2E8F0', fontWeight: 700, marginBottom: 10 }}>样本外窗口</div>
                  {windows.length === 0 ? (
                    <div style={{ color: '#64748B', fontSize: 12 }}>数据门禁通过后，按 504 日训练、126 日验证、126 日测试及 purge/embargo 规则生成；当前没有可冒充的窗口结果。</div>
                  ) : (
                    <div style={{ display: 'grid', gap: 7 }}>
                      {windows.map((window, index) => (
                        <div key={window.window_id || index} style={{ display: 'grid', gridTemplateColumns: '80px repeat(5, minmax(90px, 1fr))', gap: 8, color: '#94A3B8', fontSize: 12, fontVariantNumeric: 'tabular-nums' }}>
                          <span>{window.window_id || `窗口 ${index + 1}`}</span>
                          <span>超额 {numberValue(window.excess_return_pct)}%</span>
                          <span>夏普 {numberValue(window.sharpe)}</span>
                          <span>回撤 {numberValue(window.max_drawdown_pct)}%</span>
                          <span>成交 {numberValue(window.trade_count, 0)} 笔</span>
                          <span>行业峰值 {numberValue(Number(window.max_realized_industry_weight || 0) * 100, 1)}%</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
                  <MetricCard label="样本外夏普" value={numberValue(metrics.sharpe)} />
                  <MetricCard label="最大回撤" value={`${numberValue(metrics.max_drawdown_pct)}%`} />
                  <MetricCard label="费后超额" value={`${numberValue(metrics.after_cost_excess_return_pct)}%`} />
                  <MetricCard label="正超额窗口占比" value={metrics.positive_excess_window_ratio != null ? `${numberValue(metrics.positive_excess_window_ratio * 100, 1)}%` : '--'} />
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 12 }}>
                  <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, padding: 16 }}>
                    <div style={{ color: '#E2E8F0', fontWeight: 700, marginBottom: 8 }}>成本压力</div>
                    <div style={{ color: '#94A3B8', fontSize: 12, lineHeight: 1.9, fontVariantNumeric: 'tabular-nums' }}>
                      <div>1.0 倍成本：{numberValue(Number(stressMetrics['1.0']?.excess_return || 0) * 100)}% 超额</div>
                      <div>1.5 倍成本：{numberValue(Number(stressMetrics['1.5']?.excess_return || 0) * 100)}% 超额</div>
                      <div>2.0 倍成本：{numberValue(Number(stressMetrics['2.0']?.excess_return || 0) * 100)}% 超额</div>
                      <div>基础场景总成本：{numberValue(totalWindowValue('total_cost'), 0)} 元</div>
                    </div>
                  </div>
                  <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, padding: 16 }}>
                    <div style={{ color: '#E2E8F0', fontWeight: 700, marginBottom: 8 }}>容量约束</div>
                    <div style={{ color: '#94A3B8', fontSize: 12, lineHeight: 1.9, fontVariantNumeric: 'tabular-nums' }}>
                      <div>目标单票上限：{numberValue(maxWindowValue('max_name_weight') * 100, 1)}% / 候选硬上限 {candidatePolicyPct('max_name_weight')}</div>
                      <div>目标行业上限：{numberValue(maxWindowValue('max_industry_weight') * 100, 1)}% / 候选硬上限 {candidatePolicyPct('max_industry_weight')}</div>
                      <div>持有期行业峰值：{numberValue(maxWindowValue('max_realized_industry_weight') * 100, 1)}%（价格漂移，非目标违规）</div>
                      <div>容量拒绝金额：{numberValue(totalWindowValue('capacity_rejected_notional'), 0)} 元；目标约束违规 {numberValue(metrics.constraint_violation_count, 0)} 次</div>
                    </div>
                  </div>
                </div>
              </>
            );
          })()}

          <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, overflow: 'hidden' }}>
            <div style={{ padding: '14px 16px', borderBottom: '1px solid #1E293B', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16 }}>
              <div>
                <div style={{ color: '#E2E8F0', fontWeight: 700 }}>每日研究选股组合</div>
                <div style={{ color: '#64748B', fontSize: 11, marginTop: 5 }}>
                  独立消费当前因子快照；不覆盖 F4 周验证，也不构成交易信号。
                </div>
              </div>
              <button onClick={loadResearchSelection} disabled={selectionLoading}
                style={{ padding: '5px 11px', background: '#1E293B', border: '1px solid #334155', borderRadius: 6, color: '#94A3B8', fontSize: 11, cursor: selectionLoading ? 'wait' : 'pointer' }}>
                {selectionLoading ? '加载中…' : '刷新组合'}
              </button>
            </div>

            {researchSelection?.research_refresh?.state === 'refreshing' && researchSelection?.is_current === false && (
              <div style={{ margin: 14, padding: '10px 12px', background: '#0C4A6E33', border: '1px solid #38BDF844', borderRadius: 8, color: '#7DD3FC', fontSize: 12 }}>
                正在更新目标日期 {displayCompactDate(researchSelection.research_refresh.target_date)}，当前展示上一完整版本；新一代因子、评估与选股将完成后一次切换。
              </div>
            )}

            {researchSelection?.is_current === false && researchSelection?.research_refresh?.state !== 'refreshing' && (
              <div style={{ margin: 14, padding: '10px 12px', background: '#451A0322', border: '1px solid #F59E0B55', borderRadius: 8, color: '#FBBF24', fontSize: 12 }}>
                研究选股已过期：{researchSelection.freshness_warning || '当前组合仅供历史参考，等待下一次确定性研究流水线完成。'}
              </div>
            )}

            {selectionError && (
              <div style={{ margin: 14, padding: '10px 12px', background: '#FBBF2414', border: '1px solid #FBBF2433', borderRadius: 8, color: '#FBBF24', fontSize: 12 }}>
                研究选股不可用：{selectionError}
              </div>
            )}

            {researchSelection && !selectionLoading && (
              <>
                <div style={{ padding: '12px 16px', display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 12, borderBottom: '1px solid #1E293B', fontSize: 12 }}>
                  <div><span style={{ color: '#475569' }}>选股日期</span><div style={{ color: '#E2E8F0', marginTop: 3 }}>{displayCompactDate(researchSelection.selection_date)}</div></div>
                  <div><span style={{ color: '#475569' }}>股票数量</span><div style={{ color: '#E2E8F0', marginTop: 3 }}>{researchSelection.position_count ?? researchSelection.positions?.length ?? 0}</div></div>
                  <div><span style={{ color: '#475569' }}>F4 来源状态</span><div style={{ color: researchSelection.source_validation_rejected ? '#FBBF24' : '#4ADE80', marginTop: 3 }}>{researchSelection.f4_gate_status || '--'}</div></div>
                  <div style={{ minWidth: 0 }}><span style={{ color: '#475569' }}>组合 ID</span><div title={researchSelection.portfolio_id} style={{ color: '#94A3B8', marginTop: 3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontFamily: 'JetBrains Mono, monospace' }}>{researchSelection.portfolio_id || '--'}</div></div>
                </div>

                {researchSelection.source_validation_rejected && (
                  <div style={{ margin: 14, padding: '10px 12px', background: '#FBBF2410', border: '1px solid #FBBF2433', borderRadius: 8, color: '#FBBF24', fontSize: 12 }}>
                    F4 组合级门禁未通过；以下结果不能晋升为合格策略或进入实盘，F5 实验模拟准入由独立硬风控判定。
                  </div>
                )}

                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 980, fontSize: 12 }}>
                    <thead>
                      <tr style={{ color: '#64748B', textAlign: 'left', background: '#0B0F1A' }}>
                        {['代码', '名称', '行业', '研究得分', '研究权重', '参考收盘价', '研究理由'].map(label => (
                          <th key={label} style={{ padding: '9px 12px', fontWeight: 600, whiteSpace: 'nowrap', width: label === '研究理由' ? '42%' : undefined }}>{label}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {(researchSelection.positions || []).map((position: any) => (
                        <tr key={position.code} style={{ borderTop: '1px solid #1E293B', color: '#CBD5E1' }}>
                          <td style={{ padding: '9px 12px', fontFamily: 'JetBrains Mono, monospace' }}>{position.code}</td>
                          <td style={{ padding: '9px 12px', color: '#F1F5F9', whiteSpace: 'nowrap' }}>{position.name || '--'}</td>
                          <td style={{ padding: '9px 12px', whiteSpace: 'nowrap' }}>{position.industry || '行业未知'}</td>
                          <td style={{ padding: '9px 12px', fontFamily: 'JetBrains Mono, monospace' }}>{Number(position.score || 0).toFixed(4)}</td>
                          <td style={{ padding: '9px 12px', fontFamily: 'JetBrains Mono, monospace', color: '#34D399' }}>{(Number(position.target_weight || 0) * 100).toFixed(2)}%</td>
                          <td style={{ padding: '9px 12px', fontFamily: 'JetBrains Mono, monospace' }}>{Number(position.reference_close || 0).toFixed(2)}</td>
                          <td style={{ padding: '9px 16px 9px 12px', color: '#94A3B8', lineHeight: 1.55, minWidth: 360, whiteSpace: 'normal' }}>{position.research_reason || '--'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div style={{ padding: '10px 16px', borderTop: '1px solid #1E293B', color: '#7DD3FC', fontSize: 11 }}>
                  权限边界：research_only · execution_authority=false · 不构成交易信号
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* ── 多因子组合 ── */}
      {tab === 'combo' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{ fontSize: 11, color: '#64748B', lineHeight: 1.6, padding: '8px 12px', background: '#0B0F1A', borderRadius: 8 }}>
            选择多个有效因子，按权重组合成综合打分，对全市场股票排名后做多 Top N / 做空 Bottom N。
            权重建议：基本面因子正向（net_margin/roe/roa），波动率/换手率因子负向（volatility_20/turnover_5）。
          </div>

          {/* 因子选择+权重 */}
          <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, padding: 16 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: '#E2E8F0', marginBottom: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
              <Layers style={{ width: 14, height: 14, color: ACCENT }} /> 因子组合配置
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {comboFactors.map((f, i) => (
                <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <select value={f.name} onChange={e => setComboFactors(prev => prev.map((p, j) => j === i ? { ...p, name: e.target.value } : p))}
                    style={{ padding: '6px 10px', background: '#0B0F1A', border: '1px solid #1E293B', borderRadius: 6, color: '#E2E8F0', fontSize: 12, width: 200, outline: 'none' }}>
                    {factorList.length > 0 ? factorList.map(fn => <option key={fn} value={fn}>{fn}</option>) : <option value={f.name}>{f.name}</option>}
                  </select>
                  <input type="number" step="0.05" value={f.weight} onChange={e => setComboFactors(prev => prev.map((p, j) => j === i ? { ...p, weight: Number(e.target.value) } : p))}
                    style={{ padding: '6px 10px', background: '#0B0F1A', border: '1px solid #1E293B', borderRadius: 6, color: '#E2E8F0', fontSize: 12, width: 70, outline: 'none', fontFamily: 'JetBrains Mono, monospace' }} />
                  <span style={{ fontSize: 12, color: '#475569', width: 40 }}>{(f.weight / totalWeight * 100).toFixed(0)}%</span>
                  <button onClick={() => setComboFactors(prev => prev.filter((_, j) => j !== i))} disabled={comboFactors.length <= 1}
                    style={{ padding: '4px 8px', background: '#7F1D1D', border: 'none', borderRadius: 4, color: '#FECACA', fontSize: 12, cursor: comboFactors.length <= 1 ? 'not-allowed' : 'pointer', opacity: comboFactors.length <= 1 ? 0.4 : 1 }}>删除</button>
                </div>
              ))}
            </div>
            <button onClick={() => setComboFactors(prev => [...prev, { name: factorList[0] || 'ret_5', weight: 0.1 }])}
              style={{ marginTop: 8, padding: '6px 12px', background: '#1E293B', border: '1px solid #334155', borderRadius: 6, color: '#94A3B8', fontSize: 11, cursor: 'pointer' }}>+ 添加因子</button>
          </div>

          {/* 股票池+持有期 */}
          <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, padding: 16, display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <div style={{ flex: 1, minWidth: 250 }}>
              <div style={{ fontSize: 12, color: '#475569', marginBottom: 5 }}>股票列表 (逗号分隔)</div>
              <input value={comboCodes} onChange={e => setComboCodes(e.target.value)}
                style={{ padding: '8px 12px', background: '#0B0F1A', border: '1px solid #1E293B', borderRadius: 8, color: '#E2E8F0', fontSize: 12, width: '100%', outline: 'none', fontFamily: 'JetBrains Mono, monospace' }}
                onFocus={e => (e.target.style.borderColor = ACCENT)} onBlur={e => (e.target.style.borderColor = '#1E293B')} />
            </div>
            <div>
              <div style={{ fontSize: 12, color: '#475569', marginBottom: 5 }}>持有天数</div>
              <input type="number" value={comboHold} onChange={e => setComboHold(Number(e.target.value))}
                style={{ padding: '8px 12px', background: '#0B0F1A', border: '1px solid #1E293B', borderRadius: 8, color: '#E2E8F0', fontSize: 12, width: 70, outline: 'none' }} />
            </div>
            <button onClick={runCombo} disabled={comboLoading}
              style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 18px', background: ACCENT, border: 'none', borderRadius: 8, color: '#0B0F1A', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>
              {comboLoading ? <Loader2 style={{ width: 13, height: 13, animation: 'spin 1s linear infinite' }} /> : <Zap style={{ width: 13, height: 13 }} />}
              组合回测
            </button>
          </div>

          {comboError && <div style={{ padding: '10px 14px', background: '#EF444414', border: '1px solid #EF444433', borderRadius: 8, fontSize: 12, color: '#F87171' }}>
            <AlertTriangle style={{ width: 12, height: 12, display: 'inline', marginRight: 6 }} />{comboError}
          </div>}

          {/* 组合回测结果 */}
          {comboResult && (() => {
            const s = comboResult?.backtest?.summary;
            const ps = comboResult?.backtest?.per_stock || {};
            const details = comboResult?.backtest?.details || [];
            const comboSnapshots: any[] = comboResult?.backtest?.daily_snapshots || [];
            return (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                {comboResult.elapsed && <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Clock style={{ width: 12, height: 12, color: '#475569' }} />
                  <span style={{ fontSize: 11, color: '#475569' }}>耗时 {comboResult.elapsed.toFixed(1)} 秒 · 因子：{comboFactors.map(f => f.name).join(' + ')}</span>
                </div>}
                {s && (
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
                    <MetricCard label="总收益率" value={`${(s.total_return_pct ?? 0) >= 0 ? '+' : ''}${(s.total_return_pct ?? 0).toFixed(2)}%`} color={(s.total_return_pct ?? 0) >= 0 ? '#4ADE80' : '#F87171'} />
                    <MetricCard label="平均收益" value={`${(s.avg_return_pct ?? 0).toFixed(2)}%`} color={(s.avg_return_pct ?? 0) >= 0 ? '#4ADE80' : '#F87171'} />
                    <MetricCard label="胜率" value={`${(s.win_rate_pct ?? 0).toFixed(1)}%`} color="#60A5FA" />
                    <MetricCard label="交易次数" value={String(s.total_trades ?? 0)} color="#94A3B8" />
                  </div>
                )}
                {comboSnapshots.length > 0 && <EquityCurve snapshots={comboSnapshots} />}
                {Object.keys(ps).length > 0 && (
                  <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, overflow: 'hidden' }}>
                    <div style={{ padding: '10px 16px', background: '#0B0F1A', borderBottom: '1px solid #1E293B', fontSize: 12, fontWeight: 600, color: '#94A3B8' }}>个股表现</div>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                      <thead><tr style={{ borderBottom: '1px solid #1E293B' }}>
                        {['代码','交易次数','总收益','胜率','均笔收益'].map((h,ci) => <th key={h} style={{ padding: '9px 14px', textAlign: ci>=1?'right':'left', fontSize: 12, fontWeight: 600, color: '#475569' }}>{h}</th>)}
                      </tr></thead>
                      <tbody>
                        {Object.entries(ps).map(([code, p]: [string, any]) => (
                          <tr key={code} style={{ borderBottom: '1px solid #1E293B44' }}>
                            <td style={{ padding: '9px 14px', fontFamily: 'JetBrains Mono, monospace', color: ACCENT, fontSize: 12 }}>{code}</td>
                            <td style={{ padding: '9px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: '#94A3B8', fontSize: 11 }}>{p.trade_count}</td>
                            <td style={{ padding: '9px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: p.total_return_pct >= 0 ? '#4ADE80' : '#F87171', fontWeight: 600, fontSize: 11 }}>{p.total_return_pct >= 0 ? '+' : ''}{p.total_return_pct.toFixed(2)}%</td>
                            <td style={{ padding: '9px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: '#94A3B8', fontSize: 11 }}>{p.win_rate_pct.toFixed(1)}%</td>
                            <td style={{ padding: '9px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: '#94A3B8', fontSize: 11 }}>{(p.avg_win_pct||0) >= 0 ? '+' : ''}{(p.avg_win_pct||0).toFixed(2)}%</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                {details.length > 0 && (
                  <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, overflow: 'hidden' }}>
                    <div style={{ padding: '10px 16px', background: '#0B0F1A', borderBottom: '1px solid #1E293B', fontSize: 12, fontWeight: 600, color: '#94A3B8' }}>最近交易 (共 {details.length} 笔)</div>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                      <thead><tr style={{ borderBottom: '1px solid #1E293B' }}>
                        {['入场日期','代码','入场价','出场价','天数','收益率'].map((h,ci) => <th key={h} style={{ padding: '9px 14px', textAlign: ci>=2?'right':'left', fontSize: 12, fontWeight: 600, color: '#475569' }}>{h}</th>)}
                      </tr></thead>
                      <tbody>
                        {details.slice(0, 40).map((t: any, i: number) => (
                          <tr key={i} style={{ borderBottom: '1px solid #1E293B44' }}>
                            <td style={{ padding: '8px 14px', color: '#475569', fontSize: 11, fontFamily: 'JetBrains Mono, monospace' }}>{String(t.entry_date || '').slice(0, 10)}</td>
                            <td style={{ padding: '8px 14px', fontFamily: 'JetBrains Mono, monospace', color: ACCENT, fontSize: 11 }}>{t.code}</td>
                            <td style={{ padding: '8px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: '#94A3B8', fontSize: 11 }}>{Number(t.entry_price||0).toFixed(2)}</td>
                            <td style={{ padding: '8px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: '#94A3B8', fontSize: 11 }}>{Number(t.exit_price||0).toFixed(2)}</td>
                            <td style={{ padding: '8px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: '#475569', fontSize: 11 }}>{t.holding_days}</td>
                            <td style={{ padding: '8px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: (t.pnl_pct||0) >= 0 ? '#4ADE80' : '#F87171', fontWeight: 600, fontSize: 11 }}>{(t.pnl_pct||0) >= 0 ? '+' : ''}{(t.pnl_pct||0).toFixed(2)}%</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            );
          })()}

          {!comboResult && !comboLoading && (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '60px 0', color: '#334155' }}>
              <Layers style={{ width: 48, height: 48, marginBottom: 12, opacity: 0.3 }} />
              <div style={{ fontSize: 14, fontWeight: 600, color: '#475569' }}>配置因子组合后运行回测</div>
              <div style={{ fontSize: 12, color: '#334155', marginTop: 4 }}>回测耗时约 30-90 秒</div>
            </div>
          )}
          {comboLoading && (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '60px 0', color: '#475569' }}>
              <Loader2 style={{ width: 36, height: 36, color: ACCENT, animation: 'spin 1s linear infinite', marginBottom: 12 }} />
              <div style={{ fontSize: 14, color: '#64748B' }}>多因子组合回测运行中...</div>
            </div>
          )}
        </div>
      )}

      {/* ── 策略列表 ── */}
      {tab === 'list' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {meta ? Object.entries(meta as Record<string, any>).map(([id, s]) => (
            <div key={id} style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, overflow: 'hidden' }}>
              <button
                onClick={() => setExpanded(p => ({ ...p, [id]: !p[id] }))}
                style={{ width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 16px', background: 'transparent', border: 'none', cursor: 'pointer', textAlign: 'left' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <ChevronRight style={{ width: 14, height: 14, color: '#475569', transform: expanded[id] ? 'rotate(90deg)' : 'none', transition: 'transform 150ms' }} />
                  <span style={{ fontSize: 14, fontWeight: 600, color: '#E2E8F0' }}>{s.name}</span>
                  <span style={{ fontSize: 12, fontFamily: 'JetBrains Mono, monospace', color: '#334155', background: '#1E293B', padding: '2px 8px', borderRadius: 4 }}>{id}</span>
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
              <div style={{ fontSize: 12, color: '#475569', marginBottom: 5 }}>策略</div>
              <select value={selected} onChange={e => setSelected(e.target.value)}
                style={{ padding: '8px 12px', background: '#0B0F1A', border: '1px solid #1E293B', borderRadius: 8, color: '#E2E8F0', fontSize: 13, outline: 'none', cursor: 'pointer' }}>
                {meta && Object.entries(meta as Record<string, any>).map(([id, s]) => <option key={id} value={id}>{s.name}</option>)}
              </select>
            </div>
            <div style={{ flex: 1, minWidth: 200 }}>
              <div style={{ fontSize: 12, color: '#475569', marginBottom: 5 }}>股票列表</div>
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
                  <div style={{ fontSize: 12, color: '#475569', marginBottom: 4 }}>{p.name}</div>
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

              {/* 净值曲线 / 回撤图 (纯 SVG, 零依赖) */}
              {snapshots.length > 0 && <EquityCurve snapshots={snapshots} />}

              {/* Per-stock */}
              {Object.keys(perStock).length > 0 && (
                <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, overflow: 'hidden' }}>
                  <div style={{ padding: '10px 16px', background: '#0B0F1A', borderBottom: '1px solid #1E293B', fontSize: 12, fontWeight: 600, color: '#94A3B8' }}>个股表现</div>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                    <thead><tr style={{ borderBottom: '1px solid #1E293B' }}>
                      {['代码','交易次数','总收益','胜率','均笔收益'].map((h,i) => <th key={h} style={{ padding: '9px 14px', textAlign: i>=1?'right':'left', fontSize: 12, fontWeight: 600, color: '#475569' }}>{h}</th>)}
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
                      {['入场日期','代码','入场价','出场价','天数','收益率'].map((h,i) => <th key={h} style={{ padding: '9px 14px', textAlign: i>=2?'right':'left', fontSize: 12, fontWeight: 600, color: '#475569' }}>{h}</th>)}
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

      {tab === 'paper' && <PaperStrategyConfig onDirtyChange={setPaperDirty} />}

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
};

export default StrategyPanel;
