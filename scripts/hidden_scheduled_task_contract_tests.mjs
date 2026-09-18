import assert from 'node:assert/strict';
import fs from 'node:fs';

const path = 'scripts/run_hidden_scheduled_task.ps1';
assert(fs.existsSync(path), 'hidden scheduled-task launcher must exist');
const source = fs.readFileSync(path, 'utf8');

for (const taskKey of [
  'paper_daily',
  'paper_intraday',
  'research_daily',
  'qlib_weekly',
  'strategy_weekly',
]) {
  assert(source.includes(taskKey), `hidden launcher must allow ${taskKey}`);
}

for (const required of [
  'ValidateSet',
  'Start-Process',
  '-WindowStyle Hidden',
  '-Wait',
  '-PassThru',
  'ExitCode',
  '-WorkingDirectory $projectRoot',
]) {
  assert(source.includes(required), `hidden launcher missing ${required}`);
}

assert(!source.includes('Invoke-Expression'), 'hidden launcher must not execute arbitrary text');
assert(!source.includes('AlphaCouncil2-AI'), 'hidden launcher must never target frozen backup');
console.log('hidden scheduled task contracts passed');
