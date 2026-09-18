import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  AlertTriangle,
  BarChart3,
  BrainCircuit,
  Calculator,
  Database,
  RefreshCw,
  Scale,
  Search,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';

const API_BASE = (import.meta as any).env?.VITE_API_BASE || '';
const API_TOKEN = (import.meta as any).env?.VITE_XUANJI_API_TOKEN || '';
const jsonHeaders = () => ({
  'Content-Type': 'application/json',
  ...(API_TOKEN ? { 'X-XuanJi-Token': API_TOKEN } : {}),
});

type TrackStatus = 'success' | 'partial' | 'unavailable' | 'error';

interface TrackResult {
  type?: string;
  status?: TrackStatus;
  low?: number | null;
  mid?: number | null;
  high?: number | null;
  confidence?: number | null;
  details?: Record<string, any>;
  warnings?: string[];
  error?: string;
}

interface AnalysisResult {
  valuation_id?: string;
  code?: string;
  name?: string;
  data_date?: string;
  report_period?: string;
  current_price?: number | null;
  sources?: string[];
  warnings?: string[];
  valuations?: Record<string, TrackResult>;
  consensus?: {
    status?: string;
    base_mid?: number | null;
    final_mid?: number | null;
    market_adjustment?: number | null;
    weights?: Record<string, number>;
    calibration?: Record<string, Record<string, any>>;
    market_applied_once?: boolean;
  };
  financial_quality?: {
    valuation_as_of?: string | null;
    financial_as_of?: string | null;
    point_in_time_quality?: string | null;
    point_in_time_quality_score?: number | null;
    ttm_formula?: string | null;
  };
}

interface GlmResult {
  valuation_id?: string;
  provider?: string;
  model?: string;
  model_source?: string;
  model_version?: string;
  prompt_version?: string;
  usage?: Record<string, any>;
  valuation?: TrackResult;
}

interface ValuationPanelProps {
  initialCode: string;
  initialName?: string;
  requestKey: number;
}

const TRACK_META = {
  absolute: { label: '绝对估值', icon: Calculator, color: '#38BDF8' },
  relative: { label: '相对估值', icon: Scale, color: '#A78BFA' },
  market: { label: '市场估值', icon: BarChart3, color: '#F59E0B' },
  glm: { label: 'AI 模型估值', icon: BrainCircuit, color: '#34D399' },
};

function normalizeCode(value: string): string {
  let code = String(value || '').trim().toUpperCase();
  code = code.replace(/\.SH$|\.SZ$/i, '');
  if (code.startsWith('SH') || code.startsWith('SZ')) code = code.slice(2);
  return /^\d{6}$/.test(code) && !code.startsWith('920') ? code : '';
}

async function valuationApi(body: Record<string, any>, signal?: AbortSignal) {
  const response = await fetch(`${API_BASE}/api/valuation`, {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify(body),
    signal,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || !payload.success) {
    throw new Error(payload.error || `估值接口请求失败 (${response.status})`);
  }
  return payload.data;
}

function formatPrice(value: unknown): string {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number.toFixed(2) : '--';
}

function formatPercent(value: unknown): string {
  const number = Number(value);
  return Number.isFinite(number) ? `${(number * 100).toFixed(0)}%` : '--';
}

function statusLabel(status?: TrackStatus): string {
  return {
    success: '完整',
    partial: '降级可用',
    unavailable: '不可用',
    error: '错误',
  }[status || 'unavailable'];
}

function statusColor(status?: TrackStatus): string {
  return {
    success: '#34D399',
    partial: '#F59E0B',
    unavailable: '#64748B',
    error: '#F87171',
  }[status || 'unavailable'];
}

const StatusBadge: React.FC<{ status?: TrackStatus }> = ({ status }) => {
  const color = statusColor(status);
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      minHeight: 22,
      padding: '2px 8px',
      borderRadius: 6,
      background: `${color}14`,
      border: `1px solid ${color}44`,
      color,
      fontSize: 12,
      fontWeight: 700,
    }}>
      {statusLabel(status)}
    </span>
  );
};

