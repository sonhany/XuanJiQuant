# Data Management Control Plane Design

## Goal

Replace the disconnected data-management paths with one managed control plane
that can start, stop, observe, audit, and recover the realtime sync daemon and
manual data-update jobs without reporting fabricated progress or health.

## Architecture

### Realtime sync daemon

`server/sync_service_manager.mjs` is the only Node-side owner of
`quant.data.sync_service`. It starts and stops the Python process, records PID
metadata, and reports process liveness. The Python service writes a heartbeat
to `data:sync:daemon_status` every cycle with PID, watched code count, source
counts, last success, last error, and current market session.

The UI switch controls this manager directly. Local browser storage only
remembers the user's preference; it is never treated as daemon state.

### Manual updates

`server/update_manager.mjs` continues to run `scripts/daily_update.py`, but
persists task state to `data:update:status`. Progress, stderr tail, exit code,
parameters, timestamps, and results survive API-server restarts. Only one
manual update may run at a time.

The API accepts an optional validated stock-code list in addition to the
existing mode, limit, and worker count.

### Status and health

`/api/sync` exposes:

- `status`: canonical storage, universe, K-line coverage, source policy, source
  probes, and latest health report.
- `daemon_status`: manager process state plus Python heartbeat freshness.
- `update_progress`: persisted manual-update state.
- `health`: full-market integrity summary and source-probe results.
- `start` / `stop`: real daemon lifecycle operations.
- `start_update` / `stop_update`: manual update lifecycle operations.

No endpoint may infer daemon liveness from `stock:realtime:*` cache keys. No
endpoint may label a source online without a successful probe.

### Source health

The source-health collector records explicit results for TdxQuant, Sina,
Tencent, AkShare, Baostock, Jin10, and optional Tushare. Each result contains
status, latency, checked time, success/failure count, and the latest error.
Unavailable optional sources are reported as `unconfigured`, not `online`.

### Audit

Every daemon start/stop, manual update start/finish/failure/stop, health check,
and source probe writes a structured `audit_events` row. Payloads include
parameters, PID, data scope, result counts, source, timing, and errors.
Generic HTTP server logs remain supplementary.

### Watchdog

The server watchdog includes the realtime sync daemon. It restarts the daemon
only when `data:sync:config.enabled` is true and the managed process or
heartbeat is stale. Restart attempts and failures are audited.

## Frontend

The Data Management panel shows:

- actual daemon state, PID, heartbeat age, watched-code count, last success,
  last error, and source distribution;
- manual-update mode, PID, progress, scope, stderr tail, and final result;
- SQLite key count, universe size, K-line coverage, latest data date, and
  optional ClickHouse state;
- source-health table with latency and last check;
- full-market data-health summary and issue counts;
- optional comma-separated stock codes for selective manual updates.

The panel never uses the words "running" or "online" unless the backend has
verified that state.

## Error Handling

- A failed daemon spawn returns an error and leaves `enabled=false`.
- A stale heartbeat is shown separately from process liveness.
- A backend restart reloads persisted task state and marks orphaned tasks
  `interrupted` when their PID is no longer alive.
- stderr is retained as a bounded tail instead of discarded.
- Source probes have strict timeouts and never block the page indefinitely.
- Health-check failures return a partial report with explicit errors.

## Compatibility

Existing `start_update`, `stop_update`, `update_progress`, `status`, and
`daemon_status` actions remain available. The legacy
`sync:cmd:trigger:*`, `sync:popular_progress`, `sync:full_progress`, and
60-second completion heuristic are removed.

## Verification

- Node contract tests cover route semantics, manager lifecycle contracts,
  removal of legacy keys, and watchdog integration.
- Python tests cover heartbeat payloads, source aggregation, selective code
  normalization, and full-market health summaries.
- API smoke tests verify truthful idle/running states without launching a
  destructive full-market update.
- Browser verification checks the Data Management panel, console, refresh
  behavior, and responsive layout.

