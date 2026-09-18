function pidAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

export function runtimeMetaFromPersisted(status = {}) {
  const persistedRunning = status?.daemon_running ?? status?.running;
  const pid = Number(status?.daemon_pid ?? status?.pid);
  if (persistedRunning !== true || !pidAlive(pid)) {
    return { running: false, pid: null, started_at: null };
  }
  return {
    running: true,
    pid,
    started_at: status?.started_at || null,
  };
}
