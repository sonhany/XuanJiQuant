import fs from 'node:fs';

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const audit = fs.readFileSync('quant/data/audit.py', 'utf-8');
const riskRunner = fs.readFileSync('scripts/risk_runner.py', 'utf-8');
const router = fs.readFileSync('server/router.mjs', 'utf-8');

assert(audit.includes('order_id: str = ""'), 'audit replay should accept order_id');
assert(audit.includes('"model_calls": _rows'), 'audit replay should include model calls');
assert(riskRunner.includes('order_id=str(req.get("order_id") or "")'), 'risk runner should pass order_id to audit replay');
assert(router.includes("'decision_trace'"), 'risk API read-only actions should include decision_trace alias');

console.log('decision trace contract tests passed');
