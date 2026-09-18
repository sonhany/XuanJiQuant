import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync(new URL('../components/PaperPanel.tsx', import.meta.url), 'utf8');

assert(
  source.includes('/api/paper-execution') && source.includes("f5('account')"),
  'paper account UI must read the atomic F5 account projection',
);
assert(
  source.includes('currentMarketValue') && source.includes('totalEquity'),
  'paper account metrics must derive only from the F5 account projection',
);
assert(
  source.includes('setData({ ...accountProjection, status })'),
  'F5 runtime status must override the account compatibility status field',
);
assert.match(
  source,
  /const refresh = useCallback\(async \(\) => \{\s*setLoading\(true\);\s*try \{/,
  'a successful refresh must clear stale transport errors',
);

console.log('paper ledger UI contract tests passed');
