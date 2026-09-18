import assert from 'node:assert/strict';
import fs from 'node:fs';

const path = 'scripts/install_f5_paper_task.ps1';
assert(fs.existsSync(path), 'F5 schedule installer must exist');
const source = fs.readFileSync(path, 'utf8');
for (const required of [
  'XuanJiQuant-Paper-Daily', 'run_hidden_scheduled_task.ps1', 'paper_daily',
  '-WindowStyle Hidden',
  '17:10', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday',
  'IgnoreNew', 'New-TimeSpan -Minutes 15', 'RestartCount 3',
  'New-TimeSpan -Hours 2', '-WorkingDirectory',
  '[System.Security.Principal.WindowsIdentity]::GetCurrent().Name',
]) assert(source.includes(required), `schedule installer missing ${required}`);
assert(!source.includes('-Execute $pythonPath'), 'F5 daily task must not launch console python directly');
assert(!source.includes('-At "16:40"'), 'F5 daily task must run after the daily research completion window');
assert(!source.includes('-UserId $env:USERNAME'), 'principal must use the fully-qualified Windows identity');
assert(!source.includes('AlphaCouncil2-AI'), 'installer must never target frozen backup');
console.log('f5 schedule contracts passed');

const intradayPath = 'scripts/install_f5_intraday_task.ps1';
assert(fs.existsSync(intradayPath), 'F5 intraday schedule installer must exist');
const intraday = fs.readFileSync(intradayPath, 'utf8');
for (const required of [
  'XuanJiQuant-Paper-Intraday', 'run_hidden_scheduled_task.ps1', 'paper_intraday',
  '-WindowStyle Hidden',
  '09:35', '11:25', '13:05', '14:50', 'AddMinutes(5)',
  'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'IgnoreNew',
  '-WorkingDirectory', '[System.Security.Principal.WindowsIdentity]::GetCurrent().Name',
]) assert(intraday.includes(required), `intraday schedule installer missing ${required}`);
assert(!intraday.includes('-Execute $pythonPath'), 'F5 intraday task must not launch console python directly');
assert(!intraday.includes('.Repetition.Interval'), 'weekly trigger repetition is unsupported on this Windows cmdlet');
assert(!intraday.includes('AlphaCouncil2-AI'), 'intraday installer must never target frozen backup');
