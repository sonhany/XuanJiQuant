import fs from 'node:fs';

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const dataRoute = fs.readFileSync('server/routes/data.mjs', 'utf-8');
const router = fs.readFileSync('server/router.mjs', 'utf-8');
const managerPath = 'server/tick_collector_manager.mjs';

assert(fs.existsSync(managerPath), 'server must provide a tick collector manager');
assert(dataRoute.includes('handleTickCollectorAction'), 'data route should intercept tick collector control actions');
assert(router.includes('tick_collector_status'), 'router should allow tick collector status action');
const readOnlyBlock = router.match(/const READ_ONLY_ACTIONS = \{([\s\S]*?)\n\};/)?.[1] || '';
assert(!readOnlyBlock.includes("'tick_collector_start'"), 'tick collector start must require control authorization');
assert(!readOnlyBlock.includes("'tick_collector_stop'"), 'tick collector stop must require control authorization');
assert(!readOnlyBlock.includes("'tick_collect_once'"), 'one-shot tick collection must require control authorization');

console.log('tick collector route contract tests passed');
