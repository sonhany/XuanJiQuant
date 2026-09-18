import fs from 'fs';
import assert from 'assert';

const unified = fs.readFileSync('scripts/install_research_schedules.ps1', 'utf8');
const qlib = fs.readFileSync('scripts/install_qlib_schedule.ps1', 'utf8');

for (const token of [
  'XuanJiQuant-Research-Daily',
  'MON,TUE,WED,THU,FRI',
  '16:20',
  '20:30',
  'XuanJiQuant-Strategy-Weekly',
  'SUN',
  '10:00',
  'RestartCount',
  'IgnoreNew',
  'StartWhenAvailable',
  'ExecutionTimeLimit',
  'AllowStartIfOnBatteries',
  'DontStopIfGoingOnBatteries',
]) {
  assert(unified.includes(token), `research schedule installer must contain ${token}`);
}

assert(
  unified.includes('$dailyPrimaryTrigger') &&
    unified.includes('$dailyRecoveryTrigger') &&
    unified.includes('$dailyTriggers'),
  'daily research must have a primary trigger and an idempotent evening recovery trigger',
);

assert(
  unified.includes('run_hidden_scheduled_task.ps1') &&
    unified.includes('research_daily') &&
    unified.includes('qlib_weekly') &&
    unified.includes('strategy_weekly') &&
    unified.includes('-WindowStyle Hidden'),
  'research tasks must use the fixed hidden launcher task keys',
);
assert(
  unified.includes('WorkingDirectory') && unified.includes('$projectRoot'),
  'research task actions must declare the project working directory',
);
assert(
  qlib.includes('XuanJiQuant-Qlib-Weekly') &&
    qlib.includes('SAT') &&
    qlib.includes('18:30'),
  'Qlib installer must retain Saturday 18:30',
);
assert(
  qlib.includes('New-ScheduledTaskAction') &&
    qlib.includes('run_hidden_scheduled_task.ps1') &&
    qlib.includes('qlib_weekly') &&
    qlib.includes('-WindowStyle Hidden') &&
    qlib.includes('WorkingDirectory') &&
    qlib.includes('IgnoreNew'),
  'Qlib installer must use a project working directory and IgnoreNew concurrency',
);
const qlibBlock = unified.slice(
  unified.indexOf('-TaskName "XuanJiQuant-Qlib-Weekly"'),
  unified.indexOf('$strategyTrigger'),
);
const strategyBlock = unified.slice(
  unified.indexOf('-TaskName "XuanJiQuant-Strategy-Weekly"'),
  unified.indexOf('Write-Host'),
);
assert(strategyBlock.includes('-TaskKey "strategy_weekly"'), 'Sunday F4 must use the fixed strategy task key');
assert(
  strategyBlock.includes('-ExecutionHours 12'),
  'Sunday F4 must allow the verified eight-hour v2 factory to finish',
);
assert(
  qlibBlock.includes('-TaskKey "qlib_weekly"') &&
    !qlib.includes('scripts\\qlib_schedule.py'),
  'Saturday Qlib must be claimed through ResearchJobStore before invoking qlib_schedule',
);
assert(
  strategyBlock.includes('-TaskKey "strategy_weekly"'),
  'Sunday F4 task must claim only the strategy lane',
);
assert(!unified.includes('-Execute $Executable'), 'research tasks must not launch console python directly');
assert(!qlib.includes('-Execute $python'), 'standalone Qlib installer must not launch console python directly');
assert(
  !unified.toLowerCase().includes('agent') &&
    !unified.toLowerCase().includes('/api/execution') &&
    !unified.toLowerCase().includes('/api/paper'),
  'research schedule installer must not revive Agent or execution entry points',
);

console.log('research schedule contract tests passed');
