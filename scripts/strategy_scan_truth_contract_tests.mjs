import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync('components/StrategyPanel.tsx', 'utf8');
const router = fs.readFileSync('server/router.mjs', 'utf8');

assert(source.includes('F4 策略与组合验证'), 'strategy entry must expose the F4 validation surface');
assert(source.includes('execution_authority 均为 false'), 'strategy surface must state its non-execution authority');
assert(!source.includes('snapshot_proxy'), 'retired snapshot-proxy ranking must not remain');
assert(!source.includes('scan.realistic'), 'retired market-scan realism branch must not remain');
assert(
  router.includes("'/api/strategy': new Set(['meta', 'market_scan', 'research_selection'])"),
  'F4 and research-selection projections must remain explicitly read-only API actions',
);

console.log('strategy scan truth contract tests passed');
