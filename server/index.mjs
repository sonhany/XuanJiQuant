/**
 * XuanJiQuant 服务器入口
 * 默认 SQLite 存储 (data/quant.db，零外部依赖)，可选 Redis (QUANT_CACHE=redis)
 */
import http from 'http';
import { Worker } from 'worker_threads';
import { createRouter } from './router.mjs';
import { PORT, HOST } from './config.mjs';
import { closeDbLogWriter, writeDbLog } from './db_log_writer.mjs';
import { log } from './http-utils.mjs';
import { closeDataRunners } from './data-runners.mjs';
import { marketStreamService } from './market-stream-service.mjs';
import { stopWorkbenchCache } from './routes/workbench.mjs';

// ─── 创建 HTTP 服务器 ─────────────────────

const server = http.createServer(createRouter());
const sessionId = `${Date.now().toString(36)}-${process.pid}`;
let watchdogWorker = null;
let shuttingDown = false;

console.log('[DB] 默认存储: SQLite (data/quant.db)；如需 Redis 设环境变量 QUANT_CACHE=redis');

// ─── 启动监听 ─────────────────────────────

server.listen(PORT, HOST, () => {
  console.log(`[API Server] 本地代理服务器运行在 http://${HOST}:${PORT}`);
  log('INFO', `[API Server] session started sessionId=${sessionId} pid=${process.pid}`);
  marketStreamService.start();

  // Watchdog contains synchronous cross-process probes. Keep them off the
  // HTTP event loop so health checks and daemon recovery cannot stall APIs.
  watchdogWorker = new Worker(
    new URL('./watchdog_worker.mjs', import.meta.url),
    { type: 'module' },
  );
  watchdogWorker.on('error', (error) => {
    log('ERROR', `[WatchdogWorker] ${error?.stack || error}`);
  });
  watchdogWorker.on('message', (message) => {
    if (message?.type === 'db_log' && message.event) {
      writeDbLog(
        message.event.level,
        message.event.message,
        message.event.meta || {},
      );
    }
  });
  watchdogWorker.on('exit', (code) => {
    if (!shuttingDown && code !== 0) {
      log('ERROR', `[WatchdogWorker] exited code=${code}`);
    }
  });
});

server.on('error', (error) => {
  log('FATAL', `[API Server] listener error: ${error?.stack || error}`);
});

server.on('close', () => {
  log('INFO', '[API Server] listener closed');
});

function shutdown(signal, exitCode = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  log('WARN', `[API Server] shutdown requested: ${signal}`);
  watchdogWorker?.postMessage({ type: 'shutdown' });
  marketStreamService.stop();
  stopWorkbenchCache();
  closeDataRunners();

  const forceTimer = setTimeout(() => {
    log('FATAL', '[API Server] graceful shutdown timed out');
    closeDbLogWriter();
    process.exit(exitCode || 1);
  }, 5000);
  forceTimer.unref();

  server.close(() => {
    clearTimeout(forceTimer);
    watchdogWorker?.terminate();
    closeDbLogWriter();
    process.exit(exitCode);
  });
}

process.on('SIGINT', () => shutdown('SIGINT'));
process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('uncaughtException', (error) => {
  log('FATAL', `[API Server] uncaughtException: ${error?.stack || error}`);
  shutdown('uncaughtException', 1);
});
process.on('unhandledRejection', (reason) => {
  log('ERROR', `[API Server] unhandledRejection: ${reason?.stack || reason}`);
});
