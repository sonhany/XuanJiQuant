import React from 'react';
import type { QlibDataset, QlibJob, QlibModel, QlibStatus } from '../../lib/qlib-types';
import { qlibJobLabel } from '../../lib/workbench-state.mjs';

type Props = { status: QlibStatus | null; datasets: QlibDataset[]; jobs: QlibJob[]; models: QlibModel[] };
const stateColor: Record<string, string> = { 可用: '#34D399', 受限: '#FBBF24', 运行中: '#67E8F9', 失败: '#F87171', 未接入: '#7F91A8' };

const QlibOverview: React.FC<Props> = ({ status, datasets, jobs, models }) => {
  const environment = status?.environment || {};
  const schedules = status?.schedule;
  return <section>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(185px, 1fr))', gap: 10 }}>
      {[
        ['活动数据根', status?.data_root || '--'],
        ['外部路径覆盖', status?.data_root_override ? '已启用（需审计）' : '未启用'],
        ['数据集', String(datasets.length)],
        ['模型', String(models.length)],
        ['活动任务', status?.active_job?.kind ? qlibJobLabel(status.active_job.kind) : '无'],
        ['连续计划成功', `周 ${schedules?.weekly?.consecutive_successes || 0} / 月 ${schedules?.monthly?.consecutive_successes || 0} / 季 ${schedules?.quarterly?.consecutive_successes || 0}`],
      ].map(([label, value]) => <div key={label} style={{ minHeight: 78, padding: 13, border: '1px solid #253247', borderRadius: 7, background: '#0D1625' }}>
        <div style={{ color: '#708399', fontSize: 11 }}>{label}</div><div style={{ marginTop: 9, fontSize: 13, fontWeight: 800, overflowWrap: 'anywhere' }}>{value}</div>
      </div>)}
    </div>
    <div style={{ marginTop: 14, padding: 16, border: '1px solid #253247', borderRadius: 7, background: '#0D1625' }}>
      <div style={{ fontSize: 14, fontWeight: 800, marginBottom: 11 }}>真实能力目录</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: 8 }}>
        {(status?.catalog || []).map(item => <div key={item.id} style={{ padding: 11, borderLeft: `2px solid ${stateColor[item.status]}`, background: '#111C2D' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}><strong style={{ fontSize: 12 }}>{item.name}</strong><span style={{ color: stateColor[item.status], fontSize: 11 }}>能力：{item.status}</span></div>
          <div style={{ marginTop: 6, color: '#71849A', fontSize: 11, lineHeight: 1.55 }}>{item.items.join(' · ')}</div>
        </div>)}
      </div>
    </div>
    <details open style={{ marginTop: 10, padding: 10, border: '1px solid #253247', borderRadius: 7, color: '#71849A', fontSize: 11 }}>
      <summary style={{ cursor: 'pointer', color: '#C9D5E4' }}>隔离环境版本</summary>
      <div style={{ marginTop: 8 }}>Python {String(environment.python_version || '--')} · pyqlib {String(environment.qlib_version || '--')} · LightGBM {String(environment.lightgbm_version || '--')} · XGBoost {String(environment.xgboost_version || '--')}</div>
      <div style={{ marginTop: 5 }}>控制索引：{status?.registry || '--'} · 已登记任务 {jobs.length} 个</div>
    </details>
  </section>;
};

export default QlibOverview;
