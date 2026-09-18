import { parentPort } from 'worker_threads';
import { watchdogTick } from './watchdog.mjs';

const FIRST_CHECK_DELAY_MS = 30_000;
const CHECK_INTERVAL_MS = 60_000;
let firstTimer = null;
let intervalTimer = null;
let running = false;

function runCheck(options = {}) {
  if (running) return;
  running = true;
  try {
    watchdogTick(options);
  } finally {
    running = false;
  }
}

function stop() {
  if (firstTimer) clearTimeout(firstTimer);
  if (intervalTimer) clearInterval(intervalTimer);
  firstTimer = null;
  intervalTimer = null;
}

firstTimer = setTimeout(() => {
  console.log('[Watchdog] worker 启动定时巡检 (每 60s)');
  runCheck({ startupRecovery: true });
  intervalTimer = setInterval(runCheck, CHECK_INTERVAL_MS);
}, FIRST_CHECK_DELAY_MS);

parentPort?.on('message', (message) => {
  if (message?.type === 'shutdown') {
    stop();
    process.exit(0);
  }
});

process.on('SIGTERM', () => {
  stop();
  process.exit(0);
});
