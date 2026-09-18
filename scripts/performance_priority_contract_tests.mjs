import fs from 'node:fs';
import assert from 'node:assert/strict';

const runner = fs.readFileSync('server/persistent_runner.mjs', 'utf8');
const dataRoute = fs.readFileSync('server/routes/data.mjs', 'utf8');
const factorRunner = fs.readFileSync('scripts/factor_runner.py', 'utf8');
const indexHtml = fs.readFileSync('index.html', 'utf8');
const uiVerify = fs.readFileSync('scripts/ui_verify.mjs', 'utf8');
const webVerify = fs.readFileSync('scripts/web_verify.mjs', 'utf8');
const riskRunner = fs.readFileSync('scripts/risk_runner.py', 'utf8');
const viteConfig = fs.readFileSync('vite.config.ts', 'utf8');

assert(runner.includes('cleanupStaleScriptProcesses'), 'runner should clean stale same-script children');
assert(runner.includes('$_.ProcessId -ne $PID'), 'cleanup must exclude its own PowerShell process');
assert(runner.includes('orphan response id mismatch'), 'orphan protocol output must not poison the active queue');
assert(runner.includes('restart()'), 'runner should expose bounded restart recovery');
assert(dataRoute.includes('response id mismatch') && dataRoute.includes('runner.restart()'), 'data route should recover once');
assert(factorRunner.includes('factor:evaluate_all:') && factorRunner.includes('FACTOR_EVALUATE_CACHE_TTL'), 'factor evaluation should be cached');
assert(!indexHtml.includes('cdn.tailwindcss.com'), 'initial page must not depend on Tailwind CDN');
assert(!uiVerify.includes("action: 'reset'") && !uiVerify.includes('action: "reset"'), 'UI verification must not reset the ledger');
assert(
  webVerify.includes("action: 'meta'") && webVerify.includes("action: 'system_health'") &&
    webVerify.includes("post('execution', { action: 'place_order'") &&
    webVerify.includes("post('paper', { action: 'run_once' })") &&
    webVerify.includes('automatic_execution_disabled'),
  'Web verification must exercise current reads and both fail-closed write boundaries',
);
assert(webVerify.includes('current_readiness'), 'web verification must recognize an eligible paper lane waiting for the next market window');
assert(!factorRunner.includes('"market_evaluation": action_market_eval') && !riskRunner.includes('"check": action_system_health'), 'obsolete aliases must stay removed');
assert(uiVerify.includes('SUITE_TIMEOUT_MS') && uiVerify.includes('browserHandle?.close()'), 'UI suite needs a deadline and browser cleanup');
assert(!uiVerify.includes("waitUntil: 'networkidle'"), 'polling UI must not wait for network idle');
for (const ignoredPath of ['.venv-qlib/**', 'data/**', 'logs/**', 'dist/**', '**/__pycache__/**']) {
  assert(viteConfig.includes(ignoredPath), `Vite watcher should ignore ${ignoredPath}`);
}

console.log('performance priority contract tests passed');
