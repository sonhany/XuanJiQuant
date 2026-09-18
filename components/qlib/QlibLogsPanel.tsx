import React, { useEffect, useRef } from 'react';
import { Square } from 'lucide-react';
import type { QlibJob } from '../../lib/qlib-types';
import { qlibJobLabel, statusLabel } from '../../lib/workbench-state.mjs';

type Props = { jobs: QlibJob[]; activeJob: QlibJob | null; lines: string[]; controlsEnabled: boolean; onAction: (action: string, payload: Record<string, unknown>) => void };

const QlibLogsPanel: React.FC<Props> = ({ jobs, activeJob, lines, controlsEnabled, onAction }) => {
  const logRef = useRef<HTMLDivElement>(null);
  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, [lines]);
  const displayJob = activeJob || jobs[0] || null;
  const progress = Number(displayJob?.progress || 0) * 100;
  return <section style={{ display: 'grid', gridTemplateColumns: 'minmax(360px, 1.2fr) minmax(320px, 1fr)', gap: 12 }}>
    <div style={{ overflowX: 'auto', border: '1px solid #253247', borderRadius: 7 }}><table style={{ width: '100%', minWidth: 760, borderCollapse: 'collapse' }}>
      <thead><tr style={{ background: '#111C2D' }}>{['任务', '中文状态', '阶段', '进度', '心跳时间', '说明'].map(item => <th key={item} style={{ padding: 10, textAlign: 'left', color: '#71849A', fontSize: 11 }}>{item}</th>)}</tr></thead>
      <tbody>{jobs.map(job => <tr key={job.id} style={{ borderTop: '1px solid #253247' }}><td style={{ padding: 10, fontSize: 11 }}>{qlibJobLabel(job.kind)}</td><td style={{ padding: 10, fontSize: 11 }}>{statusLabel(job.status)}</td><td style={{ padding: 10, fontSize: 11 }}>{qlibJobLabel(job.stage)}</td><td style={{ padding: 10, fontSize: 11 }}>{(Number(job.progress || 0) * 100).toFixed(1)}%</td><td style={{ padding: 10, fontSize: 11 }}>{job.heartbeat_at || '--'}</td><td style={{ padding: 10, fontSize: 11 }}>{job.message || '--'}</td></tr>)}
      {!jobs.length && <tr><td colSpan={6} style={{ padding: 28, textAlign: 'center', color: '#66798F', fontSize: 12 }}>尚无任务记录</td></tr>}</tbody>
    </table></div>
    <div style={{ minHeight: 390, padding: 13, border: '1px solid #253247', borderRadius: 7, background: '#080F1B', display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}><div><strong style={{ fontSize: 12 }}>{activeJob ? '活动任务输出' : '最近任务输出'}</strong>{displayJob && <div style={{ marginTop: 5, color: '#8CA3BA', fontSize: 11 }}>当前进度 {progress.toFixed(1)}% · {statusLabel(displayJob.status)} · {displayJob.message || qlibJobLabel(displayJob.kind)}</div>}</div>
        <button title="取消活动任务" disabled={!controlsEnabled || !activeJob} onClick={() => activeJob && onAction('cancel_job', { job_id: activeJob.id })} style={{ width: 30, height: 30, border: '1px solid #4B5563', borderRadius: 6, background: '#172033', color: '#FCA5A5', display: 'grid', placeItems: 'center' }}><Square size={13} /></button>
      </div>
      <div ref={logRef} style={{ minHeight: 0, flex: 1, overflow: 'auto' }}><pre style={{ margin: 0, color: '#9FB2C7', fontSize: 11, lineHeight: 1.65, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{lines.length ? lines.join('\n') : '当前没有可显示的任务日志。'}</pre></div>
    </div>
  </section>;
};

export default QlibLogsPanel;
