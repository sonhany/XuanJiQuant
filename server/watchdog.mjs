/** 数据同步看门狗。研究调度由独立的确定性 ResearchTrainingScheduler 管理。 */
import { daemonMeta as syncMeta, startDaemon as startSync } from './sync_service_manager.mjs';

export function watchdogTick() {
  const meta = syncMeta();
  if (!meta.running) startSync({ codes: [] });
  return {
    last_check: new Date().toISOString(),
    sync_alive: syncMeta().running,
    automatic_execution_enabled: false,
  };
}
