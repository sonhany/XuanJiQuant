import React from 'react';
import { DatabaseZap, Download, FileOutput } from 'lucide-react';
import type { QlibDataset, QlibJob, QlibQualityReport } from '../../lib/qlib-types';
import { qlibDatasetState, qlibJobLabel, statusLabel } from '../../lib/workbench-state.mjs';

type Props = {
  datasets: QlibDataset[]; quality: QlibQualityReport | null; qualityReports: QlibQualityReport[];
  activeJob: QlibJob | null; runningAction: string; controlsEnabled: boolean;
  onAction: (action: string, payload?: Record<string, unknown>) => void;
};
const buttonStyle: React.CSSProperties = { height: 34, padding: '0 12px', border: '1px solid #334155', borderRadius: 7, background: '#142033', color: '#D7E2EF', display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 12, fontWeight: 700 };

const QlibDataPanel: React.FC<Props> = ({ datasets, quality, qualityReports, activeJob, runningAction, controlsEnabled, onAction }) => {
  const disabled = !controlsEnabled || !!activeJob || !!runningAction;
  const metrics = quality?.metrics || {};
  return <section>
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 14 }}>
      <button style={buttonStyle} disabled={disabled} onClick={() => onAction('setup')}><DatabaseZap size={15} />检查目录</button>
      <button style={buttonStyle} disabled={disabled} onClick={() => onAction('collect_six_years')}><Download size={15} />补齐六年原始行情</button>
      <button style={buttonStyle} disabled={disabled} onClick={() => onAction('quality_six_years')}><DatabaseZap size={15} />运行数据质量门禁</button>
      <button style={buttonStyle} disabled={disabled || !quality?.passed} onClick={() => onAction('export_six_years')}><FileOutput size={15} />导出六年 Qlib bin</button>
      {runningAction && <span style={{ color: '#67E8F9', fontSize: 12, alignSelf: 'center' }}>正在提交：{qlibJobLabel(runningAction)}</span>}
    </div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 9, marginBottom: 14 }}>
      {[
        ['数据版本', quality?.dataset_version || '--'],
        ['质量门禁版本', quality?.gate_version || '--'],
        ['门禁状态', quality ? (quality.passed ? '通过' : '未通过') : '未执行'],
        ['点时状态覆盖率', metrics.completed ? `${((1 - Number(metrics.unknown_st_samples || 0) / Math.max(1, Number(metrics.completed))) * 100).toFixed(2)}%` : '--'],
        ['复权校验异常', String(metrics.non_positive_factors ?? '--')],
        ['历史退市股票', String(metrics.delisted_instruments ?? '已纳入股票池审计')],
        ['ST 未知区间', String(metrics.unknown_st_samples ?? '--')],
        ['失败原因', quality?.reason_codes?.length ? quality.reason_codes.join('、') : '无'],
      ].map(([label, value]) => <div key={label} style={{ padding: 12, border: '1px solid #253247', borderRadius: 7, background: '#0D1625' }}><div style={{ color: '#71849A', fontSize: 11 }}>{label}</div><div style={{ marginTop: 7, fontSize: 13, fontWeight: 800, overflowWrap: 'anywhere' }}>{value}</div></div>)}
    </div>
    <div style={{ color: '#71849A', fontSize: 11, marginBottom: 8 }}>历史质量报告：{qualityReports.length} 份。旧路径若出现，只作为“历史记录，不是活动路径”。</div>
    <div style={{ overflowX: 'auto', border: '1px solid #253247', borderRadius: 7 }}><table style={{ width: '100%', minWidth: 880, borderCollapse: 'collapse' }}>
      <thead><tr style={{ background: '#111C2D' }}>{['数据集', '类型', '状态', '起止日期', '最新交易日', '股票数', '行数', '覆盖率'].map(item => <th key={item} style={{ padding: 10, textAlign: 'left', color: '#71849A', fontSize: 11 }}>{item}</th>)}</tr></thead>
      <tbody>{datasets.map(item => { const availability = qlibDatasetState(item); return <tr key={item.id} style={{ borderTop: '1px solid #253247' }}>
        <td style={{ padding: 10, fontSize: 12, fontWeight: 700 }}>{item.id}</td><td style={{ padding: 10, fontSize: 12 }}>{qlibJobLabel(item.kind)}</td><td style={{ padding: 10, fontSize: 12 }}>{statusLabel(item.status)} · {availability.label}</td>
        <td style={{ padding: 10, fontSize: 12 }}>{item.start_date || '--'} 至 {item.end_date || '--'}</td><td style={{ padding: 10, fontSize: 12 }}>{item.latest_date || '--'}</td><td style={{ padding: 10, fontSize: 12 }}>{item.instruments || 0}</td><td style={{ padding: 10, fontSize: 12 }}>{item.rows || 0}</td><td style={{ padding: 10, fontSize: 12 }}>{(Number(item.coverage || 0) * 100).toFixed(2)}%</td>
      </tr>; })}{!datasets.length && <tr><td colSpan={8} style={{ padding: 28, color: '#66798F', textAlign: 'center', fontSize: 12 }}>尚未登记 Qlib 数据集</td></tr>}</tbody>
    </table></div>
  </section>;
};

export default QlibDataPanel;
