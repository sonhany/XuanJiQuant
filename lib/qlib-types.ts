export type QlibCapabilityState = '可用' | '受限' | '运行中' | '失败' | '未接入';

export interface QlibGateResult {
  gate_version: string;
  status: 'candidate' | 'rejected' | 'review_required';
  passed: boolean;
  reason_codes: string[];
  checks: Record<string, unknown>;
}

export interface QlibWorkflowRun {
  id: string;
  experiment_id: string;
  qlib_experiment_id: string;
  recorder_id: string;
  dataset_version: string;
  quality_report_id: string;
  handler: 'Alpha158' | 'Alpha360';
  model_type: 'LightGBM' | 'XGBoost' | 'Linear';
  seed: number;
  config_hash: string;
  status: string;
  recorded_path: string;
  resolved_path: string;
  path_state: 'active' | 'mapped_legacy' | 'missing_historical' | 'rejected_frozen';
  resolution_reason?: string;
  artifacts_complete: boolean;
  available_handlers?: string[];
  available_models?: string[];
  artifacts: Record<string, string>;
  metrics: Record<string, unknown>;
  gate: QlibGateResult;
  created_at?: string;
}

export interface QlibBacktestResult {
  id: string;
  workflow_run_id: string;
  engine: 'qlib_official' | 'xuanji_ashare';
  signal_hash: string;
  metrics: Record<string, unknown>;
  config: Record<string, unknown>;
  artifact_path?: string;
  created_at?: string;
}

export interface QlibDataset {
  id: string;
  kind: string;
  status: string;
  start_date: string;
  end_date: string;
  latest_date: string;
  instruments: number;
  rows: number;
  coverage: number;
  path: string;
  metadata: Record<string, unknown>;
}

export interface QlibJob {
  id: string;
  kind: string;
  status: string;
  stage: string;
  progress: number;
  heartbeat_at?: string;
  message: string;
  result?: Record<string, unknown>;
}

export interface QlibModel {
  id: string;
  experiment_id: string;
  status: string;
  model_type: string;
  path: string;
  sha256: string;
  metrics: Record<string, unknown>;
}

export interface QlibExperiment {
  id: string;
  dataset_id: string;
  status: string;
  model_type: string;
  config: Record<string, unknown>;
  metrics: Record<string, unknown>;
  created_at?: string;
}

export interface QlibQualityReport {
  id?: string;
  report_id?: string;
  passed: boolean;
  gate_version?: string;
  dataset_version?: string;
  reason_codes?: string[];
  metrics?: Record<string, unknown>;
  created_at?: string;
}

export interface QlibScheduleMode {
  mode: string;
  consecutive_successes: number;
  latest_complete_cycle?: Record<string, unknown> | null;
}

export interface QlibStatus {
  environment: Record<string, unknown>;
  data_root: string;
  data_root_override: boolean;
  registry: string;
  active_job: QlibJob | null;
  latest_job: QlibJob | null;
  latest_workflow: QlibWorkflowRun | null;
  six_year_quality: QlibQualityReport | null;
  schedule: Record<'weekly' | 'monthly' | 'quarterly', QlibScheduleMode>;
  safety_boundary: 'offline_research_only';
  catalog: Array<{ id: string; name: string; status: QlibCapabilityState; items: string[] }>;
  checked_at: string;
}

export interface QlibResearchState {
  status: QlibStatus | null;
  datasets: QlibDataset[];
  jobs: QlibJob[];
  experiments: QlibExperiment[];
  models: QlibModel[];
  reports: Array<Record<string, unknown>>;
  qualityReports: QlibQualityReport[];
  workflowRuns: QlibWorkflowRun[];
  backtests: QlibBacktestResult[];
}

export function qlibNumber(value: unknown, fallback = 0): number {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

export function qlibMetric(metrics: Record<string, unknown> | undefined, key: string): number | null {
  if (!metrics) return null;
  const number = Number(metrics[key]);
  return Number.isFinite(number) ? number : null;
}
