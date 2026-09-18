import fs from 'fs';
import net from 'net';
import path from 'path';
import { spawn } from 'child_process';
import { fileURLToPath } from 'url';

const ROOT_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const LOG_DIR = path.join(ROOT_DIR, 'logs');
const HOST = '127.0.0.1';
const SERVICES = [
  {
    name: 'backend',
    port: 8880,
    command: process.execPath,
    args: ['server/index.mjs'],
    stdout: 'backend-launcher-out.log',
    stderr: 'backend-launcher-err.log',
  },
  {
    name: 'frontend',
    port: 8888,
    command: process.execPath,
    args: ['node_modules/vite/bin/vite.js', '--host', HOST, '--port', '8888', '--strictPort'],
    stdout: 'frontend-launcher-out.log',
    stderr: 'frontend-launcher-err.log',
  },
];

function pidPath(service) {
  return path.join(LOG_DIR, `${service.name}.pid`);
}

function isProcessAlive(pid) {
  if (!Number.isSafeInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function recordedProcessIsAlive(service) {
  try {
    const pid = Number.parseInt(fs.readFileSync(pidPath(service), 'utf8').trim(), 10);
    return isProcessAlive(pid);
  } catch {
    return false;
  }
}

function isListening(port) {
  return new Promise((resolve) => {
    const socket = net.createConnection({ host: HOST, port });
    const done = (result) => {
      socket.removeAllListeners();
      socket.destroy();
      resolve(result);
    };
    socket.setTimeout(800);
    socket.once('connect', () => done(true));
    socket.once('timeout', () => done(false));
    socket.once('error', () => done(false));
  });
}

async function waitForPort(port, timeoutMs = 20_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await isListening(port)) return true;
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  return false;
}

function startDetached(service) {
  fs.mkdirSync(LOG_DIR, { recursive: true });
  const stdoutPath = path.join(LOG_DIR, service.stdout);
  const stderrPath = path.join(LOG_DIR, service.stderr);
  const stdout = fs.openSync(stdoutPath, 'w');
  const stderr = fs.openSync(stderrPath, 'w');

  const child = spawn(service.command, service.args, {
    cwd: ROOT_DIR,
    detached: true,
    windowsHide: true,
    stdio: ['ignore', stdout, stderr],
    env: process.env,
  });
  child.unref();
  fs.closeSync(stdout);
  fs.closeSync(stderr);
  fs.writeFileSync(pidPath(service), `${child.pid}\n`, 'utf8');
  return child.pid;
}

async function main() {
  let failed = false;
  for (const service of SERVICES) {
    if (service.port === null && recordedProcessIsAlive(service)) {
      console.log(`[OK] ${service.name} already running`);
      continue;
    }
    if (service.port !== null && await isListening(service.port)) {
      console.log(`[OK] ${service.name} already listening on ${HOST}:${service.port}`);
      continue;
    }

    const pid = startDetached(service);
    const ready = service.port === null
      ? await new Promise(resolve => setTimeout(() => resolve(isProcessAlive(pid)), 1000))
      : await waitForPort(service.port);
    if (ready) {
      const location = service.port === null ? '' : ` on ${HOST}:${service.port}`;
      console.log(`[OK] ${service.name} started pid=${pid}${location}`);
    } else {
      failed = true;
      console.error(
        `[FAIL] ${service.name} did not become ready; check logs/${service.stderr}`,
      );
    }
  }
  process.exitCode = failed ? 1 : 0;
}

await main();
