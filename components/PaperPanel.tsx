import React, { useState, useEffect, useCallback } from 'react';
import { Bot, Zap, RefreshCw, Settings, Activity, AlertTriangle, Loader2, Clock, TrendingUp, TrendingDown, FileText, AlertCircle, Terminal } from 'lucide-react';

const API_BASE = (import.meta as any).env?.VITE_API_BASE || '';
const API_TOKEN = (import.meta as any).env?.VITE_ALPHACOUNCIL_API_TOKEN || '';
const jsonHeaders = () => ({ 'Content-Type': 'application/json', ...(API_TOKEN ? { 'X-AlphaCouncil-Token': API_TOKEN } : {}) });
const ACCENT = '#A78BFA';

async function api(body: any) {
  const r = await fetch(`${API_BASE}/api/paper`, {
    method: 'POST', headers: jsonHeaders(),
    body: JSON.stringify(body),
  });
  const d = await r.json();
  if (!d.success) throw new Error(d.error || '请求失败');
  return d.data;
}

interface StrategyMeta { [key: string]: { name: string; desc: string; params: { name: string; type: string; default: any; desc: string }[] }; }

const Card: React.FC<{ title?: string; children: React.ReactNode; right?: React.ReactNode }> = ({ title, children, right }) => (
  <div style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, overflow: 'hidden' }}>
    {title && (
      <div style={{ padding: '12px 16px', background: '#0B0F1A', borderBottom: '1px solid #1E293B', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Settings style={{ width: 14, height: 14, color: '#475569' }} />
          <span style={{ fontSize: 12, fontWeight: 600, color: '#94A3B8' }}>{title}</span>
        </div>
        {right}
      </div>
    )}
    {children}
  </div>
);

const Label: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div style={{ fontSize: 10, color: '#475569', marginBottom: 5, letterSpacing: 0.3 }}>{children}</div>
);

const inputStyle: React.CSSProperties = {
  padding: '8px 12px', background: '#0B0F1A', border: '1px solid #1E293B', borderRadius: 8,
  color: '#E2E8F0', fontSize: 13, fontFamily: 'JetBrains Mono, monospace', outline: 'none',
};

// ─── Token 使用量统计展示 ────────────────────────────────
const SCENE_LABELS: Record<string, string> = {
  test: '测试', operator: 'AI操作员', data: '数据层', factor: '因子工厂',
  strategy: '策略工厂', execution: '执行层', risk: '风控',
  report: '日报', alert: '告警解读', paper: '模拟盘', unknown: '其他',
};

const PROVIDER_LABELS: Record<string, string> = {
  glm: 'GLM', deepseek: 'DeepSeek', qwen: 'Qwen', gemini: 'Gemini', unknown: '其他',
};

const fmt = (n: number | undefined) => (n ?? 0).toLocaleString();

const TokenUsageStats: React.FC<{ usage: any; loading: boolean; onRefresh: () => void; onReset: () => void }> = ({ usage, loading, onRefresh, onReset }) => {
  const total = usage?.total?.totals;
  const today = usage?.today?.totals;
  const providers = usage?.total?.providers || {};
  const scenes = usage?.total?.scenes || {};
  const recent = usage?.recent || [];
  const last = usage?.last;

  // 按 token 降序排
  const provList = Object.entries(providers).sort((a: any, b: any) => b[1].total_tokens - a[1].total_tokens);
  const sceneList = Object.entries(scenes).sort((a: any, b: any) => b[1].total_tokens - a[1].total_tokens);
  const maxProvTokens = Math.max(1, ...provList.map(([, v]: any) => v.total_tokens));

  return (
    <div style={{ marginTop: 10, padding: 10, background: '#0B0F1A', border: '1px solid #312E81', borderRadius: 6 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 11, fontWeight: 600, color: '#A78BFA' }}>📊 Token 使用量</span>
          {loading && <Loader2 style={{ width: 10, height: 10, color: '#7C3AED', animation: 'spin 1s linear infinite' }} />}
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <button onClick={onRefresh} title="刷新"
            style={{ padding: '2px 8px', background: 'transparent', border: '1px solid #4C1D95', borderRadius: 4, color: '#A78BFA', fontSize: 10, cursor: 'pointer' }}>
            刷新
          </button>
          <button onClick={onReset} title="清空统计"
            style={{ padding: '2px 8px', background: 'transparent', border: '1px solid #4C1D95', borderRadius: 4, color: '#F87171', fontSize: 10, cursor: 'pointer' }}>
            重置
          </button>
        </div>
      </div>

      {/* 今日 / 累计 概览 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 10 }}>
        <div style={{ padding: 8, background: '#1E1B4B', borderRadius: 5, border: '1px solid #312E81' }}>
          <div style={{ fontSize: 9, color: '#7C3AED', marginBottom: 3 }}>今日</div>
          <div style={{ fontSize: 15, fontWeight: 700, color: '#DDD6FE', fontFamily: 'JetBrains Mono, monospace' }}>{fmt(today?.total_tokens)}</div>
          <div style={{ fontSize: 9, color: '#6D5FBC' }}>{today?.calls || 0} 次调用 · ↑{fmt(today?.prompt_tokens)} ↓{fmt(today?.completion_tokens)}</div>
        </div>
        <div style={{ padding: 8, background: '#1E1B4B', borderRadius: 5, border: '1px solid #312E81' }}>
          <div style={{ fontSize: 9, color: '#7C3AED', marginBottom: 3 }}>累计</div>
          <div style={{ fontSize: 15, fontWeight: 700, color: '#DDD6FE', fontFamily: 'JetBrains Mono, monospace' }}>{fmt(total?.total_tokens)}</div>
          <div style={{ fontSize: 9, color: '#6D5FBC' }}>{total?.calls || 0} 次调用 · ↑{fmt(total?.prompt_tokens)} ↓{fmt(total?.completion_tokens)}</div>
        </div>
      </div>

      {/* 按供应商分类 (带进度条) */}
      {provList.length > 0 && (
        <div style={{ marginBottom: 8 }}>
          <div style={{ fontSize: 9, color: '#7C3AED', marginBottom: 4 }}>按模型供应商</div>
          {provList.map(([p, v]: any) => (
            <div key={p} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
              <span style={{ fontSize: 10, color: '#C4B5FD', minWidth: 70 }}>{PROVIDER_LABELS[p] || p}</span>
              <div style={{ flex: 1, height: 6, background: '#0B0F1A', borderRadius: 3, overflow: 'hidden' }}>
                <div style={{ width: `${(v.total_tokens / maxProvTokens) * 100}%`, height: '100%', background: 'linear-gradient(90deg, #7C3AED, #A78BFA)', borderRadius: 3 }} />
              </div>
              <span style={{ fontSize: 10, color: '#94A3B8', fontFamily: 'JetBrains Mono, monospace', minWidth: 55, textAlign: 'right' }}>{fmt(v.total_tokens)}</span>
              <span style={{ fontSize: 9, color: '#475569', minWidth: 28, textAlign: 'right' }}>{v.calls}次</span>
            </div>
          ))}
        </div>
      )}

      {/* 按场景分类 */}
      {sceneList.length > 0 && (
        <div style={{ marginBottom: 8 }}>
          <div style={{ fontSize: 9, color: '#7C3AED', marginBottom: 4 }}>按调用场景</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {sceneList.map(([s, v]: any) => (
              <span key={s} style={{ fontSize: 9, padding: '2px 6px', background: '#312E8155', border: '1px solid #312E8155', borderRadius: 8, color: '#C4B5FD' }}>
                {SCENE_LABELS[s] || s}: <b style={{ color: '#DDD6FE' }}>{fmt(v.total_tokens)}</b> ({v.calls})
              </span>
            ))}
          </div>
        </div>
      )}

      {/* 最近一次调用 */}
      {last && (
        <div style={{ fontSize: 9, color: '#6D5FBC', borderTop: '1px solid #312E8155', paddingTop: 6 }}>
          最近: {last.ts?.slice(11) || '--'} · {PROVIDER_LABELS[last.provider] || last.provider}/{SCENE_LABELS[last.scene] || last.scene}
          {' '}→ <span style={{ color: '#DDD6FE' }}>↑{fmt(last.prompt_tokens)} ↓{fmt(last.completion_tokens)} = {fmt(last.total_tokens)}</span>
        </div>
      )}

      {/* 空状态 */}
      {!total?.calls && !loading && (
        <div style={{ fontSize: 10, color: '#475569', textAlign: 'center', padding: '8px 0' }}>
          暂无 token 使用记录 · 点击「测试连接」或运行 AI 任务后将自动统计
        </div>
      )}
    </div>
  );
};

