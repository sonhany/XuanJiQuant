import assert from 'node:assert/strict';
import fs from 'node:fs';

const route = fs.readFileSync('server/routes/factor.mjs', 'utf8');
const uiVerify = fs.readFileSync('scripts/ui_verify.mjs', 'utf8');
const factorPanel = fs.readFileSync('components/FactorPanel.tsx', 'utf8');
assert(route.includes('BUSINESS_GATE_REASONS'), 'factor route must classify fail-closed business gates');
assert(route.includes('factor_snapshot_stale'), 'stale factor evidence must be a named business gate');
assert(route.includes('factor_evaluation_version_mismatch'), 'evaluation/version mismatch during deterministic refresh is a business gate');
assert(route.includes('factor_projection_version_mismatch'), 'projection/version mismatch during deterministic refresh is a business gate');
assert(route.includes('data.success || BUSINESS_GATE_REASONS.has(data.reason_code) ? 200 : 500'), 'business gates must not masquerade as HTTP infrastructure errors');
for (const reason of ['factor_snapshot_stale', 'factor_evaluation_version_mismatch', 'factor_projection_version_mismatch']) {
  assert(uiVerify.includes(`'${reason}'`), `UI verifier must accept fail-closed business gate ${reason}`);
}
assert(
  factorPanel.includes('因子评估已过期') &&
    factorPanel.includes("marketEval?.research_refresh?.state !== 'refreshing'"),
  'factor surface must explicitly label a completed but stale research generation',
);
console.log('factor stale route contracts passed');
