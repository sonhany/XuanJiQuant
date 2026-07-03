/**
 * 兼容层: 历史文件名 ai_loop_manager 实际管理的是 ai_scheduler.py。
 *
 * 新代码请直接 import ./ai_scheduler_manager.mjs。
 * 保留本文件是为了避免旧 import 失效。
 */
export { startDaemon, stopDaemon, daemonMeta } from './ai_scheduler_manager.mjs';
