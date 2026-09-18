import fs from 'node:fs';
import assert from 'node:assert/strict';

const executionRunner = fs.readFileSync('scripts/execution_runner.py', 'utf8');
const executionRoute = fs.readFileSync('server/routes/execution.mjs', 'utf8');

assert(!executionRunner.includes('check_order'), 'read-only execution runner must not retain order routing');
assert(!executionRunner.includes('def action_place_order'), 'read-only execution runner must not implement place_order');
assert(!executionRunner.includes('def action_cancel_order'), 'read-only execution runner must not implement cancel_order');
assert(
  executionRoute.includes('automatic_execution_disabled') && executionRoute.includes('json(res, 409'),
  'execution write actions must fail closed at the API boundary',
);
assert(
  executionRoute.includes("new PersistentRunner('f5_paper_runner.py')") &&
    !executionRoute.includes("new PersistentRunner('execution_runner.py')"),
  '/api/execution reads must be a compatibility view of the single F5 ledger',
);
assert(
  executionRunner.includes('def _sort_timestamp') &&
    executionRunner.includes('_sort_timestamp(item.get("created_at")') &&
    executionRunner.includes('_sort_timestamp(item.get("timestamp")'),
  'historical orders and trades must tolerate mixed legacy timestamps',
);

console.log('execution read-only boundary contract tests passed');
