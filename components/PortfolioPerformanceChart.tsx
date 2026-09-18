import React, { useMemo } from 'react';
import { formatOptionalPercent, normalizePerformanceSeries } from '../lib/ui-workbench.mjs';

type PerformancePoint = {
  date?: string;
  equity?: number;
  drawdown_pct?: number;
  drawdownPct?: number;
};

const WIDTH = 820;
const HEIGHT = 236;
const PAD_X = 48;
const NAV_TOP = 22;
const NAV_BOTTOM = 148;
const DD_TOP = 168;
const DD_BOTTOM = 214;

const pct = (value: number) => `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`;

export const PortfolioPerformanceChart: React.FC<{
  points?: PerformancePoint[];
  initialEquity?: number | null;
  benchmarkName?: string;
  benchmarkReturnPct?: number | null;
}> = ({ points = [], initialEquity, benchmarkName = '沪深300', benchmarkReturnPct }) => {
  const series = useMemo(
    () => normalizePerformanceSeries(points, initialEquity),
    [points, initialEquity],
  );

  if (series.length < 2) {
    return (
      <div className="performance-chart-empty">
        连续净值快照不足，至少形成两个交易日快照后展示趋势。
      </div>
    );
  }

  const xAt = (index: number) => PAD_X + (index / (series.length - 1)) * (WIDTH - PAD_X * 2);
  const navValues = series.map((point: any) => point.nav);
  const navMinRaw = Math.min(...navValues, 1);
  const navMaxRaw = Math.max(...navValues, 1);
  const navPadding = Math.max((navMaxRaw - navMinRaw) * 0.16, 0.004);
  const navMin = navMinRaw - navPadding;
  const navMax = navMaxRaw + navPadding;
  const yNav = (value: number) => NAV_BOTTOM - ((value - navMin) / (navMax - navMin)) * (NAV_BOTTOM - NAV_TOP);
  const ddMin = Math.min(...series.map((point: any) => point.drawdownPct), -0.5);
  const yDrawdown = (value: number) => DD_TOP + ((0 - value) / (0 - ddMin)) * (DD_BOTTOM - DD_TOP);
  const navPath = series
    .map((point: any, index: number) => `${index ? 'L' : 'M'} ${xAt(index).toFixed(1)} ${yNav(point.nav).toFixed(1)}`)
    .join(' ');
  const drawdownPath = series
    .map((point: any, index: number) => `${index ? 'L' : 'M'} ${xAt(index).toFixed(1)} ${yDrawdown(point.drawdownPct).toFixed(1)}`)
    .join(' ');
  const drawdownArea = `${drawdownPath} L ${xAt(series.length - 1).toFixed(1)} ${DD_TOP} L ${PAD_X} ${DD_TOP} Z`;
  const finalReturn = (series[series.length - 1].nav - 1) * 100;
  const maxDrawdown = Math.min(...series.map((point: any) => point.drawdownPct));
  const benchmarkText = formatOptionalPercent(benchmarkReturnPct);

  return (
    <div className="performance-chart">
      <div className="performance-chart-legend">
        <span><i className="legend-line" />组合净值 {pct(finalReturn)}</span>
        <span><i className="legend-area" />最大回撤 {maxDrawdown.toFixed(2)}%</span>
        <span className="benchmark-label">{benchmarkName} 同期 {benchmarkText}</span>
      </div>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={`组合净值从 ${series[0].nav.toFixed(4)} 变化至 ${series[series.length - 1].nav.toFixed(4)}，最大回撤 ${maxDrawdown.toFixed(2)}%`}
        preserveAspectRatio="none"
      >
        {[0, 0.5, 1].map((ratio) => {
          const value = navMax - (navMax - navMin) * ratio;
          const y = NAV_TOP + (NAV_BOTTOM - NAV_TOP) * ratio;
          return (
            <g key={ratio}>
              <line x1={PAD_X} y1={y} x2={WIDTH - PAD_X} y2={y} stroke="#223047" strokeWidth="1" />
              <text x="4" y={y + 4} fill="#94A3B8" fontSize="11" fontFamily="JetBrains Mono, Consolas, monospace">
                {value.toFixed(3)}
              </text>
            </g>
          );
        })}
        <line x1={PAD_X} y1={yNav(1)} x2={WIDTH - PAD_X} y2={yNav(1)} stroke="#64748B" strokeDasharray="4 5" opacity="0.72" />
        <path d={drawdownArea} fill="rgba(248,113,113,0.14)" />
        <path d={drawdownPath} fill="none" stroke="#F87171" strokeWidth="1.25" />
        <path d={navPath} fill="none" stroke="#38BDF8" strokeWidth="2.25" vectorEffect="non-scaling-stroke" />
        {series.map((point: any, index: number) => (
          <circle key={`${point.date}-${index}`} cx={xAt(index)} cy={yNav(point.nav)} r="7" fill="transparent">
            <title>{`${point.date} · 净值 ${point.nav.toFixed(4)} · 权益 ¥${point.equity.toLocaleString('zh-CN')} · 回撤 ${point.drawdownPct.toFixed(2)}%`}</title>
          </circle>
        ))}
        <text x={PAD_X} y={HEIGHT - 4} fill="#94A3B8" fontSize="11">{series[0].date}</text>
        <text x={WIDTH - PAD_X} y={HEIGHT - 4} fill="#94A3B8" fontSize="11" textAnchor="end">{series[series.length - 1].date}</text>
        <text x="4" y={DD_TOP + 4} fill="#94A3B8" fontSize="11">0%</text>
        <text x="4" y={DD_BOTTOM} fill="#F87171" fontSize="11">{ddMin.toFixed(1)}%</text>
      </svg>
      <div className="performance-chart-note">
        上区为执行账本净值，下区为相对历史峰值回撤；基准缺少共同起点时不绘制推测曲线。
      </div>
      <style>{`
        .performance-chart { margin-top: 10px; padding: 12px 12px 9px; border: 1px solid #223047; border-radius: 6px; background: #0B1220; }
        .performance-chart svg { width: 100%; height: 236px; display: block; }
        .performance-chart-legend { min-height: 28px; display: flex; align-items: center; flex-wrap: wrap; gap: 10px 18px; color: #CBD5E1; font-size: var(--font-meta); }
        .performance-chart-legend span { display: inline-flex; align-items: center; gap: 7px; }
        .performance-chart-legend i { width: 18px; display: inline-block; }
        .legend-line { height: 2px; background: #38BDF8; }
        .legend-area { height: 8px; border: 1px solid rgba(248,113,113,.62); background: rgba(248,113,113,.14); }
        .performance-chart-legend .benchmark-label { margin-left: auto; color: #94A3B8; }
        .performance-chart-note, .performance-chart-empty { color: #94A3B8; font-size: var(--font-meta); line-height: 1.55; }
        .performance-chart-note { padding: 5px 4px 0; }
        .performance-chart-empty { min-height: 118px; display: flex; align-items: center; justify-content: center; margin-top: 10px; border: 1px dashed #334155; border-radius: 6px; background: #0B1220; text-align: center; }
        @media (max-width: 620px) {
          .performance-chart { padding: 10px 8px 8px; }
          .performance-chart svg { height: 206px; }
          .performance-chart-legend .benchmark-label { width: 100%; margin-left: 0; }
        }
      `}</style>
    </div>
  );
};

export default PortfolioPerformanceChart;
