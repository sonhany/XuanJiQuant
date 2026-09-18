import fs from 'fs';
import assert from 'assert';

const batch = fs.readFileSync('start_all.bat', 'utf8');
const launcher = fs.readFileSync('scripts/start_services.mjs', 'utf8');
const server = fs.readFileSync('server/index.mjs', 'utf8');
const paperRoute = fs.readFileSync('server/routes/paper.mjs', 'utf8');
const researchScheduler = fs.readFileSync('scripts/research_training_scheduler.py', 'utf8');
const dailyResearchPipeline = fs.readFileSync('scripts/run_daily_research_pipeline.py', 'utf8');

assert(
  batch.includes('node scripts\\start_services.mjs'),
  'start_all.bat should delegate process startup to the durable launcher',
);
assert(
  !batch.includes('cmd /c "node server\\index.mjs"'),
  'start_all.bat should not bind the backend lifetime to a transient cmd window',
);
assert(
  launcher.includes('detached: true') && launcher.includes('.unref()'),
  'service launcher should detach child processes from the launching terminal',
);
assert(
  launcher.includes('backend-launcher-out.log') && launcher.includes('backend-launcher-err.log'),
  'service launcher should persist backend stdout and stderr',
);
assert(
  !launcher.includes("name: 'research-training-scheduler'") &&
    !launcher.includes("args: ['scripts/research_training_scheduler.py']"),
  'service launcher must leave deterministic research ownership to scheduled entry points',
);
assert(
  researchScheduler.indexOf('sys.path.insert') >= 0 &&
  researchScheduler.indexOf('sys.path.insert') < researchScheduler.indexOf('from quant.qlib.paths import'),
  'the directly launched research scheduler must add the project root before importing quant',
);
assert(
  dailyResearchPipeline.indexOf('"daily_update.py"') >= 0 &&
  dailyResearchPipeline.indexOf('"daily_update.py"') <
    dailyResearchPipeline.indexOf('"research_training_scheduler.py"'),
  'daily research pipeline must update data before running research',
);
assert(
  dailyResearchPipeline.includes('daily_snapshot_gate_failed') &&
  dailyResearchPipeline.includes('factor_artifact_gate_failed'),
  'daily research pipeline must fail closed at snapshot and factor artifact gates',
);
assert(
  launcher.includes("fs.openSync(stdoutPath, 'w')") && launcher.includes("fs.openSync(stderrPath, 'w')"),
  'launcher logs should contain only the current service session',
);
assert(
  server.includes("process.on('uncaughtException'") &&
  server.includes("process.on('unhandledRejection'") &&
  server.includes("server.on('error'"),
  'server should record fatal process and listener failures',
);
assert(
  server.includes('[API Server] session started') && server.includes('sessionId='),
  'server log should mark the current process session for bounded diagnostics',
);
assert(paperRoute.includes('automatic_execution_disabled'), 'paper route must keep automatic execution closed');

console.log('service lifecycle contract tests passed');