const SummaryMetric: React.FC<{
  label: string;
  value: string;
  note?: string;
  color?: string;
}> = ({ label, value, note, color = '#E2E8F0' }) => (
  <div style={{
    minWidth: 0,
    padding: '12px 14px',
    background: '#0F172A',
    border: '1px solid #1E293B',
    borderRadius: 8,
  }}>
    <div style={{ color: '#64748B', fontSize: 12 }}>{label}</div>
    <div style={{
      marginTop: 6,
      color,
      fontSize: 18,
      fontWeight: 750,
      fontFamily: 'JetBrains Mono, monospace',
      overflowWrap: 'anywhere',
    }}>
      {value}
    </div>
    {note ? <div style={{ marginTop: 4, color: '#475569', fontSize: 12 }}>{note}</div> : null}
  </div>
);

const WarningList: React.FC<{ warnings?: string[]; error?: string }> = ({ warnings, error }) => {
  const items = [...(warnings || [])];
  if (error) items.unshift(error);
  if (!items.length) return null;
  return (
    <div style={{ display: 'grid', gap: 5, marginTop: 12 }}>
      {items.slice(0, 6).map((item, index) => (
        <div key={`${item}-${index}`} style={{
          display: 'flex',
          gap: 6,
          color: error && index === 0 ? '#FCA5A5' : '#FBBF24',
          fontSize: 12,
          lineHeight: 1.5,
        }}>
          <AlertTriangle style={{ width: 12, height: 12, flex: '0 0 auto', marginTop: 1 }} />
          <span>{item}</span>
        </div>
      ))}
    </div>
  );
};

const PriceBand: React.FC<{ track?: TrackResult }> = ({ track }) => (
  <div style={{
    display: 'grid',
    gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
    gap: 8,
    marginTop: 14,
  }}>
    {[
      ['保守', track?.low, '#94A3B8'],
      ['中枢', track?.mid, '#F8FAFC'],
      ['乐观', track?.high, '#34D399'],
    ].map(([label, value, color]) => (
      <div key={String(label)} style={{ padding: '9px 10px', background: '#0B1220', borderRadius: 6 }}>
        <div style={{ color: '#64748B', fontSize: 11 }}>{label}</div>
        <div style={{
          color: String(color),
          marginTop: 4,
          fontSize: 15,
          fontWeight: 750,
          fontFamily: 'JetBrains Mono, monospace',
        }}>
          {formatPrice(value)}
        </div>
      </div>
    ))}
  </div>
);

const ValuationTrack: React.FC<{
  kind: keyof typeof TRACK_META;
  track?: TrackResult;
  children?: React.ReactNode;
  pending?: boolean;
}> = ({ kind, track, children, pending }) => {
  const meta = TRACK_META[kind];
  const Icon = meta.icon;
  return (
    <section style={{
      minWidth: 0,
      padding: 16,
      background: '#111827',
      border: '1px solid #1E293B',
      borderRadius: 8,
      contentVisibility: 'auto',
      containIntrinsicSize: '360px',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
        <div style={{
          width: 30,
          height: 30,
          display: 'grid',
          placeItems: 'center',
          borderRadius: 7,
          background: `${meta.color}14`,
          border: `1px solid ${meta.color}38`,
        }}>
          <Icon style={{ width: 15, height: 15, color: meta.color }} />
        </div>
        <div style={{ minWidth: 0 }}>
          <div style={{ color: '#E2E8F0', fontSize: 13, fontWeight: 700 }}>{meta.label}</div>
          <div style={{ color: '#475569', fontSize: 11 }}>
            {kind === 'glm' ? '独立模型判断 · 不覆盖规则估值' : '确定性公式 · 可回放'}
          </div>
        </div>
        <div style={{ marginLeft: 'auto' }}>
          {pending ? (
            <RefreshCw style={{ width: 14, height: 14, color: meta.color, animation: 'spin 1s linear infinite' }} />
          ) : (
            <StatusBadge status={track?.status} />
          )}
        </div>
      </div>
      <PriceBand track={track} />
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 10, color: '#64748B', fontSize: 12 }}>
        <span>置信度</span>
        <span style={{ color: '#CBD5E1', fontFamily: 'JetBrains Mono, monospace' }}>{formatPercent(track?.confidence)}</span>
      </div>
      {children}
      <WarningList warnings={track?.warnings} error={track?.error} />
    </section>
  );
};

