import fs from 'node:fs';
import assert from 'node:assert/strict';

const app = fs.readFileSync('App.tsx', 'utf8');
const shell = fs.readFileSync('components/AppShell.tsx', 'utf8');
const profile = fs.readFileSync('components/LocalProfileScreen.tsx', 'utf8');

for (const workspace of ['决策中心', '策略研究', '交易与组合', '风险与审计', '数据与系统']) {
  assert(shell.includes(workspace), `shell must expose workspace: ${workspace}`);
}

assert(!shell.includes('专业投资工作台'), 'shell must not display the professional workbench header');
assert(!shell.includes('<TruthBar'), 'shell must not display the global truth bar');
assert(shell.includes('sidebar-profile'), 'shell must keep profile controls in the sidebar');
assert(shell.includes('mobile-menu-button'), 'shell must provide a standalone mobile menu button');
assert(shell.includes('workbench-mobile-nav'), 'shell must provide a mobile navigation drawer');
assert(shell.includes('onLogout'), 'shell must expose logout');
assert(app.includes('<AppShell'), 'App must use the shared shell');
assert(app.includes('<LocalProfileScreen'), 'App must use the honest local profile screen');
assert(!profile.includes('SECURE ACCESS'), 'local profile screen must not claim server authentication');
assert(profile.includes('仅保存于当前浏览器'), 'local profile screen must explain local-only identity');

console.log('workbench shell contract tests passed');
