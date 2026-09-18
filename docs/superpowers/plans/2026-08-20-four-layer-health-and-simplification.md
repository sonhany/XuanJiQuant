# Four-Layer Health and Simplification Implementation Plan

> **For Codex:** Execute this plan in the active `C:\Users\HYSHEN\XuanJiQuant` workspace only. Use test-driven development and verify every completion claim with current evidence. The workspace is not a Git repository, so commit steps are intentionally omitted.

**Goal:** Make data, factor, strategy, and paper-execution health truthful and source-traceable; repair the Qlib benchmark failure; remove retired execution code; and preserve fail-closed, research-only/paper-only authority boundaries.

**Architecture:** Replace legacy cache-count health checks with one read-only four-layer health projection built from authoritative publication pointers, F4 evidence, F5 ledger state, and current data metadata. Keep research generation, strategy validation, and paper execution independent. Register the CSI 300 benchmark with the Qlib provider while excluding it from the train/trade universe through the existing instrument boundary.

**Tech Stack:** Python 3, SQLite, Redis-compatible cache, Qlib, Node.js contract tests, React/TypeScript, Vite.

---

### Task 1: Truthful four-layer health projection

- [x] Add failing Python tests for current/stale/missing data, factor publication identity, F4 rejected-versus-broken semantics, and F5 paper-only reconciliation state.
- [x] Implement a small pure health projection module with explicit `as_of`, expected date, freshness, coverage, source, status, reason, and authority fields.
- [x] Make the risk runner load authoritative artifacts and return the four-layer projection; remove the legacy cache-count and hard-coded strategy/execution checks.
- [x] Verify the risk API and workbench expose the same current facts without treating a research rejection as a system failure or old execution state as current.

### Task 2: Repair Qlib benchmark registration

- [x] Add a failing exporter/workflow test proving `SH000300` is provider-readable while excluded from the model/trading universe.
- [x] Correct the export contract so the benchmark is registered in Qlib instruments and retains features, while existing dataset/training exclusions prevent benchmark leakage.
- [x] Run focused Qlib provider and workflow tests, then repair/revalidate the current local Qlib artifact without granting execution authority.

### Task 3: Remove current frontend console error

- [x] Add a failing UI/source contract for unique audit-row React keys.
- [x] Use a stable row identity with an index fallback that remains unique for duplicate historical timestamps.
- [x] Run Node contracts, TypeScript, Vite build, browser/UI verification, and inspect the current console.

### Task 4: Retire unrelated execution code safely

- [x] Prove with repository search and tests that `quant/execution`, `scripts/verify_paper_rules.py`, and `scripts/smoke_test.py` have no active route, scheduler, or runtime consumer.
- [x] Replace the old validation-isolation assertion with a retirement-boundary test, then delete the retired package/scripts using explicit patches.
- [x] Preserve historical documentation, logs, databases, and audit names; update active README and handoff documentation to distinguish removed source from historical evidence.

### Task 5: Full verification and operational report

- [x] Run focused Python tests after each change and the full Python suite after integration.
- [x] Run all Node contracts, TypeScript checking, Vite build, Web verification, UI verification, and browser console inspection.
- [x] Re-query live data/factor/strategy/F5 endpoints and scheduled-task evidence; report health, freshness, remaining business gates, performance, changed/deleted files, and any manual action required.
