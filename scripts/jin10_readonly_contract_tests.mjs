import fs from 'node:fs';
import assert from 'node:assert/strict';

const src = fs.readFileSync('server/router.mjs', 'utf8');
const jin10Line = src.split('\n').find((line) => line.includes("'/api/jin10'")) || '';

assert(jin10Line.includes("'status'"), 'Jin10 status should be read-only');
assert(jin10Line.includes("'tools'"), 'Jin10 tool metadata should be read-only');
assert(jin10Line.includes("'resources'"), 'Jin10 resource metadata should be read-only');
assert(!jin10Line.includes("'quote'"), 'Jin10 quote calls should require control authorization');
assert(!jin10Line.includes("'flash'"), 'Jin10 flash calls should require control authorization');
assert(!jin10Line.includes("'news'"), 'Jin10 news calls should require control authorization');
assert(!jin10Line.includes("'calendar'"), 'Jin10 calendar calls should require control authorization');

console.log('jin10 readonly contract tests passed');
