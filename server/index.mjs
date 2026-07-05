/**
 * AlphaCouncil2 服务器入口
 * 默认 SQLite 存储 (data/quant.db，零外部依赖)，可选 Redis (QUANT_CACHE=redis)
 */
import http from 'http';
import { createRouter } from './router.mjs';
import { PORT, HOST } from './config.mjs';
import { watchdogTick } from './watchdog.mjs';

// ─── 创建 HTTP 服务器 ─────────────────────

const server = http.createServer(createRouter());

console.log('[DB] 默认存储: SQLite (data/quant.db)；如需 Redis 设环境变量 QUANT_CACHE=redis');

// ─── 启动监听 ─────────────────────────────

server.listen(PORT, HOST, () => {
  console.log(`[API Server] 本地代理服务器运行在 http://${HOST}:${PORT}`);

  // ─── 看门狗: daemon 自愈 + 持久进程保活 ──────
  // 首次延迟 30s (等所有路由模块的 PersistentRunner.ensure 完成), 之后每 60s 巡检一次。
  // 检查 paper_trader / ai_scheduler 两个 daemon 存活, 挂了自动拉起。
  setTimeout(() => {
    console.log('[Watchdog] 启动定时巡检 (每 60s)');
    watchdogTick();  // 启动后立即跑一次
    setInterval(watchdogTick, 60_000);
  }, 30_000);
});