const PaperPanel: React.FC = () => {
  const [meta, setMeta] = useState<StrategyMeta | null>(null);
  const [status, setStatus] = useState<any>(null);
  const [logs, setLogs] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');
  const [lastRunResult, setLastRunResult] = useState<any>(null);
  const [report, setReport] = useState<any>(null);
  const [reportLoading, setReportLoading] = useState(false);
  // 实时运行进度
  const [progressEvents, setProgressEvents] = useState<any[]>([]);
  const [runInProgress, setRunInProgress] = useState(false);
  // 自主调度器状态 (判断交易由谁触发)
  const [schedActive, setSchedActive] = useState(false);
  // 选股流 (ai_all_status 聚合: screen)
  const [aiAll, setAiAll] = useState<any>(null);
  const [screenLoading, setScreenLoading] = useState(false);

  // 本地编辑态 (独立于后端 cfg, 保存时才提交)
  const [strategy, setStrategy] = useState('ma_cross');
  const [params, setParams] = useState<Record<string, any>>({});
  const [universe, setUniverse] = useState('600519,000858,600036,000333,601318');
  const [posPct, setPosPct] = useState('0.2');
  const [maxPos, setMaxPos] = useState('5');
  const [tradeTime, setTradeTime] = useState('15:05');
  // LLM 配置
  const [llmEnabled, setLlmEnabled] = useState(false);
  const [llmProvider, setLlmProvider] = useState('glm');
  const [llmMode, setLlmMode] = useState('off');
  const [llmTestResult, setLlmTestResult] = useState<string | null>(null);
  const [llmTesting, setLlmTesting] = useState(false);
  // LLM Token 使用量统计
  const [llmUsage, setLlmUsage] = useState<any>(null);
  const [llmUsageLoading, setLlmUsageLoading] = useState(false);

  // 拉策略元信息 (一次性)
  useEffect(() => {
    fetch(`${API_BASE}/api/strategy`, { method: 'POST', headers: jsonHeaders(), body: JSON.stringify({ action: 'meta' }) })
      .then(r => r.json())
      .then(j => { if (j.success) setMeta(j.data); })
      .catch(() => {});
  }, []);

  const refresh = useCallback(async () => {
    try {
      const d = await api({ action: 'status' });
      setStatus(d.status);
      setRunning(d.daemon?.running || false);
      if (d.config) {
        setStrategy(d.config.strategy_name || 'ma_cross');
        setParams(d.config.strategy_params || {});
        setUniverse((d.config.universe || []).join(','));
        setPosPct(String(d.config.position_size_pct ?? 0.2));
        setMaxPos(String(d.config.max_positions ?? 5));
        setTradeTime(d.config.trade_time || '15:05');
        const llm = d.config.llm || {};
        setLlmEnabled(llm.enabled ?? false);
        setLlmProvider(llm.provider || 'glm');
        setLlmMode(llm.mode || 'off');
      }
      if (d.status?.last_result) setLastRunResult(d.status.last_result);
    } catch (e: any) { setError(e.message); }
  }, []);

  const refreshLog = useCallback(async () => {
    try {
      const d = await api({ action: 'log', limit: 30 });
      setLogs(d || []);
    } catch { /* 静默 */ }
  }, []);

  // 拉取/生成最新日报 (含基准对比)
  const fetchReport = useCallback(async (generate: boolean = false) => {
    setReportLoading(true);
    try {
      const action = generate ? 'generate_report' : 'report';
      const r = await fetch(`${API_BASE}/api/paper`, {
        method: 'POST', headers: jsonHeaders(),
        body: JSON.stringify({ action }),
      });
      const j = await r.json();
      if (j.success && j.data) setReport(j.data);
      else if (generate && !j.success) setError(j.error || '生成日报失败');
    } catch (e: any) { /* 静默, 日报为可选 */ }
    setReportLoading(false);
  }, []);

  // 拉取自主调度器状态 (判断交易由调度器驱动还是模拟盘独立)
  const fetchSchedStatus = useCallback(async () => {
    try {
      const d = await api({ action: 'ai_scheduler_status' });
      setSchedActive(!!(d?.daemon_running || d?.config?.enabled));
    } catch { /* 静默 */ }
  }, []);

  // 拉选取股流 (ai_all_status 聚合: screen)
  const fetchAiAll = useCallback(async () => {
    try {
      const d = await api({ action: 'ai_all_status' });
      setAiAll(d || null);
    } catch { /* 静默 */ }
  }, []);

  // 手动触发全市场选股
  const runScreen = useCallback(async () => {
    setScreenLoading(true); setError('');
    try {
      await api({ action: 'ai_screen_run', provider: llmProvider, top_n: 20 });
      await fetchAiAll();
    } catch (e: any) { setError(e.message); }
    setScreenLoading(false);
  }, [llmProvider, fetchAiAll]);

  useEffect(() => { refresh(); refreshLog(); fetchReport(false); fetchSchedStatus(); fetchAiAll(); }, [refresh, refreshLog, fetchReport, fetchSchedStatus, fetchAiAll]);
  // 每 30 秒刷新调度器 + 选股流状态
  useEffect(() => {
    const t = setInterval(() => { fetchSchedStatus(); fetchAiAll(); }, 30000);
    return () => clearInterval(t);
  }, [fetchSchedStatus]);
  // 运行中时高频轮询日志
  useEffect(() => {
    if (!running) return;
    const t = setInterval(refreshLog, 3000);
    return () => clearInterval(t);
  }, [running, refreshLog]);

  // 切策略时初始化参数默认值
  useEffect(() => {
    if (!meta || !meta[strategy]) return;
    const defaults: Record<string, any> = {};
    meta[strategy].params.forEach((p) => { defaults[p.name] = params[p.name] ?? p.default; });
    setParams(defaults);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [strategy, meta]);

  const saveConfig = useCallback(async () => {
    setLoading(true); setError('');
    try {
      // 先读后端当前配置, 用后端值兜底前端未编辑的字段
      // 避免前端默认值覆盖后端已有配置
      let backendCfg: any = null;
      try {
        const st = await api({ action: 'status' });
        backendCfg = st.config;
      } catch { /* 静默 */ }

      const newCfg = {
        strategy_name: strategy || backendCfg?.strategy_name || 'ma_cross',
        strategy_params: Object.keys(params).length > 0 ? params : (backendCfg?.strategy_params || {}),
        universe: universe.split(',').map(s => s.trim()).filter(Boolean),
        position_size_pct: parseFloat(posPct) || backendCfg?.position_size_pct || 0.2,
        max_positions: parseInt(maxPos) || backendCfg?.max_positions || 5,
        trade_time: tradeTime || backendCfg?.trade_time || '15:05',
        enabled: running,
        llm: {
          enabled: llmEnabled,
          provider: llmProvider,
          mode: llmEnabled ? llmMode : 'off',
          timeout: backendCfg?.llm?.timeout || 45,
          max_new_positions: backendCfg?.llm?.max_new_positions || 3,
          confidence_threshold: backendCfg?.llm?.confidence_threshold ?? 0.4,
          interpret_alerts: backendCfg?.llm?.interpret_alerts ?? true,
        },
      };
      await api({ action: 'set_config', config: newCfg });
      await refresh();
    } catch (e: any) { setError(e.message); }
    setLoading(false);
  }, [strategy, params, universe, posPct, maxPos, tradeTime, running, llmEnabled, llmProvider, llmMode, refresh]);

  // LLM 配置即时持久化 (只写 llm 子配置, 后端深度合并不影响其他字段)
  const persistLlm = useCallback(async (overrides: Record<string, any> = {}) => {
    // 先读后端当前 llm 配置作为兜底, 避免硬编码覆盖
    let backendLlm: any = {};
    try {
      const st = await api({ action: 'status' });
      backendLlm = st.config?.llm || {};
    } catch { /* 静默 */ }
    const llm = {
      enabled: overrides.enabled ?? llmEnabled,
      provider: overrides.provider ?? llmProvider,
      mode: overrides.mode ?? llmMode,
      timeout: backendLlm.timeout ?? 45,
      max_new_positions: backendLlm.max_new_positions ?? 3,
      confidence_threshold: backendLlm.confidence_threshold ?? 0.4,
      interpret_alerts: backendLlm.interpret_alerts ?? true,
    };
    if (!llm.enabled) llm.mode = 'off';
    try {
      await api({ action: 'set_config', config: { llm } });
    } catch { /* 静默, 用户下次保存配置会兜底 */ }
  }, [llmEnabled, llmProvider, llmMode]);

  // LLM 连接测试
  const testLlm = useCallback(async () => {
    setLlmTesting(true); setLlmTestResult(null);
    try {
      const r = await fetch(`${API_BASE}/api/paper`, {
        method: 'POST', headers: jsonHeaders(),
        body: JSON.stringify({ action: 'test_llm', provider: llmProvider }),
      });
      const j = await r.json();
      if (j.success) {
        const u = j.data?.usage || {};
        const tk = u.total_tokens ? ` · ${u.total_tokens} tokens` : '';
        setLlmTestResult(`✅ ${j.data?.label || llmProvider}: ${j.data?.text || '连接成功'}${tk}`);
        fetchLlmUsage();  // 刷新统计 (本次测试已计入)
      } else {
        setLlmTestResult(`❌ ${j.data?.error || j.error || '测试失败'}`);
      }
    } catch (e: any) { setLlmTestResult(`❌ ${e.message}`); }
    setLlmTesting(false);
  }, [llmProvider]);

  // 拉取 LLM Token 使用量统计
  const fetchLlmUsage = useCallback(async () => {
    setLlmUsageLoading(true);
    try {
      const d = await api({ action: 'llm_usage', days: 7 });
      setLlmUsage(d || null);
    } catch { /* 静默 */ }
    setLlmUsageLoading(false);
  }, []);

  // 重置 Token 统计
  const resetLlmUsage = useCallback(async () => {
    if (!confirm('确定清空所有 Token 使用量统计?此操作不可恢复。')) return;
    try {
      await api({ action: 'llm_usage_reset' });
      await fetchLlmUsage();
    } catch (e: any) { setError(e.message); }
  }, [fetchLlmUsage]);

  // 初次加载 + 每 60 秒刷新一次 token 统计
  useEffect(() => {
    fetchLlmUsage();
    const t = setInterval(fetchLlmUsage, 60000);
    return () => clearInterval(t);
  }, [fetchLlmUsage]);

  // 轮询进度 (运行中时每 2 秒)
  const pollProgress = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/api/paper`, {
        method: 'POST', headers: jsonHeaders(),
        body: JSON.stringify({ action: 'progress' }),
      });
      const j = await r.json();
      if (!j.success) return;
      const data = j.data || {};
      setProgressEvents(data.events || []);
      const stillRunning = data.running;
      setRunInProgress(stillRunning);

      // 运行结束: 刷新最终结果
      if (!stillRunning && data.result) {
        setLastRunResult(data.result);
        await refresh(); await refreshLog(); await fetchReport(true);
      }
    } catch { /* 静默 */ }
  }, [refresh, refreshLog, fetchReport]);

  // 运行中时高频轮询进度
  useEffect(() => {
    if (!runInProgress) return;
    const t = setInterval(pollProgress, 2000);
    return () => clearInterval(t);
  }, [runInProgress, pollProgress]);

  const runNow = useCallback(async () => {
    setLoading(true); setError(''); setLastRunResult(null);
    setProgressEvents([]); setRunInProgress(true);
    try {
      await saveConfig();  // 用当前编辑态跑
      // 非阻塞启动 — 立即返回, 靠轮询看进度
      await api({ action: 'run_now' });
      // 立即开始轮询
      setTimeout(pollProgress, 500);
    } catch (e: any) { setError(e.message); setRunInProgress(false); }
    setLoading(false);
  }, [saveConfig, pollProgress]);

  const fmtTime = (s: string | null) => s ? String(s).slice(0, 19).replace('T', ' ') : '-';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 22 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ width: 40, height: 40, borderRadius: 10, background: `${ACCENT}22`, border: `1px solid ${ACCENT}44`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Bot style={{ width: 20, height: 20, color: ACCENT }} />
          </div>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, color: '#F1F5F9' }}>模拟盘自动交易</div>
            <div style={{ fontSize: 11, color: '#64748B' }}>每日收盘自动跑策略 · 信号转订单 · 与交易执行共享账户</div>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, background: '#111827', border: '1px solid #1E293B', borderRadius: 20, padding: '4px 12px' }}>
            <div style={{ width: 6, height: 6, borderRadius: '50%', background: running ? '#4ADE80' : '#475569', boxShadow: running ? '0 0 6px #4ADE80' : 'none' }} />
            <span style={{ fontSize: 11, color: '#64748B' }}>{running ? '调度运行中' : '已停止'}</span>
          </div>
          <button onClick={() => { refresh(); refreshLog(); fetchReport(false); }}
            style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '7px 12px', background: '#111827', border: '1px solid #1E293B', borderRadius: 8, color: '#64748B', fontSize: 12, cursor: 'pointer' }}>
            <RefreshCw style={{ width: 12, height: 12 }} />刷新
          </button>
        </div>
      </div>

      {error && <div style={{ padding: '10px 14px', background: '#EF444414', border: '1px solid #EF444433', borderRadius: 8, fontSize: 12, color: '#F87171' }}>
        <AlertTriangle style={{ width: 12, height: 12, display: 'inline', marginRight: 6 }} />{error}
      </div>}

      {/* 状态摘要 */}
      {status && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12 }}>
          {[
            { label: '调度状态', value: running ? '运行中' : '已停止', color: running ? '#4ADE80' : '#64748B', icon: Activity },
            { label: '上次运行', value: fmtTime(status.last_run), color: '#F1F5F9', icon: Clock },
            { label: '上次下单数', value: String(status.last_result?.order_count ?? 0), color: '#60A5FA', icon: Zap },
            { label: '下次运行', value: status.next_run || '-', color: '#94A3B8', icon: Clock },
            { label: '触发来源', value: status.last_result?.trigger_source || '-', color: '#A78BFA', icon: Terminal },
          ].map(m => {
            const Icon = m.icon;
            return (
              <div key={m.label} style={{ background: '#111827', border: '1px solid #1E293B', borderRadius: 12, padding: '14px 16px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                  <Icon style={{ width: 11, height: 11, color: '#475569' }} />
                  <span style={{ fontSize: 10, color: '#475569', letterSpacing: 0.5 }}>{m.label}</span>
                </div>
                <div style={{ fontSize: 15, fontWeight: 700, fontFamily: 'JetBrains Mono, monospace', color: m.color }}>{m.value}</div>
              </div>
            );
          })}
        </div>
      )}

      {/* ① 选股流可视化 — 全市场 AI 轮询筛选结果 */}
      <Card title="① 选股流 · 全市场 AI 轮询筛选" right={
        <button onClick={runScreen} disabled={screenLoading}
          style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '4px 10px', background: '#1E3A8A', border: '1px solid #3B82F6', borderRadius: 6, color: '#BFDBFE', fontSize: 10, cursor: 'pointer' }}>
          {screenLoading ? <Loader2 style={{ width: 10, height: 10, animation: 'spin 1s linear infinite' }} /> : <Activity style={{ width: 10, height: 10 }} />}
          手动选股
        </button>
      }>
        <div style={{ padding: 16 }}>
          {(() => {
            const screen = aiAll?.screen;
            if (!screen || !screen.top || screen.top.length === 0) {
              return <div style={{ fontSize: 12, color: '#475569', textAlign: 'center', padding: 20 }}>
                暂无选股结果 {screen?.stats && `(全市场 ${screen.n_universe || 5207} 只, 上次过滤: ST {screen.stats.filtered_st||0} / 涨停 {screen.stats.filtered_limit||0} / 停牌 {screen.stats.filtered_halt||0} / 仙股 {screen.stats.filtered_penny||0})`}
              </div>;
            }
            return (
              <>
                <div style={{ display: 'flex', gap: 12, marginBottom: 12, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 10, color: '#64748B', background: '#0B0F1A', padding: '3px 10px', borderRadius: 10, border: '1px solid #1E293B' }}>
                    全市场 {screen.n_universe || 5207} 只
                  </span>
                  <span style={{ fontSize: 10, color: '#10B981', background: '#064E3B', padding: '3px 10px', borderRadius: 10 }}>
                    AI 复核通过 {screen.top.length} 只
                  </span>
                  {screen.stats && (
                    <span style={{ fontSize: 10, color: '#64748B', background: '#0B0F1A', padding: '3px 10px', borderRadius: 10, border: '1px solid #1E293B' }}>
                      剔除: ST {screen.stats.filtered_st||0} / 涨停 {screen.stats.filtered_limit||0} / 停牌 {screen.stats.filtered_halt||0} / 仙股 {screen.stats.filtered_penny||0} / 低置信 {screen.stats.filtered_low_conf||0}
                    </span>
                  )}
                  {screen.screened_at && <span style={{ fontSize: 10, color: '#475569' }}>选股时间: {screen.screened_at}</span>}
                </div>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                    <thead>
                      <tr style={{ background: '#0B0F1A' }}>
                        {['代码', '打分', '现价', '近5日%', 'AI置信度', 'AI 理由'].map(h => (
                          <th key={h} style={{ padding: '8px 10px', textAlign: 'left', fontSize: 10, color: '#475569', fontWeight: 600, borderBottom: '1px solid #1E293B' }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {screen.top.map((t: any, i: number) => {
                        const conf = t.confidence;
                        const confColor = conf === null || conf === undefined ? '#64748B' : conf >= 0.7 ? '#10B981' : conf >= 0.5 ? '#F59E0B' : '#EF4444';
                        return (
                          <tr key={t.code} style={{ borderBottom: '1px solid #1E293B' }}>
                            <td style={{ padding: '7px 10px', fontFamily: 'JetBrains Mono, monospace', fontWeight: 600, color: '#E2E8F0' }}>
                              <span style={{ color: '#475569', marginRight: 6 }}>#{i + 1}</span>{t.code}
                            </td>
                            <td style={{ padding: '7px 10px', fontFamily: 'JetBrains Mono, monospace', color: '#A78BFA', fontWeight: 600 }}>{(t.score || 0).toFixed(2)}</td>
                            <td style={{ padding: '7px 10px', fontFamily: 'JetBrains Mono, monospace', color: '#E2E8F0' }}>{t.close ? t.close.toFixed(2) : '-'}</td>
                            <td style={{ padding: '7px 10px', fontFamily: 'JetBrains Mono, monospace', color: (t.chg5 || 0) >= 0 ? '#EF4444' : '#22C55E' }}>
                              {t.chg5 !== null && t.chg5 !== undefined ? `${t.chg5 >= 0 ? '+' : ''}${t.chg5}%` : '-'}
                            </td>
                            <td style={{ padding: '7px 10px', fontFamily: 'JetBrains Mono, monospace', fontWeight: 600, color: confColor }}>
                              {conf === null || conf === undefined ? 'N/A' : conf.toFixed(2)}
                            </td>
                            <td style={{ padding: '7px 10px', color: '#94A3B8', fontSize: 11, maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                              {t.reason || '(AI复核降级)'}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </>
            );
          })()}
        </div>
      </Card>

      {/* ② 决策流和 AI 五层总控已迁移到驾驶舱 (DashboardPanel), 这里不再重复展示 */}
      {/* AI Quant Operator 总控已迁移到驾驶舱, 此处不再重复 */}

      {/* 操作按钮 — 职责分离: 调度控制归驾驶舱, 这里只管执行配置 */}
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        {/* 调度状态提示 (调度控制已统一到驾驶舱) */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8, padding: '10px 16px',
          background: schedActive ? '#064E3B' : '#1E293B',
          border: `1px solid ${schedActive ? '#10B981' : '#334155'}`,
          borderRadius: 8,
        }}>
          {schedActive ? <Activity style={{ width: 14, height: 14, color: '#10B981' }} /> : <Clock style={{ width: 14, height: 14, color: '#64748B' }} />}
          <span style={{ fontSize: 12, color: schedActive ? '#A7F3D0' : '#94A3B8' }}>
            {schedActive ? '⚡ 由驾驶舱自主调度器驱动交易' : '⚪ 调度未启动 — 可在驾驶舱开启自主调度'}
          </span>
        </div>
        <button onClick={runNow} disabled={loading}
          style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '10px 20px', background: '#1E293B', border: '1px solid #334155', borderRadius: 8, color: '#E2E8F0', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}
          title="只跑策略+下单, 不跑 AI 闭环。AI 闭环由驾驶舱调度器自动驱动。">
          {loading ? <Loader2 style={{ width: 14, height: 14, animation: 'spin 1s linear infinite' }} /> : <Zap style={{ width: 14, height: 14, color: ACCENT }} />}
          测试执行一次
        </button>
        <span style={{ fontSize: 10, color: '#64748B' }}>只跑策略+下单, 不跑 AI 闭环</span>
        <button onClick={saveConfig} disabled={loading}
          style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '10px 20px', background: 'transparent', border: '1px solid #334155', borderRadius: 8, color: '#94A3B8', fontSize: 13, cursor: 'pointer' }}>
          保存配置
        </button>
      </div>

      {/* 配置区 */}
      <Card title="策略配置">
        <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
            <div>
              <Label>策略</Label>
              <select value={strategy} onChange={e => setStrategy(e.target.value)} style={{ ...inputStyle, width: '100%' }}>
                {meta && Object.entries(meta).map(([k, v]) => (
                  <option key={k} value={k}>{v.name} ({k})</option>
                ))}
              </select>
            </div>
            <div>
              <Label>每日触发时间 (HH:MM, 收盘后)</Label>
              <input value={tradeTime} onChange={e => setTradeTime(e.target.value)} style={{ ...inputStyle, width: '100%' }} />
            </div>
          </div>

          {/* 动态策略参数 */}
          {meta && meta[strategy] && meta[strategy].params.length > 0 && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14 }}>
              {meta[strategy].params.map((p) => (
                <div key={p.name}>
                  <Label>{p.name} <span style={{ color: '#334155' }}>({p.desc})</span></Label>
                  <input value={params[p.name] ?? ''} onChange={e => setParams(prev => ({ ...prev, [p.name]: e.target.value }))} style={{ ...inputStyle, width: '100%' }} />
                </div>
              ))}
            </div>
          )}

          <div>
            <Label>选股池 (逗号分隔 6 位代码)</Label>
            <input value={universe} onChange={e => setUniverse(e.target.value)} style={{ ...inputStyle, width: '100%' }} placeholder="600519,000858,600036" />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
            <div>
              <Label>单股仓位占比 (0~1)</Label>
              <input value={posPct} onChange={e => setPosPct(e.target.value)} style={{ ...inputStyle, width: '100%' }} />
            </div>
            <div>
              <Label>最大持仓只数</Label>
              <input value={maxPos} onChange={e => setMaxPos(e.target.value)} style={{ ...inputStyle, width: '100%' }} />
            </div>
          </div>

          {meta && meta[strategy] && (
            <div style={{ fontSize: 11, color: '#475569', padding: '8px 10px', background: '#0B0F1A', borderRadius: 6 }}>
              {meta[strategy].desc}
            </div>
          )}

          {/* AI 大模型配置 */}
          <div style={{ padding: '12px 14px', background: 'linear-gradient(135deg, #1E1B4B 0%, #0B0F1A 100%)', border: '1px solid #312E81', borderRadius: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <Bot style={{ width: 13, height: 13, color: '#A78BFA' }} />
                <span style={{ fontSize: 12, fontWeight: 600, color: '#C4B5FD' }}>AI 大模型决策</span>
                <span style={{ fontSize: 9, color: '#7C3AED', background: '#4C1D9555', padding: '1px 6px', borderRadius: 8 }}>
                  {llmEnabled ? '已启用' : '未启用'}
                </span>
              </div>
              <button onClick={() => { const next = !llmEnabled; setLlmEnabled(next); persistLlm({ enabled: next }); }}
                style={{ width: 36, height: 18, borderRadius: 9, border: 'none', cursor: 'pointer',
                  background: llmEnabled ? '#7C3AED' : '#334155', position: 'relative', transition: 'background 0.2s' }}>
                <div style={{ width: 14, height: 14, borderRadius: '50%', background: 'white', position: 'absolute',
                  top: 2, left: llmEnabled ? 20 : 2, transition: 'left 0.2s' }} />
              </button>
            </div>
            {llmEnabled && (
              <>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 8 }}>
                  <div>
                    <Label>模型供应商</Label>
                    <select value={llmProvider} onChange={e => { setLlmProvider(e.target.value); setLlmTestResult(null); persistLlm({ provider: e.target.value }); }} style={{ ...inputStyle, width: '100%' }}>
                      <option value="glm">GLM 智谱 (自建)</option>
                      <option value="deepseek">DeepSeek</option>
                      <option value="qwen">通义千问 Qwen</option>
                      <option value="gemini">Gemini</option>
                    </select>
                  </div>
                  <div>
                    <Label>决策模式</Label>
                    <select value={llmMode} onChange={e => { setLlmMode(e.target.value); persistLlm({ mode: e.target.value }); }} style={{ ...inputStyle, width: '100%' }}>
                      <option value="off">关闭 (纯量化)</option>
                      <option value="review">审核模式 (二次审核量化信号)</option>
                      <option value="decide">决策模式 (LLM 独立建议)</option>
                    </select>
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <button onClick={testLlm} disabled={llmTesting}
                    style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '5px 12px', background: '#4C1D95', border: '1px solid #7C3AED', borderRadius: 6, color: '#DDD6FE', fontSize: 11, cursor: 'pointer' }}>
                    {llmTesting ? <Loader2 style={{ width: 11, height: 11, animation: 'spin 1s linear infinite' }} /> : <Zap style={{ width: 11, height: 11 }} />}
                    测试连接
                  </button>
                  {llmTestResult && <span style={{ fontSize: 10, color: llmTestResult.startsWith('✅') ? '#4ADE80' : '#F87171' }}>{llmTestResult}</span>}
                </div>
                <div style={{ fontSize: 10, color: '#6D5FBC', marginTop: 8 }}>
                  ⚙️ 所有 LLM 建议必须通过风控网关 (仓位/敞口/现金/整手/T+1) 才能下单, AI 无法绕过
                </div>
              </>
            )}

            {/* Token 使用量统计 */}
            <TokenUsageStats usage={llmUsage} loading={llmUsageLoading} onRefresh={fetchLlmUsage} onReset={resetLlmUsage} />
          </div>
        </div>
      </Card>

      {/* 实时运行日志 */}
      {(runInProgress || progressEvents.length > 0) && (
        <Card title="实时运行日志" right={
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <div style={{ width: 6, height: 6, borderRadius: '50%', background: runInProgress ? '#FBBF24' : '#4ADE80', boxShadow: runInProgress ? '0 0 6px #FBBF24' : '0 0 6px #4ADE80' }} />
            <span style={{ fontSize: 10, color: runInProgress ? '#FBBF24' : '#4ADE80' }}>{runInProgress ? '运行中' : '已完成'}</span>
          </div>
        }>
          <div ref={(el) => { if (el) el.scrollTop = el.scrollHeight; }}
            style={{ maxHeight: 280, overflowY: 'auto', background: '#050810', fontFamily: 'Consolas, "Courier New", monospace', padding: '12px 16px' }}>
            {progressEvents.length === 0 ? (
              <div style={{ color: '#334155', fontSize: 12, padding: '20px 0', textAlign: 'center' }}>等待启动...</div>
            ) : (
              progressEvents.map((ev, i) => {
                const icon = ev.status === 'done' ? '✓' : ev.status === 'error' ? '✗' : ev.status === 'skip' ? '⊘' : '⏳';
                const color = ev.status === 'done' ? '#4ADE80' : ev.status === 'error' ? '#F87171' : ev.status === 'skip' ? '#94A3B8' : '#FBBF24';
                const time = String(ev.time || '').slice(11, 19);
                return (
                  <div key={i} style={{ display: 'flex', gap: 8, padding: '3px 0', fontSize: 12, lineHeight: 1.6, alignItems: 'flex-start' }}>
                    <span style={{ color: '#475569', flexShrink: 0 }}>{time}</span>
                    <span style={{ color, flexShrink: 0, width: 14, textAlign: 'center' }}>
                      {ev.status === 'running' ? <Loader2 style={{ width: 11, height: 11, animation: 'spin 1s linear infinite', display: 'inline' }} /> : icon}
                    </span>
                    <span style={{ color: ev.status === 'running' ? '#E2E8F0' : '#94A3B8', fontWeight: ev.status === 'running' ? 600 : 400 }}>{ev.label}</span>
                    {ev.detail && <span style={{ color: '#64748B', fontSize: 11 }}>— {ev.detail}</span>}
                  </div>
                );
              })
            )}
          </div>
        </Card>
      )}

      {/* 上次运行结果 */}
      {lastRunResult && (
        <Card title="最近一次运行结果" right={<span style={{ fontSize: 10, color: '#334155' }}>{fmtTime(lastRunResult.finished_at)}</span>}>
          <div style={{ padding: 16 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 14 }}>
              <div style={{ background: '#0B0F1A', borderRadius: 8, padding: 12 }}>
                <div style={{ fontSize: 10, color: '#475569', marginBottom: 4 }}>有数据股票</div>
                <div style={{ fontSize: 18, fontWeight: 700, fontFamily: 'JetBrains Mono, monospace', color: '#F1F5F9' }}>{lastRunResult.stocks_with_data ?? 0}</div>
              </div>
              <div style={{ background: '#0B0F1A', borderRadius: 8, padding: 12 }}>
                <div style={{ fontSize: 10, color: '#475569', marginBottom: 4 }}>产生信号</div>
                <div style={{ fontSize: 18, fontWeight: 700, fontFamily: 'JetBrains Mono, monospace', color: '#60A5FA' }}>{(lastRunResult.signals || []).length}</div>
              </div>
              <div style={{ background: '#0B0F1A', borderRadius: 8, padding: 12 }}>
                <div style={{ fontSize: 10, color: '#475569', marginBottom: 4 }}>下单数</div>
                <div style={{ fontSize: 18, fontWeight: 700, fontFamily: 'JetBrains Mono, monospace', color: '#4ADE80' }}>{lastRunResult.order_count ?? 0}</div>
              </div>
            </div>

            {lastRunResult.errors && lastRunResult.errors.length > 0 && (
              <div style={{ padding: '8px 12px', background: '#EF444411', border: '1px solid #EF444433', borderRadius: 6, fontSize: 11, color: '#F87171', marginBottom: 10 }}>
                {lastRunResult.errors.map((er: string, i: number) => <div key={i}>• {er}</div>)}
              </div>
            )}

            {(lastRunResult.signals || []).length > 0 && (
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead><tr style={{ borderBottom: '1px solid #1E293B' }}>
                  {['代码', '信号', '动作', '数量', '价格'].map((h, i) => (
                    <th key={h} style={{ padding: '8px 12px', textAlign: i >= 2 ? 'right' : 'left', fontSize: 10, fontWeight: 600, color: '#475569' }}>{h}</th>
                  ))}
                </tr></thead>
                <tbody>
                  {lastRunResult.signals.map((s: any, i: number) => (
                    <tr key={i} style={{ borderBottom: '1px solid #1E293B44' }}>
                      <td style={{ padding: '8px 12px', fontFamily: 'JetBrains Mono, monospace', color: '#60A5FA', fontWeight: 600 }}>{s.code}</td>
                      <td style={{ padding: '8px 12px', fontFamily: 'JetBrains Mono, monospace', color: s.signal >= 1 ? '#4ADE80' : '#F87171' }}>{s.signal >= 1 ? '做多' : '平仓'}</td>
                      <td style={{ padding: '8px 12px', textAlign: 'right', color: s.action.includes('sell') ? '#F87171' : '#4ADE80' }}>{s.action}</td>
                      <td style={{ padding: '8px 12px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: '#94A3B8' }}>{s.qty}</td>
                      <td style={{ padding: '8px 12px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: '#94A3B8' }}>{Number(s.price || 0).toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </Card>
      )}

      {/* 每日日报 + 基准对比 */}
      <Card title="每日日报 · 基准对比" right={
        <button onClick={() => fetchReport(true)} disabled={reportLoading}
          style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '3px 8px', background: '#1E293B', border: 'none', borderRadius: 6, color: '#94A3B8', fontSize: 10, cursor: 'pointer' }}>
          {reportLoading ? <Loader2 style={{ width: 10, height: 10, animation: 'spin 1s linear infinite' }} /> : <FileText style={{ width: 10, height: 10 }} />}
          生成最新
        </button>
      }>
        {report ? (
          <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 14 }}>
            {/* 账户 + 基准 核心指标 */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
              {(() => {
                const acc = report.account || {};
                const bm = report.benchmark || {};
                const totalPnl = acc.total_pnl ?? 0;
                const totalPnlPct = acc.total_pnl_pct ?? 0;
                const excess = bm.excess_return_pct ?? 0;
                const isUp = totalPnl >= 0;
                const isExcessPositive = excess >= 0;
                const items = [
                  { label: '总权益', value: `¥${(acc.total_equity ?? 0).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`, color: '#F1F5F9', icon: Activity },
                  { label: '累计盈亏', value: `${totalPnl >= 0 ? '+' : ''}¥${Math.abs(totalPnl).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })} (${totalPnlPct.toFixed(2)}%)`, color: isUp ? '#4ADE80' : '#F87171', icon: isUp ? TrendingUp : TrendingDown },
                  { label: `${bm.name || '沪深300'} 累计`, value: `${(bm.total_return_pct ?? 0).toFixed(2)}%`, color: '#60A5FA', icon: TrendingUp },
                  { label: '超额收益', value: `${excess >= 0 ? '+' : ''}${excess.toFixed(2)}%`, color: isExcessPositive ? '#4ADE80' : '#F87171', icon: isExcessPositive ? TrendingUp : TrendingDown },
                ];
                return items.map((m, i) => {
                  const Icon = m.icon;
                  return (
                    <div key={i} style={{ background: '#0B0F1A', borderRadius: 8, padding: '12px 14px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 6 }}>
                        <Icon style={{ width: 11, height: 11, color: '#475569' }} />
                        <span style={{ fontSize: 10, color: '#475569', letterSpacing: 0.3 }}>{m.label}</span>
                      </div>
                      <div style={{ fontSize: 14, fontWeight: 700, fontFamily: 'JetBrains Mono, monospace', color: m.color }}>{m.value}</div>
                    </div>
                  );
                });
              })()}
            </div>

            {/* 账户细节 */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
              <div style={{ background: '#0B0F1A', borderRadius: 8, padding: '10px 14px' }}>
                <div style={{ fontSize: 10, color: '#475569' }}>现金</div>
                <div style={{ fontSize: 13, fontWeight: 600, fontFamily: 'JetBrains Mono, monospace', color: '#94A3B8' }}>¥{(report.account?.cash ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>
              </div>
              <div style={{ background: '#0B0F1A', borderRadius: 8, padding: '10px 14px' }}>
                <div style={{ fontSize: 10, color: '#475569' }}>持仓市值</div>
                <div style={{ fontSize: 13, fontWeight: 600, fontFamily: 'JetBrains Mono, monospace', color: '#94A3B8' }}>¥{(report.account?.market_value ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>
              </div>
              <div style={{ background: '#0B0F1A', borderRadius: 8, padding: '10px 14px' }}>
                <div style={{ fontSize: 10, color: '#475569' }}>持仓数</div>
                <div style={{ fontSize: 13, fontWeight: 600, fontFamily: 'JetBrains Mono, monospace', color: '#94A3B8' }}>{report.account?.position_count ?? 0}</div>
              </div>
            </div>

            {/* 数据状态 + 告警 */}
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              {report.data?.is_stale && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '5px 10px', background: '#F59E0B14', border: '1px solid #F59E0B33', borderRadius: 6, fontSize: 11, color: '#FBBF24' }}>
                  <AlertCircle style={{ width: 11, height: 11 }} />
                  数据过期: 最新K线 {report.data.latest_kline_date || 'N/A'}
                </div>
              )}
              {report.alerts?.active > 0 && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '5px 10px', background: '#EF444414', border: '1px solid #EF444433', borderRadius: 6, fontSize: 11, color: '#F87171' }}>
                  <AlertTriangle style={{ width: 11, height: 11 }} />
                  活跃告警 {report.alerts.active} (严重 {report.alerts.critical ?? 0})
                </div>
              )}
              {report.paper_skip_reason && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '5px 10px', background: '#1E293B', border: '1px solid #334155', borderRadius: 6, fontSize: 11, color: '#94A3B8' }}>
                  跳过: {report.paper_skip_reason}
                </div>
              )}
              <div style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '5px 10px', fontSize: 10, color: '#334155' }}>
                生成于 {String(report.generated_at || '').slice(0, 19)}
              </div>
            </div>

            {/* 风控拒单 */}
            {(report.risk_rejections || []).length > 0 && (
              <div style={{ padding: '8px 12px', background: '#EF444411', border: '1px solid #EF444433', borderRadius: 6, fontSize: 11, color: '#F87171' }}>
                <div style={{ fontWeight: 600, marginBottom: 4 }}>风控拒单 ({report.risk_rejections.length})</div>
                {(report.risk_rejections || []).map((rj: any, i: number) => (
                  <div key={i}>• {rj.code} {rj.direction} {rj.qty}: {rj.reason}</div>
                ))}
              </div>
            )}

            {/* 持仓明细 */}
            {(report.positions || []).length > 0 && (
              <div>
                <div style={{ fontSize: 10, color: '#475569', marginBottom: 6, letterSpacing: 0.3 }}>持仓明细 (硬止损线 -8%)</div>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                  <thead><tr style={{ borderBottom: '1px solid #1E293B' }}>
                    {['代码', '数量', '成本', '现价', '市值', '盈亏%', '止损状态', '可卖'].map((h, i) => (
                      <th key={h} style={{ padding: '6px 8px', textAlign: i >= 1 ? 'right' : 'left', fontSize: 10, fontWeight: 600, color: '#475569' }}>{h}</th>
                    ))}
                  </tr></thead>
                  <tbody>
                    {(report.positions || []).map((p: any, i: number) => {
                      const pnlPct = p.pnl_pct ?? 0;
                      // 止损状态: 距 -8% 硬止损线的距离
                      const stopDist = pnlPct - (-8);
                      const stopColor = pnlPct <= -8 ? '#EF4444' : pnlPct <= -5 ? '#F59E0B' : '#10B981';
                      const stopLabel = pnlPct <= -8 ? '⚠已触发' : pnlPct <= -5 ? `接近 ${stopDist.toFixed(1)}%` : '安全';
                      return (
                        <tr key={i} style={{ borderBottom: '1px solid #1E293B44' }}>
                          <td style={{ padding: '6px 8px', fontFamily: 'JetBrains Mono, monospace', color: '#60A5FA', fontWeight: 600 }}>{p.code}</td>
                          <td style={{ padding: '6px 8px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: '#94A3B8' }}>{p.quantity}</td>
                          <td style={{ padding: '6px 8px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: '#94A3B8' }}>{p.avg_price?.toFixed(2)}</td>
                          <td style={{ padding: '6px 8px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: '#94A3B8' }}>{p.current_price?.toFixed(2)}</td>
                          <td style={{ padding: '6px 8px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: '#94A3B8' }}>{p.market_value?.toLocaleString(undefined, { maximumFractionDigits: 0 })}</td>
                          <td style={{ padding: '6px 8px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: pnlPct >= 0 ? '#4ADE80' : '#F87171', fontWeight: 600 }}>{pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%</td>
                          <td style={{ padding: '6px 8px', textAlign: 'right', fontSize: 10, fontWeight: 600, color: stopColor }}>{stopLabel}</td>
                          <td style={{ padding: '6px 8px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: p.available_qty > 0 ? '#4ADE80' : '#475569' }}>{p.available_qty}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            {/* 今日订单 */}
            {(report.today_orders || []).length > 0 && (
              <div>
                <div style={{ fontSize: 10, color: '#475569', marginBottom: 6, letterSpacing: 0.3 }}>今日订单 ({report.today_orders.length})</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {(report.today_orders || []).map((o: any, i: number) => (
                    <div key={i} style={{ display: 'flex', gap: 10, fontSize: 11, padding: '4px 8px', background: '#0B0F1A', borderRadius: 4 }}>
                      <span style={{ color: o.success === false ? '#F87171' : '#4ADE80' }}>{o.success === false ? '❌' : '✅'}</span>
                      <span style={{ fontFamily: 'JetBrains Mono, monospace', color: '#60A5FA', fontWeight: 600 }}>{o.code}</span>
                      <span style={{ color: o.direction === 'sell' ? '#F87171' : '#4ADE80' }}>{o.direction}</span>
                      <span style={{ fontFamily: 'JetBrains Mono, monospace', color: '#94A3B8' }}>{o.qty}</span>
                      {o.error && <span style={{ color: '#F87171' }}>{o.error}</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* AI 复盘 */}
            {report.ai_review?.enabled && report.ai_review?.active && report.ai_review?.text && (
              <div style={{ padding: '12px 14px', background: 'linear-gradient(135deg, #1E1B4B 0%, #0B0F1A 100%)', border: '1px solid #4C1D95', borderRadius: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
                  <FileText style={{ width: 12, height: 12, color: '#A78BFA' }} />
                  <span style={{ fontSize: 11, fontWeight: 600, color: '#C4B5FD' }}>AI 复盘</span>
                  <span style={{ fontSize: 9, color: '#7C3AED', background: '#4C1D9555', padding: '1px 6px', borderRadius: 8 }}>
                    {report.ai_review.provider_label || report.ai_review.provider || 'AI'}
                  </span>
                </div>
                <div style={{ fontSize: 11, color: '#DDD6FE', lineHeight: 1.7, whiteSpace: 'pre-wrap' }}>
                  {report.ai_review.text}
                </div>
              </div>
            )}
            {report.ai_review?.enabled && !report.ai_review?.active && (
              <div style={{ padding: '8px 12px', background: '#0B0F1A', border: '1px solid #1E293B', borderRadius: 6, fontSize: 10, color: '#475569' }}>
                AI 复盘未启用或调用失败 {report.ai_review.error ? `(${report.ai_review.error})` : ''}
              </div>
            )}
          </div>
        ) : (
          <div style={{ padding: '40px 0', display: 'flex', flexDirection: 'column', alignItems: 'center', color: '#334155' }}>
            {reportLoading ? (
              <Loader2 style={{ width: 28, height: 28, marginBottom: 8, animation: 'spin 1s linear infinite', color: '#475569' }} />
            ) : (
              <FileText style={{ width: 36, height: 36, marginBottom: 8, opacity: 0.4 }} />
            )}
            <div style={{ fontSize: 13, color: '#475569' }}>{reportLoading ? '生成日报中...' : '暂无日报，点击「生成最新」'}</div>
          </div>
        )}
      </Card>

      {/* 运行日志 */}
      <Card title="运行日志" right={<span style={{ fontSize: 10, color: '#334155', background: '#1E293B', padding: '2px 8px', borderRadius: 10 }}>{logs.length} 条</span>}>
        {logs.length === 0 ? (
          <div style={{ padding: '40px 0', display: 'flex', flexDirection: 'column', alignItems: 'center', color: '#334155' }}>
            <Activity style={{ width: 36, height: 36, marginBottom: 8, opacity: 0.4 }} />
            <div style={{ fontSize: 13, color: '#475569' }}>暂无运行记录</div>
          </div>
        ) : (
          <div style={{ maxHeight: 320, overflowY: 'auto' }}>
            {logs.map((lg, i) => (
              <div key={i} style={{ padding: '10px 16px', borderBottom: '1px solid #1E293B44', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0, flex: 1 }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <span style={{ fontSize: 11, color: '#64748B', fontFamily: 'JetBrains Mono, monospace' }}>{fmtTime(lg.time)}</span>
                    <span style={{ fontSize: 11, color: ACCENT, background: `${ACCENT}22`, padding: '1px 6px', borderRadius: 4 }}>{lg.strategy}</span>
                    <span style={{ fontSize: 11, color: '#475569' }}>{lg.order_count} 单</span>
                  </div>
                  {(lg.signals || []).length > 0 && (
                    <div style={{ fontSize: 11, color: '#94A3B8', display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                      {lg.signals.slice(0, 8).map((s: any, j: number) => (
                        <span key={j} style={{ fontFamily: 'JetBrains Mono, monospace', color: s.action.includes('sell') ? '#F87171' : '#4ADE80' }}>
                          {s.code}·{s.action}
                        </span>
                      ))}
                      {lg.signals.length > 8 && <span style={{ color: '#475569' }}>+{lg.signals.length - 8}</span>}
                    </div>
                  )}
                  {(lg.errors || []).length > 0 && (
                    <div style={{ fontSize: 11, color: '#F87171' }}>{lg.errors[0]}</div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
};

export default PaperPanel;
