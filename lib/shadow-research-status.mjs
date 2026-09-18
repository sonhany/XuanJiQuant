import fs from 'node:fs';
import path from 'node:path';

const SCHEMA = 'xuanji-shadow-research-status-v1';

function projectPath(root, ...parts) {
  return path.join(root, ...parts);
}

function fileInfo(file, root) {
  try {
    const stat = fs.statSync(file);
    if (!stat.isFile()) return { exists: false, path: file, relative_path: path.relative(root, file).replaceAll('\\', '/') };
    return {
      exists: true,
      path: file,
      relative_path: path.relative(root, file).replaceAll('\\', '/'),
      updated_at: stat.mtime.toISOString(),
      size_bytes: stat.size,
    };
  } catch {
    return {
      exists: false,
      path: file,
      relative_path: path.relative(root, file).replaceAll('\\', '/'),
    };
  }
}

function readJsonObject(file) {
  try {
    const parsed = JSON.parse(fs.readFileSync(file, 'utf8'));
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function collectReportCandidates(base) {
  const candidates = [path.join(base, 'shadow_cycle_report.json')];
  const dailyRoot = path.join(base, 'shadow-daily');
  try {
    for (const entry of fs.readdirSync(dailyRoot, { withFileTypes: true })) {
      if (!entry.isDirectory()) continue;
      candidates.push(path.join(dailyRoot, entry.name, 'shadow_cycle_report.json'));
    }
  } catch {
    // A missing shadow-daily directory is a normal pre-cycle state.
  }
  return candidates
    .map((file) => {
      try {
        const stat = fs.statSync(file);
        return stat.isFile() ? { file, mtimeMs: stat.mtimeMs } : null;
      } catch {
        return null;
      }
    })
    .filter(Boolean)
    .sort((left, right) => right.mtimeMs - left.mtimeMs);
}

function proposalCount(report) {
  const locations = [
    report?.report?.proposals,
    report?.proposal_report?.proposals,
    report?.proposals,
  ];
  for (const value of locations) {
    if (Array.isArray(value)) return value.length;
  }
  const summaryCount = Number(report?.report?.summary?.proposal_count ?? report?.summary?.proposal_count);
  return Number.isFinite(summaryCount) ? summaryCount : null;
}

function statusFromArtifacts({ baseline, runtime, aiOutput, report }) {
  if (!baseline.exists) return ['baseline_missing', 'baseline_result_missing'];
  if (!runtime.exists) return ['runtime_summary_missing', 'runtime_summary_missing'];
  if (!aiOutput.exists) return ['shadow_ai_raw_output_missing', 'shadow_ai_raw_output_missing'];
  if (!report.exists) return ['shadow_cycle_report_missing', 'shadow_cycle_report_missing'];
  const payload = report.payload || {};
  if (payload.success === false) {
    return ['shadow_cycle_failed', String(payload.reason_code || payload.error || 'shadow_cycle_failed')];
  }
  return ['shadow_recorded', 'shadow_cycle_report_available'];
}

export function loadShadowResearchStatus(projectRoot = process.cwd()) {
  const root = path.resolve(projectRoot);
  const base = projectPath(root, 'data', 'nautilus-baseline');
  const baselinePath = path.join(base, 'baseline_result.json');
  const baselineMetaPath = path.join(base, 'baseline_result.meta.json');
  const runtimePath = path.join(base, 'runtime_summary.json');
  const aiOutputPath = path.join(base, 'ai_raw_output.json');
  const aiOutputMetaPath = path.join(base, 'ai_raw_output.meta.json');
  const storePath = path.join(base, 'shadow_decisions.sqlite3');

  const reportCandidate = collectReportCandidates(base)[0]?.file || path.join(base, 'shadow_cycle_report.json');
  const baseline = fileInfo(baselinePath, root);
  const runtime = fileInfo(runtimePath, root);
  const aiOutput = fileInfo(aiOutputPath, root);
  const reportInfo = fileInfo(reportCandidate, root);
  const reportPayload = reportInfo.exists ? readJsonObject(reportCandidate) : null;
  const shadowCycle = {
    ...reportInfo,
    report_exists: reportInfo.exists,
    success: reportPayload?.success === true ? true : reportPayload?.success === false ? false : null,
    stage: String(reportPayload?.stage || reportPayload?.report?.stage || ''),
    reason_code: String(reportPayload?.reason_code || reportPayload?.error || ''),
    total_proposals: reportPayload ? proposalCount(reportPayload) : null,
  };
  const [status, reasonCode] = statusFromArtifacts({
    baseline,
    runtime,
    aiOutput,
    report: { ...reportInfo, payload: reportPayload },
  });
  const updatedCandidates = [
    baseline.updated_at,
    runtime.updated_at,
    aiOutput.updated_at,
    shadowCycle.updated_at,
  ].filter(Boolean).sort();

  return {
    schema: SCHEMA,
    mode: 'shadow_decision_read_only',
    status,
    reason_code: reasonCode,
    updated_at: updatedCandidates.at(-1) || new Date(0).toISOString(),
    baseline: {
      ...baseline,
      metadata_exists: fileInfo(baselineMetaPath, root).exists,
    },
    runtime_summary: runtime,
    ai_raw_output: {
      ...aiOutput,
      metadata_exists: fileInfo(aiOutputMetaPath, root).exists,
    },
    shadow_cycle: shadowCycle,
    shadow_store: fileInfo(storePath, root),
    execution_authority: false,
    can_trigger_order: false,
    live_execution_authority: false,
    permissions: {
      mode: 'read_only_shadow_research',
      can_trigger_order: false,
      can_change_trade_policy: false,
      can_write_f5_ledger: false,
      live_execution_authority: false,
    },
  };
}
