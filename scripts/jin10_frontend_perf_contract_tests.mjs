import fs from 'node:fs';
import assert from 'node:assert/strict';

const src = fs.readFileSync('components/Jin10DataPanel.tsx', 'utf8');

assert(src.includes("action: 'quotes'"), 'Jin10 macro quotes should use the batch quotes action');
assert(!src.includes("action: 'quote', code"), 'Jin10 macro quotes should not issue one HTTP request per code');
assert(src.includes('force_refresh'), 'manual Jin10 refresh should be able to bypass backend cache');
assert(src.includes('payload?.data?.items'), 'Jin10 list parser should accept direct data.items payloads');
assert(src.includes('if (!res.ok || !payload?.success)'), 'Jin10 frontend should surface HTTP and business errors');
assert(src.includes('readableJin10Error(payload?.error'), 'Jin10 frontend should preserve and normalize the backend error message');
assert(src.includes('catchBackgroundRefresh'), 'Jin10 background polling should catch and display refresh errors');
assert(src.includes('if (!successful.length && quoteErrors.length)'), 'Jin10 quotes should surface an all-failed batch instead of showing an empty healthy state');
assert(src.includes('function readableJin10Error'), 'Jin10 frontend should normalize JSON-encoded MCP business errors');
assert(src.includes('chunkRows'), 'Jin10 macro quotes should be split into bounded batches');
assert(src.includes('loadSupportedQuoteCodes'), 'Jin10 macro quotes should come from quote://codes');
assert(!src.includes('}, 30_000);'), 'Jin10 must not refresh the full quote set every 30 seconds');
assert(src.includes('pages: deep ? DEEP_FEED_PAGES : 1'), 'Jin10 feeds should deep-load once and poll only the newest page');

console.log('jin10 frontend perf contract tests passed');
