import React from 'react';
import { FlaskConical, Info, ShieldAlert } from 'lucide-react';

export const ResearchBoundary: React.FC<{
  kind?: 'research' | 'operations' | 'external';
  source: string;
  asOf?: string;
  error?: string;
}> = ({ kind = 'research', source, asOf, error }) => {
  const label = kind === 'research' ? '研究结果' : kind === 'operations' ? '系统运维' : '外部资讯';
  const Icon = error ? ShieldAlert : kind === 'research' ? FlaskConical : Info;
  return (
    <div style={{
      display: 'flex',
      alignItems: 'flex-start',
      gap: 9,
      padding: '9px 11px',
      border: `1px solid ${error ? '#F8717138' : '#334155'}`,
      borderRadius: 6,
      color: error ? '#FCA5A5' : '#94A3B8',
      background: '#0D1422',
      fontSize: 11,
      lineHeight: 1.6,
    }}>
      <Icon style={{ width: 14, height: 14, flex: '0 0 auto', marginTop: 1 }} />
      <div>
        <strong style={{ color: error ? '#FCA5A5' : '#CBD5E1' }}>{label}</strong>
        <span> · 来源：{source} · 截至：{asOf || '以结果内时间字段为准'}</span>
        <div>{error ? `数据不可用：${error}` : kind === 'research' ? '仅用于研究与模拟验证，不构成可直接执行的生产交易信号。' : kind === 'external' ? '正文、图示和行情受上游授权与发布时间影响；鉴权失败不等于内容为空。' : '控制操作需要本机授权并应保留审计记录。'}</div>
      </div>
    </div>
  );
};
