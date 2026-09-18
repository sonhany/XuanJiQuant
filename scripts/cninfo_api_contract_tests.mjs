import assert from 'node:assert/strict';
import fs from 'node:fs';

const router = fs.readFileSync('server/router.mjs', 'utf8');
const routePath = 'server/routes/cninfo.mjs';

assert(fs.existsSync(routePath), 'Cninfo API route must exist');
const route = fs.readFileSync(routePath, 'utf8');

assert(router.includes("import { handleCninfo } from './routes/cninfo.mjs'"), 'router must import Cninfo handler');
assert(router.includes("'/api/cninfo': new Set(['query', 'detail', 'status'])"), 'Cninfo query, detail and status must be read-only');
assert(router.includes("'/api/cninfo':   handleCninfo") || router.includes("'/api/cninfo': handleCninfo"), 'router must register /api/cninfo');
assert(route.includes("new PersistentRunner('cninfo_runner.py', 'cninfo-query')"), 'Cninfo queries must use an isolated persistent runner');
assert(route.includes('45_000'), 'Cninfo route must allow slow upstream queries while keeping a bounded timeout');
assert(route.includes('60_000'), 'PDF extraction must have a separate bounded timeout');
assert(route.includes("'cninfo-detail'"), 'PDF detail extraction must use an isolated runner');

console.log('cninfo API contract tests passed');
