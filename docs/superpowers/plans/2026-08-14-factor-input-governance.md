# Factor Input Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bind factor evaluation and ranking to one versioned, fresh, tradeable-universe data snapshot and keep every output research-only.

**Architecture:** A focused factor input contract validates the data snapshot and derives eligible codes. Existing batch evaluation and ranking consume that contract and propagate its version metadata; deterministic scheduling uses the same SQLite snapshot rather than treating the incomplete six-year Qlib manifest as the daily-factor input.

**Tech Stack:** Python 3, pandas, SQLite cache, pytest, React/TypeScript, Node contract tests.

---

### Task 1: Factor input contract

**Files:**
- Create: `quant/factor/input_contract.py`
- Create: `tests/test_factor_input_contract.py`
- Modify: `quant/data/snapshot.py`
- Modify: `tests/test_data_snapshot_contract.py`

- [x] Write failing tests for missing/stale snapshots, universe-hash mismatch, eligibility filtering and stable metadata.
- [x] Run `python -m pytest tests/test_factor_input_contract.py tests/test_data_snapshot_contract.py -q` and confirm failures are caused by the missing contract.
- [x] Implement the contract and non-authorizing snapshot warning metadata.
- [x] Re-run the focused tests and confirm they pass.

### Task 2: Bind offline evaluation and projections

**Files:**
- Modify: `scripts/evaluate_factors.py`
- Modify: `scripts/gpu_worker.py`
- Modify: `scripts/precompute_snapshot.py`
- Modify: `scripts/factor_runner.py`
- Modify: `scripts/factor_stock_detail_contract_tests.py`

- [x] Write failing tests proving ranking excludes ineligible codes, stale/version-mismatched snapshots fail closed, and single-stock calculation passes `code`.
- [x] Run the focused tests and confirm the expected failures.
- [x] Make evaluation iterate only contract codes and attach the contract metadata to pickle, JSON and evaluation outputs.
- [x] Make `factor_stocks` validate version and filter rows before sorting.
- [x] Re-run focused tests.

### Task 3: Deterministic scheduling boundary

**Files:**
- Modify: `scripts/research_training_scheduler.py`
- Modify: `tests/test_research_training_scheduler.py`
- Modify: `quant/research/job_store.py`

- [x] Write failing tests requiring the daily factor scheduler to load the passed SQLite snapshot and to normalize every successful factor result to `research_only`.
- [x] Run the tests and confirm failures.
- [x] Separate the daily-factor snapshot from the independent Qlib six-year manifest while preserving version-bound strategy prerequisites.
- [x] Re-run focused scheduler tests.

### Task 4: UI and documentation

**Files:**
- Modify: `components/FactorPanel.tsx`
- Modify: `scripts/factor_panel_contract_tests.mjs`
- Modify: `README.md`
- Modify: `docs/XUANJI_HANDOFF.md`
- Modify: `docs/XUANJI_SYSTEM_WORKFLOW_MAP.md`
- Modify: `docs/QLIB_LOCAL_TRAINING.md`

- [x] Add contract tests for version, universe policy, stale blocking and research-only labels.
- [x] Update the panel and handoff documents without adding any execution control.
- [x] Run the Node contract suite.

### Task 5: Runtime publication and verification

**Files:**
- Modify: `scripts/daily_update.py`
- Modify: `tests/test_data_snapshot_contract.py`

- [x] Write a failing test showing that coverage above the configured gate can publish `passed` while retaining non-fatal fetch warnings.
- [x] Implement coverage-based publication and persist warnings without granting execution authority.
- [x] Refresh or republish the current daily snapshot through the normal data path.
- [x] Run focused tests, full Python, Node contracts, TypeScript, Vite build, API verification and UI verification.
