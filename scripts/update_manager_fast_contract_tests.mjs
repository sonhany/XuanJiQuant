import fs from 'node:fs';
import assert from 'node:assert/strict';

const source = fs.readFileSync('server/update_manager.mjs', 'utf-8');

assert(
  source.includes("--financial-only"),
  "financial update mode should pass --financial-only to daily_update.py",
);
assert(
  source.includes("--workers"),
  "manual data update should pass worker count to daily_update.py",
);
assert(
  source.includes("XUANJI_UPDATE_WORKERS"),
  "manual data update worker count should be configurable by environment",
);
assert(
  source.includes("const durableFinancial = mode === 'financial'") && source.includes('detached: durableFinancial'),
  'financial updates must run independently from the backend process lifetime',
);
assert(
  source.includes('financial-update-out.log') && source.includes('financial-update-err.log'),
  'durable financial updates must own independent logs',
);
assert(
  source.includes('readFinancialCheckpoint') && source.includes('mergeFinancialCheckpoint'),
  'a restarted backend must recover financial progress from the durable checkpoint',
);
assert(
  source.includes('proc.unref()'),
  'the detached financial worker must not remain tied to the backend event loop',
);
assert(
  source.includes('updateProc?.pid || updateState.pid') &&
    source.includes('process.kill(Number(activePid))') &&
    source.includes('writeFinancialCheckpointStatus'),
  'a restarted backend must be able to stop the adopted durable financial PID cleanly',
);

console.log("update manager fast contract tests passed");
