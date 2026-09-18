import React from 'react';
import { AlertTriangle, CheckCircle2, Clock3, Loader2, ShieldAlert } from 'lucide-react';

type Tone = 'ok' | 'warn' | 'error' | 'neutral';

const tones: Record<Tone, { color: string; bg: string; border: string }> = {
  ok: { color: '#4ADE80', bg: '#4ADE8012', border: '#4ADE8038' },
  warn: { color: '#FBBF24', bg: '#FBBF2412', border: '#FBBF2438' },
  error: { color: '#F87171', bg: '#F8717112', border: '#F8717138' },
  neutral: { color: '#94A3B8', bg: '#94A3B80D', border: '#94A3B826' },
};

export const StatusBadge: React.FC<{
  label: string;
  tone?: Tone;
  title?: string;
}> = ({ label, tone = 'neutral', title }) => {
  const palette = tones[tone];
  return (
    <span
      title={title}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        minHeight: 24,
        padding: '3px 8px',
        borderRadius: 6,
        border: `1px solid ${palette.border}`,
        background: palette.bg,
        color: palette.color,
        fontSize: 11,
        fontWeight: 700,
        whiteSpace: 'nowrap',
      }}
    >
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: palette.color }} />
      {label}
    </span>
  );
};

export const AsyncState: React.FC<{
  state: 'loading' | 'error' | 'unknown' | 'empty';
  message?: string;
  compact?: boolean;
}> = ({ state, message, compact = false }) => {
  const icon = state === 'loading'
    ? <Loader2 style={{ width: 16, height: 16, animation: 'spin 1s linear infinite' }} />
    : state === 'error'
      ? <ShieldAlert style={{ width: 16, height: 16 }} />
      : state === 'unknown'
        ? <AlertTriangle style={{ width: 16, height: 16 }} />
        : <Clock3 style={{ width: 16, height: 16 }} />;
  const text = message || ({
    loading: '正在读取权威状态',
    error: '状态读取失败，相关操作已停用',
    unknown: '尚无可验证数据',
    empty: '当前没有记录',
  } as const)[state];
  return (
    <div style={{
      minHeight: compact ? 40 : 88,
      display: 'flex',
      alignItems: 'center',
      justifyContent: compact ? 'flex-start' : 'center',
      gap: 9,
      padding: compact ? '8px 10px' : 18,
      border: '1px solid #273244',
      borderRadius: 8,
      background: '#101827',
      color: state === 'error' ? '#FCA5A5' : '#94A3B8',
      fontSize: 12,
    }}>
      {icon}
      <span>{text}</span>
    </div>
  );
};

export const TruthBar: React.FC<{
  data: any;
  loading: boolean;
  error: string;
}> = ({ data, loading, error }) => {
  const automaticExecution = data?.automatic_execution;
  const risk = data?.risk;
  const asOf = data?.as_of || data?.freshness?.as_of;
  return (
    <div className="workbench-truth-bar" style={{
      minHeight: 38,
      display: 'flex',
      alignItems: 'center',
      gap: 8,
      padding: '6px 16px',
      borderBottom: '1px solid #1E293B',
      background: '#0B1220',
      overflowX: 'auto',
    }}>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7, color: '#CBD5E1', fontSize: 11, fontWeight: 800, whiteSpace: 'nowrap' }}>
        {error ? <ShieldAlert style={{ width: 14, height: 14, color: '#F87171' }} /> : <CheckCircle2 style={{ width: 14, height: 14, color: '#38BDF8' }} />}
        权威状态
      </span>
      {loading && !data ? <StatusBadge label="读取中" tone="neutral" /> : null}
      {error ? <StatusBadge label="状态不可用" tone="error" title={error} /> : null}
      {!error && data ? (
        <>
          <StatusBadge label={automaticExecution?.enabled ? '自动模拟交易已启用' : '自动模拟交易已关闭'} tone={automaticExecution?.enabled ? 'warn' : 'neutral'} />
          <StatusBadge
            label={`组合风险 ${risk?.level || '未知'}`}
            tone={risk?.state === 'ok' ? 'ok' : risk?.state === 'warn' ? 'warn' : 'error'}
          />
          <StatusBadge label="只读账本" tone="neutral" title={automaticExecution?.reason} />
          <span style={{ marginLeft: 'auto', color: '#64748B', fontSize: 12, whiteSpace: 'nowrap' }}>
            截至 {asOf ? new Date(asOf).toLocaleTimeString('zh-CN', { hour12: false }) : '--'}
          </span>
        </>
      ) : null}
    </div>
  );
};
