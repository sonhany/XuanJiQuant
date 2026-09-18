import assert from 'node:assert/strict';
import fs from 'node:fs';

const routePath = 'server/routes/paper-execution.mjs';
assert(fs.existsSync(routePath), 'F5 route must exist');
const route = fs.readFileSync(routePath, 'utf8');
const router = fs.readFileSync('server/router.mjs', 'utf8');
const runner = fs.readFileSync('scripts/f5_paper_runner.py', 'utf8');
const reporting = fs.readFileSync('quant/paper_execution/reporting.py', 'utf8');

for (const action of ['status', 'account', 'runs', 'orders', 'fills', 'positions', 'equity', 'reconciliations', 'audit']) {
  assert(route.includes(`'${action}'`), `read action ${action} must be registered`);
}
for (const action of ['set_enabled', 'set_kill_switch', 'run_due', 'run_intraday']) {
  assert(route.includes(`'${action}'`), `controlled action ${action} must be registered`);
}
assert(router.includes("'/api/paper-execution'"), 'router must register F5 endpoint and auth policy');
const paperExecutionPolicyStart = router.indexOf("'/api/paper-execution': new Set");
const paperExecutionPolicy = router.slice(paperExecutionPolicyStart, paperExecutionPolicyStart + 260);
assert(paperExecutionPolicy.includes("'account'"), 'F5 account projection must be a read-only router action');
assert(router.includes('handlePaperExecution'), 'router must dispatch F5 handler');
assert(route.includes("new PersistentRunner('f5_paper_runner.py')"), 'route must use only the F5 runner');
assert(runner.includes('intraday_readiness') && runner.includes('current_readiness'), 'F5 status must expose current read-only eligibility instead of only the historical ledger tail');
assert(runner.includes('active_account_projection'), 'F5 runner must expose the single active account projection');
assert(!route.includes('execution_runner.py') && !route.includes('LiveBrokerAdapter'), 'route must never import retired/live execution');
assert(route.includes('arbitrary_order_action_forbidden'), 'arbitrary order actions must be rejected explicitly');
assert(runner.includes('live_execution_authority') && runner.includes('False'), 'runner must publish simulation-only authority');
assert(runner.includes('service.run_intraday(datetime.now())'), 'runner must expose only a parameter-free current-time intraday cycle');
assert(runner.includes('data.get("execution_mode")'), 'runner envelope must preserve the actual daily/intraday execution mode');
assert(reporting.includes('paper_execution_capability'), 'status must distinguish installed simulation capability');
for (const field of ['execution_lane', 'strategy_quality_status', 'f4_status', 'f4_reasons', 'research_generation_id']) {
  assert(reporting.includes(`"${field}"`), `status must expose ${field}`);
}
assert(reporting.includes('paper_execution_authority = bool('), 'current paper authority must be derived from the latest eligible run');
assert(!reporting.includes('"paper_execution_authority": True'), 'blocked status must not publish unconditional paper authority');
for (const forbidden of ['place_order', 'fill_order', 'cancel_order']) {
  assert(!runner.includes(`"${forbidden}":`), `${forbidden} handler must not exist`);
}
console.log('f5 paper execution contracts passed');
