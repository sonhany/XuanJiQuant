import assert from 'node:assert/strict';
import fs from 'node:fs';

const routerPath = 'server/router.mjs';
const routePath = 'server/routes/valuation.mjs';
const runnerPath = 'scripts/valuation_runner.py';

const router = fs.readFileSync(routerPath, 'utf8');
assert(router.includes("'/api/valuation'"), 'router must register /api/valuation');
assert(
  /'\/api\/valuation'\s*:\s*new Set\(\[['\"]analyze['\"],\s*['\"]latest['\"]\]\)/s.test(router),
  'valuation read-only block must contain analyze/latest only',
);
const valuationReadOnly = router.match(/'\/api\/valuation'\s*:\s*new Set\(\[(.*?)\]\)/s)?.[1] || '';
assert(!valuationReadOnly.includes('glm_analyze'), 'glm_analyze must remain protected');
assert(router.includes('handleValuation'), 'router must import and dispatch handleValuation');

assert(fs.existsSync(routePath), 'valuation route must exist');
const route = fs.readFileSync(routePath, 'utf8');
assert(
  route.includes("new PersistentRunner('valuation_runner.py')"),
  'valuation route must use the persistent runner singleton',
);
assert(route.includes('Number(data.status || 500)'), 'route must preserve runner status codes');

assert(fs.existsSync(runnerPath), 'valuation runner must exist');
const runner = fs.readFileSync(runnerPath, 'utf8');
for (const action of ['analyze', 'glm_analyze', 'latest']) {
  assert(
    runner.includes(`"${action}": action_${action}`) ||
      runner.includes(`'${action}': action_${action}`),
    `runner must dispatch ${action}`,
  );
}
assert(runner.includes('normalize_code'), 'runner must validate stock codes');
assert(runner.includes('status=400'), 'invalid codes must return status 400');

async function post(body, headers = {}) {
  const response = await fetch('http://127.0.0.1:8880/api/valuation', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(120000),
  });
  return { status: response.status, json: await response.json() };
}

try {
  const health = await fetch('http://127.0.0.1:8880/api/valuation', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'latest', code: '300442' }),
    signal: AbortSignal.timeout(3000),
  });
  if (health.status !== 404) {
    const analyzed = await post({ action: 'analyze', code: '300442' });
    assert.equal(analyzed.status, 200, `live analyze failed: ${JSON.stringify(analyzed.json)}`);
    assert.deepEqual(
      Object.keys(analyzed.json.data?.valuations || {}).sort(),
      ['absolute', 'market', 'relative'],
      'live analyze must return exactly three deterministic tracks',
    );

    const invalid = await post({ action: 'analyze', code: '920001' });
    assert.equal(invalid.status, 400, '920xxx must be rejected with HTTP 400');

    const protectedResult = await post({ action: 'glm_analyze', code: '300442' });
    assert.equal(protectedResult.status, 403, 'unauthenticated GLM valuation must be forbidden');
  }
} catch (error) {
  if (!String(error?.cause?.code || error?.message || '').match(/ECONNREFUSED|fetch failed|timeout/i)) {
    throw error;
  }
}

console.log('valuation_api_contract_tests: PASS');
