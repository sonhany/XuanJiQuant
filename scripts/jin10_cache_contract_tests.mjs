import fs from 'node:fs';
import assert from 'node:assert/strict';

const src = fs.readFileSync('scripts/jin10_runner.py', 'utf8');

assert(src.includes('CACHE_TTL_SECONDS'), 'jin10 runner should define short TTL cache windows');
assert(src.includes('def _cached_tool_data'), 'jin10 runner should cache slow read-only MCP calls');
assert(src.includes('force_refresh'), 'jin10 runner should allow manual refresh to bypass cache');
assert(src.includes('"quotes"'), 'jin10 runner should support batch quote requests');
assert(src.includes('cache_hit'), 'jin10 runner should expose cache_hit for observability');

console.log('jin10 cache contract tests passed');
