# Complete Six-Year PIT Data and F4 References Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the governed six-year A-share PIT dataset, truthful quality report, effective-dated historical industry reference, and versioned CSI 300 benchmark required by F4.

**Architecture:** Keep TdxQuant as the recent-price primary source and use AkShare only for the history prefix or symbol fallback already defined by the approved PIT design. Treat the collection manifest, quality report, historical-industry reference, and benchmark as four separately hashed inputs; F4 remains fail-closed until every input passes. All outputs stay under `data/qlib` or `data/research`, remain `research_only`, and never acquire execution authority.

**Tech Stack:** Python 3.14, pyqlib venv, pandas, TdxQuant local HTTP, AkShare/CNINFO, pytest, JSON/SHA-256.

---

### Task 1: Repair the truthful coverage gate

**Files:**
- Modify: `quant/qlib/quality_gate.py`
- Modify: `scripts/qlib_job_worker.py`
- Test: `tests/test_qlib_quality_gate.py`
- Test: `tests/test_qlib_job_worker.py`

- [x] Add a failing test proving `1/5502` cannot pass even when the one observed symbol has complete lifecycle dates.
- [x] Run the focused test and confirm it fails because lifecycle coverage replaces universe coverage.
- [x] Compute effective coverage as the minimum of completed/requested and lifecycle sample coverage; include `status=passed|failed` and reject a non-complete manifest.
- [x] Run focused quality and worker tests.

### Task 2: Repair collection-universe and manifest finalization

**Files:**
- Modify: `quant/qlib/collector.py`
- Modify: `scripts/qlib_job_worker.py`
- Test: `tests/test_qlib_collector.py`

- [x] Add a failing test proving a delisted reference without a known delisting date is not injected into the six-year requested universe.
- [x] Add a failing test proving an exhausted collection with at least 98% complete artifacts may finalize its manifest while retaining all failures for audit.
- [x] Filter delisted additions to known dates within the requested interval and distinguish `collection_complete` from `quality_passed`.
- [x] Make worker count and failure-abort settings explicit, bounded environment configuration.
- [x] Run focused collector tests.

### Task 3: Build effective-dated industry and benchmark references

**Files:**
- Create: `quant/qlib/f4_references.py`
- Create: `scripts/build_f4_market_references.py`
- Test: `tests/test_f4_market_references.py`

- [x] Add failing tests for industry effective-date ordering, no current-industry backfill, 95% coverage, benchmark 99% coverage, stable versions, and checkpoint resume.
- [x] Implement CNINFO industry-change normalization using classification standard `008002`, preserving effective dates and source fields.
- [x] Implement CSI 300 daily benchmark normalization with date coverage, duplicate/OHLC checks, and SHA-256 version identity.
- [x] Write atomic outputs to `data/research/industry/pit_industry.json` and `data/research/benchmarks/000300.json`.
- [x] Run focused tests and a small live source probe.

### Task 4: Complete the six-year dataset

**Files:**
- Runtime data: `data/qlib/datasets/a_share_6y_daily/**`
- Runtime data: `data/qlib/qlib_bin/a_share_6y_daily/**`

- [x] Verify no overlapping Qlib collection/export worker is running.
- [x] Refresh reference data and run the resumable collector for `2020-08-01` through the fixed 2026-08-14 completed-trading-day cutoff.
- [x] Monitor checkpoints, source failure ratios, artifact hashes, disk space, and process liveness; never mark a failed symbol complete.
- [x] Run point-in-time rebuild and truthful quality gate.
- [x] Export only after manifest and quality provenance agree.

### Task 5: Complete historical industry and benchmark data

**Files:**
- Runtime data: `data/research/industry/pit_industry.json`
- Runtime data: `data/research/benchmarks/000300.json`

- [x] Run the resumable CNINFO industry-history collection for the governed universe.
- [x] Fetch and version the CSI 300 benchmark for the exact dataset period.
- [x] Verify effective-date, coverage, latest-date, source and hash contracts.

### Task 6: F4 integration and handoff

**Files:**
- Modify: `README.md`
- Modify: `docs/XUANJI_HANDOFF.md`
- Modify: `docs/XUANJI_SYSTEM_WORKFLOW_MAP.md`

- [x] Run `scripts/validate_strategy_portfolios.py --once` and verify it consumes all four exact versions.
- [x] Verify `/api/strategy market_scan` exposes the new input status without execution authority.
- [x] Run focused and full Python tests, Node contracts, TypeScript and Vite build.
- [x] Record exact dataset/industry/benchmark versions, coverage, remaining exclusions and F4 status in handoff docs.

## Completion criteria

- Manifest collection finalized for the exact six-year version, with every requested symbol either hash-complete or explicitly failed.
- Universe coverage is at least 98%, recent coverage at least 99%, at least 1200 trading days, and all hard data errors are zero.
- Historical industry is effective-dated with at least 95% eligible-sample coverage; no current category is backfilled before its first effective date.
- CSI 300 coverage is at least 99% for the dataset calendar and is version/hash bound.
- F4 reads these exact inputs and remains `promotion_state=research_only`, `execution_authority=false` regardless of research result.
