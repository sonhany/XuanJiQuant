import assert from 'node:assert/strict';
import fs from 'node:fs';

assert(fs.existsSync('scripts/service_manager.py'), 'unified service manager must exist');
assert(fs.existsSync('scripts/service_host.cmd'), 'native service host command must exist');
assert(fs.existsSync('scripts/install_service_tasks.ps1'), 'service task installer must exist');
assert(fs.existsSync('scripts/run_service_host.ps1'), 'legacy service host runner must still exist');
assert(fs.existsSync('scripts/service_supervisor.ps1'), 'legacy service supervisor must still exist');

const manager = fs.readFileSync('scripts/service_manager.py', 'utf8');
const nativeHost = fs.readFileSync('scripts/service_host.cmd', 'utf8');
const installer = fs.readFileSync('scripts/install_service_tasks.ps1', 'utf8');

assert(nativeHost.includes(String.raw`server\index.mjs`) && nativeHost.includes('vite.js'), 'service host must own both governed commands');
assert(nativeHost.includes('2>>'), 'native service output must append without PowerShell UTF-16 transcoding');

assert(manager.includes('ChildProcess'), 'service manager must define ChildProcess');
assert(manager.includes('"api"') || manager.includes("'api'"), 'service manager must handle api service');
assert(manager.includes('"web"') || manager.includes("'web'"), 'service manager must handle web service');
assert(manager.includes('CHECK_INTERVAL') || manager.includes('check_interval'), 'service manager must have health check interval');
assert(manager.includes('signal') || manager.includes('SIGTERM'), 'service manager must handle graceful shutdown');
assert(manager.includes('service_host.cmd') || manager.includes('SERVICE_HOST'), 'service manager must invoke native service host');
assert(!manager.includes('f5_paper_intraday.py') && !manager.includes('run_intraday'), 'service manager must never trigger trading');
assert(!manager.includes('AlphaCouncil2-AI'), 'service manager must never touch the frozen backup');

assert(installer.includes('XuanJiQuant-Service'), 'installer must create unified service task');
assert(installer.includes('-AtLogOn'), 'service task must start at user logon');
assert(installer.includes('-RestartCount') && installer.includes('-RestartInterval'), 'service task must restart failed hosts');
assert(installer.includes('IgnoreNew'), 'service task must reject overlaps');
assert(installer.includes('service_manager.py'), 'installer must register the unified service manager');
assert(!installer.includes('f5_paper_intraday.py') && !installer.includes('run_intraday'), 'installer must not gain trading authority');

console.log('service host task contracts passed');
