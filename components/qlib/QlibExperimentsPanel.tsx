import React from 'react';
import type { QlibWorkflowRun } from '../../lib/qlib-types';
import { statusLabel } from '../../lib/workbench-state.mjs';

const shortHash = (value?: string) => value ? `${value.slice(0, 10)}…` : '--';

const QlibExperimentsPanel: React.FC<{ workflows: QlibWorkflowRun[] }> = ({ workflows }) => <section>
  <div style={{ marginBottom: 10, color: '#71849A', fontSize: 11 }}>实验身份同时保留本地 ID、Qlib Experiment ID 和 Recorder ID；只有八项产物齐全才标记完整。</div>
  <div style={{ overflowX: 'auto', border: '1px solid #253247', borderRadius: 7 }}><table style={{ width: '100%', minWidth: 1120, borderCollapse: 'collapse' }}>
    <thead><tr style={{ background: '#111C2D' }}>{['本地实验 ID', 'Qlib Experiment ID', 'Recorder ID', '数据版本', '处理器 / 模型', 'Seed', 'Config Hash', '产物完整性', '路径状态', '状态'].map(item => <th key={item} style={{ padding: 10, textAlign: 'left', color: '#71849A', fontSize: 11 }}>{item}</th>)}</tr></thead>
    <tbody>{workflows.map(item => <tr key={item.id} style={{ borderTop: '1px solid #253247' }}>
      <td style={{ padding: 10, fontSize: 11 }}>{item.experiment_id}</td><td style={{ padding: 10, fontSize: 11 }}>{item.qlib_experiment_id}</td><td style={{ padding: 10, fontSize: 11 }}>{item.recorder_id}</td><td style={{ padding: 10, fontSize: 11 }}>{item.dataset_version}</td>
      <td style={{ padding: 10, fontSize: 11 }}>{item.handler} / {item.model_type}</td><td style={{ padding: 10, fontSize: 11 }}>{item.seed}</td><td title={item.config_hash} style={{ padding: 10, fontSize: 11 }}>{shortHash(item.config_hash)}</td>
      <td style={{ padding: 10, fontSize: 11, color: item.artifacts_complete ? '#34D399' : '#F87171' }}>{item.artifacts_complete ? '完整' : '不完整'}</td><td title={item.resolution_reason} style={{ padding: 10, fontSize: 11 }}>{item.path_state === 'active' ? '活动路径' : '历史记录，不是活动路径'}</td><td style={{ padding: 10, fontSize: 11 }}>{statusLabel(item.status)}</td>
    </tr>)}{!workflows.length && <tr><td colSpan={10} style={{ padding: 28, textAlign: 'center', color: '#66798F', fontSize: 12 }}>尚无官方 Workflow 记录</td></tr>}</tbody>
  </table></div>
</section>;

export default QlibExperimentsPanel;
