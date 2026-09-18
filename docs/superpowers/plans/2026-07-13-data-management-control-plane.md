# Data Management Control Plane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one truthful and recoverable control plane for realtime data synchronization, manual data updates, health, source status, audit, and UI observability.

**Architecture:** A Node manager owns the Python realtime daemon, while both the daemon and manual updater persist structured state in the existing SQLite cache. `/api/sync` becomes the canonical API and the frontend renders only verified state.

**Tech Stack:** Node.js ESM, Python 3, SQLite cache, React 19, TypeScript, pytest, Node assertion tests, browser verification.

---

### Task 1: Lock Down Required Contracts

**Files:**
- Create: `scripts/sync_control_plane_contract_tests.mjs`
- Create: `tests/test_sync_service_status.py`

- [ ] Write tests requiring a real manager, persisted status keys, no legacy
  trigger/progress keys, bounded stderr, full-market health, structured audit,
  and watchdog integration.
- [ ] Run both tests and verify they fail because the control plane is absent.

### Task 2: Add Realtime Daemon Status and Manager

**Files:**
- Create: `server/sync_service_manager.mjs`
- Modify: `quant/data/sync_service.py`

- [ ] Add PID-based process management with hidden Windows process creation.
- [ ] Persist `data:sync:config` and `data:sync:daemon_status`.
- [ ] Write heartbeat state every cycle and on shutdown/error.
- [ ] Run focused tests until green.

### Task 3: Persist Manual Update State

**Files:**
- Modify: `server/update_manager.mjs`
- Modify: `scripts/daily_update.py`

- [ ] Persist `data:update:status` for every state transition.
- [ ] Capture a bounded stderr tail and explicit exit results.
- [ ] Accept and validate an optional code list.
- [ ] Mark orphaned persisted tasks interrupted after a server restart.
- [ ] Run focused tests until green.

### Task 4: Replace Sync API Semantics

**Files:**
- Modify: `server/routes/sync.mjs`
- Create: `quant/data/source_health.py`
- Modify: `quant/data/health.py`

- [ ] Route `start` and `stop` through the daemon manager.
- [ ] Remove legacy trigger keys and 60-second fake completion.
- [ ] Build status from `stock:universe`, SQLite cache metrics, source policy,
  daemon heartbeat, manual update status, and full-market health.
- [ ] Add bounded source probes and truthful `online/offline/unconfigured`
  statuses.
- [ ] Add structured audit events for lifecycle and health operations.
- [ ] Run focused tests until green.

### Task 5: Integrate Watchdog

**Files:**
- Modify: `server/watchdog.mjs`
- Modify: `server/index.mjs`

- [ ] Monitor the sync daemon only when its persisted config is enabled.
- [ ] Restart stale or dead managed daemons and record the result.
- [ ] Include sync state in `ai:watchdog:latest`.
- [ ] Run focused tests until green.

### Task 6: Upgrade Data Management UI

**Files:**
- Modify: `components/DbPanel.tsx`

- [ ] Add verified daemon status, heartbeat, PID, source counts, and errors.
- [ ] Add storage, full-market coverage, health issues, and source-health views.
- [ ] Add validated selective stock-code input for manual updates.
- [ ] Show persisted stderr/result information without changing other Data
  Browser tabs.
- [ ] Run TypeScript build and UI contract tests.

### Task 7: Documentation and Full Verification

**Files:**
- Modify: `README.md`

- [ ] Document the unified control plane, actions, state keys, audit events, and
  recovery semantics.
- [ ] Run Python tests, Node contract tests, security tests, and production
  build.
- [ ] Restart the API if required and run read-only API smoke checks.
- [ ] Verify the Data Management page through the browser without starting a
  full-market update.

