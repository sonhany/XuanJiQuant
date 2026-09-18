import React from 'react';
import type { QlibBacktestResult, QlibWorkflowRun } from '../../lib/qlib-types';
import { qlibMetric } from '../../lib/qlib-types';

const percent = (value: number | null) => value === null ? '--' : `${(value * 100).toFixed(2)}%`;
const decimal = (value: number | null) => value === null ? '--' : value.toFixed(3);

const QlibBacktestPanel: React.FC<{ workflows: QlibWorkflowRun[]; backtests: QlibBacktestResult[] }> = ({ workflows, backtests }) => <section>
  <div style={{ marginBottom: 10, color: '#71849A', fontSize: 11 }}>Qlib 官方回测与 A 股规则回测按同一 Signal Hash 并排核对；费用、涨跌停、停牌和成交约束差异需要人工审查。</div>
  <div style={{ overflowX: 'auto', border: '1px solid #253247', borderRadius: 7 }}><table style={{ width: '100%', minWidth: 1050, borderCollapse: 'collapse' }}>
    <thead><tr style={{ background: '#111C2D' }}>{['Workflow', '回测引擎', 'Signal Hash', 'Rank IC / ICIR', '年化收益', 'Sharpe / 信息比率', '最大回撤', '换手', '成本', '差异审查'].map(item => <th key={item} style={{ padding: 10, textAlign: 'left', color: '#71849A', fontSize: 11 }}>{item}</th>)}</tr></thead>
    <tbody>{backtests.map(item => {
      const workflow = workflows.find(value => value.id === item.workflow_run_id);
      const metrics = item.metrics || {};
      return <tr key={item.id} style={{ borderTop: '1px solid #253247' }}>
        <td style={{ padding: 10, fontSize: 11 }}>{workflow ? `${workflow.handler} / ${workflow.model_type}` : item.workflow_run_id}</td><td style={{ padding: 10, fontSize: 11 }}>{item.engine === 'qlib_official' ? 'Qlib 官方回测' : 'A 股规则回测'}</td><td title={item.signal_hash} style={{ padding: 10, fontSize: 11 }}>{item.signal_hash ? `${item.signal_hash.slice(0, 12)}…` : '--'}</td><td style={{ padding: 10, fontSize: 11 }}>{decimal(qlibMetric(metrics, 'rank_ic'))} / {decimal(qlibMetric(metrics, 'rank_icir') ?? qlibMetric(metrics, 'icir'))}</td>
        <td style={{ padding: 10, fontSize: 11 }}>{percent(qlibMetric(metrics, 'annualized_return') ?? qlibMetric(metrics, 'official_annualized_return'))}</td><td style={{ padding: 10, fontSize: 11 }}>{decimal(qlibMetric(metrics, 'sharpe') ?? qlibMetric(metrics, 'information_ratio'))}</td><td style={{ padding: 10, fontSize: 11 }}>{percent(qlibMetric(metrics, 'max_drawdown') ?? qlibMetric(metrics, 'official_max_drawdown'))}</td><td style={{ padding: 10, fontSize: 11 }}>{percent(qlibMetric(metrics, 'turnover'))}</td><td style={{ padding: 10, fontSize: 11 }}>{percent(qlibMetric(metrics, 'cost'))}</td><td style={{ padding: 10, fontSize: 11 }}>{String(item.config?.divergence_review || '待与同信号另一引擎核对')}</td>
      </tr>;
    })}{!backtests.length && <tr><td colSpan={10} style={{ padding: 28, textAlign: 'center', color: '#66798F', fontSize: 12 }}>尚无双回测记录</td></tr>}</tbody>
  </table></div>
</section>;

export default QlibBacktestPanel;
