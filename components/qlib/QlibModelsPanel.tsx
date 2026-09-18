import React from 'react';
import type { QlibModel, QlibWorkflowRun } from '../../lib/qlib-types';
import { statusLabel } from '../../lib/workbench-state.mjs';

type Props = { models: QlibModel[]; workflows: QlibWorkflowRun[]; runningAction: string; controlsEnabled: boolean; onAction: (action: string, payload: Record<string, unknown>) => void };

const QlibModelsPanel: React.FC<Props> = ({ models, workflows, runningAction, controlsEnabled, onAction }) => <section>
  <div style={{ marginBottom: 10, color: '#71849A', fontSize: 11 }}>只有统一 gate 为 candidate、模型与 Recorder 产物哈希复核一致时，才允许人工生成无订单影子信号。</div>
  <div style={{ display: 'grid', gap: 9 }}>{models.map(model => {
    const workflow = workflows.find(item => item.experiment_id === model.experiment_id);
    const gate = workflow?.gate;
    const promotable = model.status === 'candidate' && gate?.status === 'candidate' && workflow?.artifacts_complete;
    return <div key={model.id} style={{ padding: 13, border: '1px solid #253247', borderRadius: 7, background: '#0D1625', display: 'grid', gridTemplateColumns: 'minmax(170px, 1.4fr) repeat(3, minmax(120px, 1fr)) auto', gap: 12, alignItems: 'center' }}>
      <div><strong style={{ fontSize: 12 }}>{model.id}</strong><div style={{ marginTop: 5, color: '#71849A', fontSize: 11 }}>{model.model_type} · {model.sha256 ? `${model.sha256.slice(0, 12)}…` : '--'}</div></div>
      <div style={{ fontSize: 11 }}><span style={{ color: '#71849A' }}>模型状态</span><div style={{ marginTop: 5 }}>{statusLabel(model.status)}</div></div>
      <div style={{ fontSize: 11 }}><span style={{ color: '#71849A' }}>统一门禁</span><div style={{ marginTop: 5 }}>{gate ? `${statusLabel(gate.status)} · ${gate.gate_version}` : '尚未计算'}</div></div>
      <div style={{ fontSize: 11 }}><span style={{ color: '#71849A' }}>Recorder</span><div style={{ marginTop: 5 }}>{workflow?.artifacts_complete ? '产物完整' : '产物不完整'}</div></div>
      <button disabled={!controlsEnabled || !!runningAction || !promotable} onClick={() => onAction('promote_shadow', { model_id: model.id })} style={{ height: 32, padding: '0 11px', border: '1px solid #475569', borderRadius: 6, background: '#172235', color: '#DCE6F2', fontSize: 11, fontWeight: 700 }}>人工晋升影子</button>
    </div>;
  })}{!models.length && <div style={{ padding: 28, textAlign: 'center', color: '#66798F', fontSize: 12 }}>尚无模型记录</div>}</div>
</section>;

export default QlibModelsPanel;