const DcfDetails: React.FC<{ track?: TrackResult }> = ({ track }) => {
  const rows = Array.isArray(track?.details?.sensitivity) ? track?.details?.sensitivity : [];
  if (!rows.length) return null;
  const discountLabel = track?.details?.discount_rate_type === 'cost_of_equity'
    ? '股权资本成本 Ke'
    : 'WACC';
  const normalizedCash = track?.details?.normalized_cash_flow || {};
  return (
    <div style={{ marginTop: 14 }}>
      <div style={{ color: '#64748B', fontSize: 11, lineHeight: 1.6, marginBottom: 8 }}>
        现金流口径 {track?.details?.cash_flow_method || '--'}
        {' · '}{discountLabel} {formatPercent(track?.details?.discount_rate)}
        {' · '}标准化每股现金流 {formatPrice(normalizedCash.per_share)}
      </div>
      <div style={{ color: '#94A3B8', fontSize: 12, fontWeight: 700, marginBottom: 7 }}>DCF 敏感性</div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
          <thead>
            <tr style={{ color: '#475569' }}>
              <th style={{ padding: '5px', textAlign: 'left' }}>{discountLabel}</th>
              <th style={{ padding: '5px', textAlign: 'right' }}>永续增长</th>
              <th style={{ padding: '5px', textAlign: 'right' }}>每股价值</th>
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 9).map((row: any, index: number) => (
              <tr key={index} style={{ borderTop: '1px solid #1E293B' }}>
                <td style={{ padding: '5px', color: '#94A3B8' }}>{formatPercent(row.wacc)}</td>
                <td style={{ padding: '5px', color: '#94A3B8', textAlign: 'right' }}>{formatPercent(row.terminal_growth)}</td>
                <td style={{ padding: '5px', color: '#E2E8F0', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace' }}>{formatPrice(row.per_share)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

const RelativeDetails: React.FC<{ track?: TrackResult }> = ({ track }) => {
  const details = track?.details || {};
  const methods = details.methods && typeof details.methods === 'object' ? details.methods : {};
  return (
    <div style={{ marginTop: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', color: '#94A3B8', fontSize: 12 }}>
        <span>同行样本</span>
        <span>{details.sample_count ?? 0} 有效 / {details.excluded_count ?? 0} 剔除</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 6, marginTop: 8 }}>
        {['pe', 'peg', 'pb', 'ps'].map(method => (
          <div key={method} style={{ padding: 7, background: '#0B1220', borderRadius: 6, textAlign: 'center' }}>
            <div style={{ color: '#64748B', fontSize: 11 }}>{method.toUpperCase()}</div>
            <div style={{ color: '#E2E8F0', marginTop: 3, fontSize: 11, fontFamily: 'JetBrains Mono, monospace' }}>
              {formatPrice(methods[method]?.mid)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

const MarketDetails: React.FC<{ track?: TrackResult }> = ({ track }) => {
  const details = track?.details || {};
  const factors = details.factors || {};
  return (
    <div style={{ marginTop: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', color: '#94A3B8', fontSize: 12 }}>
        <span>市场调整</span>
        <span style={{ color: Number(details.adjustment || 0) >= 0 ? '#F87171' : '#34D399' }}>
          {Number.isFinite(Number(details.adjustment)) ? `${(Number(details.adjustment) * 100).toFixed(1)}%` : '--'}
        </span>
      </div>
      <div style={{ display: 'grid', gap: 5, marginTop: 8 }}>
        {[
          ['个股位置', factors.own],
          ['行业位置', factors.industry],
          ['指数状态', factors.index],
          ['宽度/流动性', factors.liquidity],
        ].map(([label, value]) => (
          <div key={String(label)} style={{ display: 'grid', gridTemplateColumns: '72px 1fr 42px', alignItems: 'center', gap: 8, fontSize: 11 }}>
            <span style={{ color: '#64748B' }}>{label}</span>
            <div style={{ height: 4, background: '#0B1220', borderRadius: 2, overflow: 'hidden' }}>
              <div style={{
                height: '100%',
                width: `${Math.min(100, Math.abs(Number(value || 0)) * 100)}%`,
                background: Number(value || 0) >= 0 ? '#F59E0B' : '#34D399',
              }} />
            </div>
            <span style={{ color: '#CBD5E1', textAlign: 'right' }}>{Number.isFinite(Number(value)) ? Number(value).toFixed(2) : '--'}</span>
          </div>
        ))}
      </div>
    </div>
  );
};

const GlmDetails: React.FC<{ track?: TrackResult }> = ({ track }) => {
  const details = track?.details || {};
  const groups = [
    ['核心假设', details.assumptions],
    ['上涨驱动', details.drivers],
    ['下行风险', details.risks],
    ['失效条件', details.invalidation_conditions],
  ];
  return (
    <div style={{ display: 'grid', gap: 9, marginTop: 14 }}>
      {groups.map(([label, values]) => (
        <div key={String(label)}>
          <div style={{ color: '#64748B', fontSize: 11 }}>{label}</div>
          <div style={{ color: '#CBD5E1', fontSize: 12, lineHeight: 1.55, marginTop: 3 }}>
            {Array.isArray(values) && values.length ? values.slice(0, 4).join(' · ') : '--'}
          </div>
        </div>
      ))}
    </div>
  );
};

const ValuationPanel: React.FC<ValuationPanelProps> = ({
  initialCode,
  initialName = '',
  requestKey,
}) => {
  const [code, setCode] = useState(initialCode || '300442');
  const [name, setName] = useState(initialName);
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [glm, setGlm] = useState<GlmResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [glmLoading, setGlmLoading] = useState(false);
  const [error, setError] = useState('');
  const requestRef = useRef<AbortController | null>(null);

  const runAnalyze = useCallback(async (rawCode: string, force = false) => {
    const normalized = normalizeCode(rawCode);
    if (!normalized) {
      setError('请输入有效的沪深 A 股六位代码，920xxx 不在当前范围内');
      return;
    }
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setLoading(true);
    setError('');
    setGlm(null);
    try {
      const data = await valuationApi(
        { action: 'analyze', code: normalized, force },
        controller.signal,
      );
      setAnalysis(data);
      setCode(normalized);
      setName(data?.name || initialName || normalized);
    } catch (requestError: any) {
      if (requestError?.name !== 'AbortError') {
        setError(requestError?.message || '规则估值失败');
      }
    } finally {
      if (requestRef.current === controller) setLoading(false);
    }
  }, [initialName]);

  const runGlm = useCallback(async () => {
    const normalized = normalizeCode(code);
    if (!normalized || glmLoading) return;
    setGlmLoading(true);
    setError('');
    try {
      const data = await valuationApi({ action: 'glm_analyze', code: normalized });
      setGlm(data);
    } catch (requestError: any) {
      setError(requestError?.message || 'AI 模型估值失败');
    } finally {
      setGlmLoading(false);
    }
  }, [code, glmLoading]);

  useEffect(() => {
    const normalized = normalizeCode(initialCode) || '300442';
    setCode(normalized);
    setName(initialName);
    void runAnalyze(normalized);
    return () => requestRef.current?.abort();
  }, [initialCode, initialName, requestKey, runAnalyze]);

  const valuations = analysis?.valuations || {};
  const deterministicMid = Number.isFinite(Number(analysis?.consensus?.final_mid))
    ? Number(analysis?.consensus?.final_mid)
    : (Number.isFinite(Number(valuations.market?.mid)) ? Number(valuations.market?.mid) : null);
  const currentPrice = Number(analysis?.current_price || 0);
  const gap = currentPrice > 0 && deterministicMid
    ? deterministicMid / currentPrice - 1
    : null;
  const statusCount = ['absolute', 'relative', 'market']
    .filter(key => ['success', 'partial'].includes(String(valuations[key]?.status))).length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: 12,
        background: '#111827',
        border: '1px solid #1E293B',
        borderRadius: 8,
        flexWrap: 'wrap',
      }}>
        <div style={{ position: 'relative' }}>
          <Search style={{ position: 'absolute', left: 10, top: 9, width: 14, height: 14, color: '#475569' }} />
          <input
            value={code}
            onChange={event => setCode(event.target.value)}
            onKeyDown={event => {
              if (event.key === 'Enter') void runAnalyze(code);
            }}
            aria-label="股票估值代码"
            style={{
              width: 132,
              height: 32,
              padding: '0 10px 0 32px',
              background: '#0B1220',
              border: '1px solid #293548',
              borderRadius: 7,
              color: '#E2E8F0',
              outline: 'none',
              fontFamily: 'JetBrains Mono, monospace',
              fontSize: 12,
            }}
          />
        </div>
        <button
          onClick={() => void runAnalyze(code, true)}
          disabled={loading}
          style={{
            height: 32,
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            padding: '0 12px',
            borderRadius: 7,
            border: '1px solid #38BDF844',
            background: '#38BDF814',
            color: '#7DD3FC',
            cursor: loading ? 'wait' : 'pointer',
            fontSize: 11,
            fontWeight: 700,
          }}
        >
          <RefreshCw style={{ width: 13, height: 13, animation: loading ? 'spin 1s linear infinite' : 'none' }} />
          运行规则估值
        </button>
        <button
          onClick={() => void runGlm()}
          disabled={glmLoading || !analysis}
          title={API_TOKEN ? '使用当前配置模型运行独立估值' : '需要配置前端 API Token 才能调用受保护动作'}
          style={{
            height: 32,
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            padding: '0 12px',
            borderRadius: 7,
            border: '1px solid #34D39944',
            background: '#34D39914',
            color: '#6EE7B7',
            cursor: glmLoading || !analysis ? 'not-allowed' : 'pointer',
            opacity: glmLoading || !analysis ? 0.55 : 1,
            fontSize: 11,
            fontWeight: 700,
          }}
        >
          <Sparkles style={{ width: 13, height: 13 }} />
          手动运行 AI 估值
        </button>
        <div style={{ marginLeft: 'auto', minWidth: 180, textAlign: 'right' }}>
          <div style={{ color: '#E2E8F0', fontSize: 14, fontWeight: 750 }}>{analysis?.code || code} {analysis?.name || name}</div>
          <div style={{ color: '#64748B', fontSize: 12, marginTop: 2 }}>研究用途 · 不生成订单 · 不覆盖风控</div>
        </div>
      </div>

      {error ? (
        <div style={{ padding: '10px 12px', background: '#7F1D1D22', border: '1px solid #EF444444', borderRadius: 8, color: '#FCA5A5', fontSize: 11 }}>
          {error}
        </div>
      ) : null}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(135px, 1fr))', gap: 8, overflowX: 'auto' }}>
        <SummaryMetric label="规则估值中枢" value={formatPrice(deterministicMid)} note={`${statusCount}/3 轨可用 · 市场调整仅应用一次`} color="#7DD3FC" />
        <SummaryMetric label="当前价格" value={formatPrice(currentPrice)} note="来自估值输入行情" />
        <SummaryMetric label="中枢空间" value={gap == null ? '--' : `${gap >= 0 ? '+' : ''}${(gap * 100).toFixed(1)}%`} note="仅为估值差，不是收益承诺" color={gap != null && gap >= 0 ? '#F87171' : '#34D399'} />
        <SummaryMetric label="数据日期" value={analysis?.data_date || '--'} note="行情/日线最新时点" />
        <SummaryMetric label="报告期" value={analysis?.report_period || '--'} note="财务估值基准" />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 12 }}>
        <ValuationTrack kind="absolute" track={valuations.absolute} pending={loading}>
          <DcfDetails track={valuations.absolute} />
        </ValuationTrack>
        <ValuationTrack kind="relative" track={valuations.relative} pending={loading}>
          <RelativeDetails track={valuations.relative} />
        </ValuationTrack>
        <ValuationTrack kind="market" track={valuations.market} pending={loading}>
          <MarketDetails track={valuations.market} />
        </ValuationTrack>
        <ValuationTrack kind="glm" track={glm?.valuation} pending={glmLoading}>
          <GlmDetails track={glm?.valuation} />
          {glm?.model ? (
            <div style={{ marginTop: 10, color: '#64748B', fontSize: 11 }}>
              实际模型：{glm.provider || '--'} / {glm.model} · 来源 {glm.model_source || '--'}
            </div>
          ) : null}
          {!glm?.valuation && !glmLoading ? (
            <div style={{ marginTop: 14, color: '#64748B', fontSize: 12, lineHeight: 1.6 }}>
              AI 估值不会自动运行。点击上方按钮后，将使用自主调度当前模型读取三类规则估值和同一份数据快照，输出独立判断。
            </div>
          ) : null}
        </ValuationTrack>
      </div>

      <section style={{
        padding: 14,
        background: '#0F172A',
        border: '1px solid #1E293B',
        borderRadius: 8,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <ShieldCheck style={{ width: 15, height: 15, color: '#34D399' }} />
          <div style={{ color: '#CBD5E1', fontSize: 12, fontWeight: 700 }}>数据质量与审计</div>
          <div style={{ marginLeft: 'auto', color: '#475569', fontSize: 11, fontFamily: 'JetBrains Mono, monospace' }}>
            {analysis?.valuation_id || '--'}
          </div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 16, marginTop: 10 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: '#64748B', fontSize: 12 }}>
              <Database style={{ width: 12, height: 12 }} />数据源
            </div>
            <div style={{ color: '#94A3B8', fontSize: 12, lineHeight: 1.6, marginTop: 4 }}>
              {(analysis?.sources || []).length ? analysis?.sources?.join(' · ') : '--'}
            </div>
          </div>
          <div>
            <div style={{ color: '#64748B', fontSize: 12 }}>数据警告</div>
            <div style={{ color: '#94A3B8', fontSize: 12, lineHeight: 1.6, marginTop: 4 }}>
              {(analysis?.warnings || []).length ? analysis?.warnings?.slice(0, 8).join(' · ') : '未发现输入层警告'}
            </div>
          </div>
          <div>
            <div style={{ color: '#64748B', fontSize: 12 }}>估值权重与财报时点</div>
            <div style={{ color: '#94A3B8', fontSize: 12, lineHeight: 1.7, marginTop: 4 }}>
              绝对估值 {formatPercent(analysis?.consensus?.weights?.absolute)}
              {' · '}相对估值 {formatPercent(analysis?.consensus?.weights?.relative)}
              {' · '}财报口径 {analysis?.financial_quality?.point_in_time_quality || '--'}
              {' · '}财报可见日 {analysis?.financial_quality?.financial_as_of || '--'}
              {' · '}TTM {analysis?.financial_quality?.ttm_formula || '--'}
            </div>
          </div>
        </div>
      </section>
    </div>
  );
};

export default ValuationPanel;
