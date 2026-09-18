import fs from 'node:fs';
import assert from 'node:assert/strict';

const risk = fs.readFileSync('components/RiskPanel.tsx', 'utf8');
const alerts = fs.readFileSync('components/AlertPanel.tsx', 'utf8');

for (const text of ['组合风险', '系统诊断', '审计回放', '历史组合快照法', '数据不可用']) {
  assert(risk.includes(text), `risk surface must include ${text}`);
}
assert(risk.includes('Promise.allSettled'), 'risk requests must preserve partial failures');
assert(alerts.includes("useState<any>(null)"), 'alert statistics must begin unknown, not zero');
assert(alerts.includes('操作员'), 'alert state changes must record operator');
assert(alerts.includes('处理原因'), 'alert state changes must require a reason');
assert(alerts.includes('window.confirm'), 'critical alert/rule actions must require confirmation');

console.log('authoritative risk and alert contract tests passed');
