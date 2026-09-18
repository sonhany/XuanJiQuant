import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity, BarChart3, BookOpenCheck, Boxes, BrainCircuit, Database,
  FileClock, FlaskConical, RefreshCw, ShieldCheck,
} from 'lucide-react';
import QlibOverview from './qlib/QlibOverview';
import QlibDataPanel from './qlib/QlibDataPanel';
import QlibTrainingPanel from './qlib/QlibTrainingPanel';
import QlibExperimentsPanel from './qlib/QlibExperimentsPanel';
import QlibModelsPanel from './qlib/QlibModelsPanel';
import QlibBacktestPanel from './qlib/QlibBacktestPanel';
import QlibLogsPanel from './qlib/QlibLogsPanel';
import { ResearchBoundary } from './ResearchBoundary';
import type {
  QlibBacktestResult, QlibDataset, QlibExperiment, QlibJob, QlibModel,
  QlibQualityReport, QlibResearchState, QlibStatus, QlibWorkflowRun,
} from '../lib/qlib-types';

const API_BASE = import.meta.env?.VITE_API_BASE || '';
const API_TOKEN = import.meta.env?.VITE_XUANJI_API_TOKEN || '';

const tabs = [
  { id: 'overview', label: '研究总览', icon: Activity },
  { id: 'data', label: '数据准备', icon: Database },
  { id: 'training', label: '模型训练', icon: BrainCircuit },
  { id: 'experiments', label: '实验记录', icon: FlaskConical },
  { id: 'models', label: '模型仓库', icon: Boxes },
  { id: 'backtest', label: '回测评估', icon: BarChart3 },
  { id: 'logs', label: '任务日志', icon: FileClock },
] as const;

type TabId = typeof tabs[number]['id'];
type ItemResponse<T> = { items: T[] };
type ScheduleResponse = { modes: QlibStatus['schedule'] };

const emptyState: QlibResearchState = {
  status: null,
  datasets: [],
  jobs: [],
  experiments: [],
  models: [],
  reports: [],
  qualityReports: [],
  workflowRuns: [],
  backtests: [],
};

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

