import React from 'react';
import { Play } from 'lucide-react';
import type { QlibJob, QlibQualityReport } from '../../lib/qlib-types';

type Props = { quality: QlibQualityReport | null; activeJob: QlibJob | null; runningAction: string; controlsEnabled: boolean; onAction: (action: string) => void };
const workflows = [
  { action: 'workflow_baseline', title: '周度固定基线', detail: 'Alpha158 + LightGBM；官方 Workflow、Recorder 与三类 Record。' },
  { action: 'workflow_monthly_walk_forward', title: 'Walk-Forward 六年基线', detail: '月度时间顺序滚动窗口；报告窗口通过率与最差窗口，固定参数，不接受任意模型 YAML。' },
  { action: 'workflow_quarterly_matrix', title: '季度固定矩阵', detail: 'Alpha158/Alpha360 与 LightGBM/XGBoost/Linear 的有界串行矩阵。' },
] as const;

const QlibTrainingPanel: React.FC<Props> = ({ quality, activeJob, runningAction, controlsEnabled, onAction }) => {
  const disabled = !controlsEnabled || !!activeJob || !!runningAction || !quality?.passed;
  return <section>
    {!quality?.passed && <div style={{ marginBottom: 12, padding: 11, border: '1px solid #78350F', borderRadius: 7, color: '#FCD34D', fontSize: 12 }}>六年数据质量门禁尚未通过，固定训练入口已关闭。</div>}
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 12 }}>
      {workflows.map(item => <div key={item.action} style={{ padding: 16, border: '1px solid #253247', borderRadius: 7, background: '#0D1625' }}>
        <Play size={20} color="#67E8F9" /><h3 style={{ fontSize: 15, margin: '12px 0 7px' }}>{item.title}</h3>
        <p style={{ color: '#7F91A8', fontSize: 12, lineHeight: 1.7, minHeight: 62 }}>{item.detail}</p>
        <button disabled={disabled} onClick={() => onAction(item.action)} style={{ height: 34, padding: '0 13px', border: 0, borderRadius: 7, background: '#0891B2', color: 'white', display: 'inline-flex', alignItems: 'center', gap: 7, fontWeight: 800 }}><Play size={15} />开始运行</button>
      </div>)}
    </div>
    <div style={{ marginTop: 12, color: '#71849A', fontSize: 11 }}>调度器只生成研究结果和 candidate，不会自动晋升为 shadow、paper 或实盘模型。</div>
  </section>;
};

export default QlibTrainingPanel;