const QlibResearchPanel: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabId>('overview');
  const [state, setState] = useState<QlibResearchState>(emptyState);
  const [jobLog, setJobLog] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [runningAction, setRunningAction] = useState('');
  const [error, setError] = useState('');

  const request = useCallback(async <T,>(action: string, payload: Record<string, unknown> = {}): Promise<T> => {
    const response = await fetch(`${API_BASE}/api/qlib`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(API_TOKEN ? { 'X-XuanJi-Token': API_TOKEN } : {}),
      },
      body: JSON.stringify({ action, ...payload }),
    });
    const result = await response.json() as { success?: boolean; data?: T; error?: string };
    if (!response.ok || !result.success || result.data === undefined) {
      throw new Error(result.error || `Qlib 请求失败（${response.status}）`);
    }
    return result.data;
  }, []);

  const fetchJobLog = useCallback(async (status: QlibStatus, jobs: QlibJob[]) => {
    const job = status.active_job || jobs.find(item => ['queued', 'running', 'cancelling'].includes(item.status));
    const logJob = job || jobs[0];
    if (!logJob?.id) {
      setJobLog([]);
      return;
    }
    const log = await request<{ lines: string[] }>('job_log', { job_id: logJob.id, tail: 400 });
    setJobLog(log.lines || []);
  }, [request]);

  const refresh = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    setError('');
    try {
      const [status, datasets, jobs, experiments, models, reports, quality, workflows, backtests, schedule] = await Promise.all([
        request<QlibStatus>('status'),
        request<ItemResponse<QlibDataset>>('datasets', { limit: 100 }),
        request<ItemResponse<QlibJob>>('jobs', { limit: 100 }),
        request<ItemResponse<QlibExperiment>>('experiments', { limit: 100 }),
        request<ItemResponse<QlibModel>>('models', { limit: 100 }),
        request<ItemResponse<Record<string, unknown>>>('reports', { limit: 100 }),
        request<ItemResponse<QlibQualityReport>>('quality_reports', { limit: 100 }),
        request<ItemResponse<QlibWorkflowRun>>('workflow_runs', { limit: 100 }),
        request<ItemResponse<QlibBacktestResult>>('backtests', { limit: 200 }),
        request<ScheduleResponse>('schedule_status'),
      ]);
      const mergedStatus = { ...status, schedule: schedule.modes || status.schedule };
      setState({
        status: mergedStatus,
        datasets: datasets.items || [],
        jobs: jobs.items || [],
        experiments: experiments.items || [],
        models: models.items || [],
        reports: reports.items || [],
        qualityReports: quality.items || [],
        workflowRuns: workflows.items || [],
        backtests: backtests.items || [],
      });
      await fetchJobLog(mergedStatus, jobs.items || []);
    } catch (caught) {
      setError(errorMessage(caught, 'Qlib 状态读取失败'));
    } finally {
      if (!quiet) setLoading(false);
    }
  }, [fetchJobLog, request]);

  const refreshRuntime = useCallback(async () => {
    try {
      const [status, jobs] = await Promise.all([
        request<QlibStatus>('status'),
        request<ItemResponse<QlibJob>>('jobs', { limit: 100 }),
      ]);
      const nextJobs = jobs.items || [];
      setState(current => ({ ...current, status, jobs: nextJobs }));
      await fetchJobLog(status, nextJobs);
    } catch (caught) {
      setError(errorMessage(caught, 'Qlib 状态刷新失败'));
    }
  }, [fetchJobLog, request]);

  useEffect(() => { void refresh(); }, [refresh]);

  const activeJob = useMemo(
    () => state.status?.active_job || state.jobs.find(job => ['queued', 'running', 'cancelling'].includes(job.status)) || null,
    [state.jobs, state.status],
  );

  useEffect(() => {
    if (!activeJob) return undefined;
    const timer = setInterval(() => { void refreshRuntime(); }, 5_000);
    return () => clearInterval(timer);
  }, [activeJob?.id, refreshRuntime]);

  const runAction = useCallback(async (action: string, payload: Record<string, unknown> = {}) => {
    if (!API_TOKEN) {
      setError('未配置 VITE_XUANJI_API_TOKEN，控制操作已禁用。');
      return;
    }
    setRunningAction(action);
    setError('');
    try {
      await request<Record<string, unknown>>(action, payload);
      await refresh(true);
    } catch (caught) {
      setError(errorMessage(caught, '任务提交失败'));
    } finally {
      setRunningAction('');
    }
  }, [refresh, request]);

  const content: Record<TabId, React.ReactNode> = {
    overview: <QlibOverview status={state.status} datasets={state.datasets} jobs={state.jobs} models={state.models} />,
    data: <QlibDataPanel datasets={state.datasets} quality={state.status?.six_year_quality || null} qualityReports={state.qualityReports} activeJob={activeJob} runningAction={runningAction} controlsEnabled={!!API_TOKEN} onAction={runAction} />,
    training: <QlibTrainingPanel quality={state.status?.six_year_quality || null} activeJob={activeJob} runningAction={runningAction} controlsEnabled={!!API_TOKEN} onAction={runAction} />,
    experiments: <QlibExperimentsPanel workflows={state.workflowRuns} />,
    models: <QlibModelsPanel models={state.models} workflows={state.workflowRuns} runningAction={runningAction} controlsEnabled={!!API_TOKEN} onAction={runAction} />,
    backtest: <QlibBacktestPanel workflows={state.workflowRuns} backtests={state.backtests} />,
    logs: <QlibLogsPanel jobs={state.jobs} activeJob={activeJob} lines={jobLog} controlsEnabled={!!API_TOKEN} onAction={runAction} />,
  };

  return (
    <div style={{ color: '#E5EDF7', minHeight: 'calc(100vh - 96px)' }}>
      <ResearchBoundary source="独立数据仓库：Qlib 数据、Recorder 与实验控制索引" asOf={state.status?.checked_at} error={error} />
      <header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 20, marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ width: 40, height: 40, border: '1px solid #334155', borderRadius: 8, display: 'grid', placeItems: 'center', background: '#111827' }}>
            <BookOpenCheck size={20} color="#67E8F9" />
          </div>
          <div>
            <h2 style={{ margin: 0, fontSize: 20 }}>Qlib 量化研究</h2>
            <div style={{ marginTop: 4, color: '#7F91A8', fontSize: 12 }}>
              六年日频 A 股 · 官方 Workflow · 双回测 · 统一晋升门禁
            </div>
          </div>
        </div>
        <button onClick={() => void refresh()} disabled={loading} title="刷新 Qlib 状态" style={{ width: 36, height: 36, border: '1px solid #334155', borderRadius: 7, background: '#111827', color: '#CBD5E1', display: 'grid', placeItems: 'center', cursor: 'pointer' }}>
          <RefreshCw size={16} className={loading ? 'spin' : ''} />
        </button>
      </header>

      <nav style={{ display: 'flex', gap: 4, overflowX: 'auto', borderBottom: '1px solid #253247', marginBottom: 16 }}>
        {tabs.map(({ id, label, icon: Icon }) => {
          const selected = activeTab === id;
          return <button key={id} onClick={() => setActiveTab(id)} style={{ height: 40, padding: '0 14px', border: 0, borderBottom: selected ? '2px solid #67E8F9' : '2px solid transparent', background: selected ? 'rgba(103,232,249,0.08)' : 'transparent', color: selected ? '#E6FBFF' : '#8091A7', display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 12, fontWeight: 700, whiteSpace: 'nowrap', cursor: 'pointer' }}>
            <Icon size={15} /> {label}
          </button>;
        })}
      </nav>

      {error && <div style={{ border: '1px solid #7F1D1D', background: 'rgba(127,29,29,0.18)', color: '#FECACA', borderRadius: 7, padding: '10px 12px', marginBottom: 14, fontSize: 12 }}>{error}</div>}
      <main style={{ minHeight: 520 }}>{content[activeTab]}</main>
      <footer style={{ marginTop: 18, paddingTop: 12, borderTop: '1px solid #253247', display: 'flex', gap: 8, color: '#7F91A8', fontSize: 12, lineHeight: 1.6 }}>
        <ShieldCheck size={15} color="#34D399" style={{ flex: '0 0 auto', marginTop: 2 }} />
        Qlib 模型是离线研究产物，调度器最多生成 candidate；只有人工复核后才能进入无订单影子信号，不能绕过风控网关或直接下单。
      </footer>
    </div>
  );
};

export default QlibResearchPanel;
