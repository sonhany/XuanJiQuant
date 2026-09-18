# Deterministic Research Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, auditable research pipeline that schedules factor, strategy, and Qlib training; validates six-year PIT data; migrates obsolete active Qlib paths; and projects only gate-passed read-only research evidence into Agent decisions.

**Architecture:** A pure scheduling module determines due work and stable idempotency keys. A SQLite-backed research job store owns leases, heartbeats, retries, and terminal audit state, while a standalone scheduler invokes existing internal factory and Qlib entry points. A fail-closed projector validates Registry, quality, hashes, backtests, shadow-factor state, and freshness before intersecting research symbols with the fresh screener pool.

**Tech Stack:** Python 3.14, SQLite, pytest, Node.js ESM contract tests, React/TypeScript, Vite.

---

## File responsibilities

- `quant/research/training_schedule.py`: pure A-share calendar due rules, Qlib priority, and stable idempotency identities.
- `quant/research/job_store.py`: independent research task ledger, singleton leases, heartbeats, interruption recovery, and promotion-state guard.
- `scripts/research_training_scheduler.py`: daemon/one-shot coordinator that calls factories and Qlib jobs as internal functions only.
- `quant/agent/research_evidence.py`: read-only Qlib and shadow-factor validation, bounded projection, and fresh-pool intersection.
- `scripts/qlib_path_migration.py`: dry-run scan, hash backup, transactional normalization, invalidation, audit, and post-scan.
- `quant/qlib/collector.py`: deterministic bounded worker queue, artifact hashes, lifecycle-aware checkpoint resume, and no partial publication.
- `quant/qlib/sources.py`: bounded source timeouts, circuit breaker state, and fixed fallback order.
- `scripts/qlib_schedule.py`: shared weekly/monthly/quarterly mode selection and single-heavy-job enforcement.
- `scripts/agent_runner.py`: merges verified research projection into `approved_research` without reusing stale evidence.
- `quant/agent/runtime.py`: ensures portfolio candidates remain the intersection of fresh screening and research evidence.
- `ai_tools.json`: removes factor/strategy factories and aliases from Agent-visible tools.
- `scripts/start_services.mjs`: supervises the research scheduler as a project-owned process.
- `README.md`, `docs/XUANJI_HANDOFF.md`, `docs/QLIB_LOCAL_TRAINING.md`: architecture, schedule, recovery, safety boundary, and acceptance commands.

### Task 1: Pure deterministic training schedule

**Files:**
- Create: `quant/research/__init__.py`
- Create: `quant/research/training_schedule.py`
- Create: `tests/test_research_training_schedule.py`

- [ ] **Step 1: Write failing due-rule tests**

```python
from datetime import date, datetime
from quant.research.training_schedule import due_research_jobs


def test_factor_is_due_after_1620_on_trading_day():
    jobs = due_research_jobs(
        now=datetime(2026, 8, 7, 16, 20),
        trading_days={date(2026, 8, 7)},
        data_version="pit-v1",
        factor_version="factor-v1",
        strategy_version="strategy-v1",
    )
    assert jobs[0].idempotency_key == "factor_daily:2026-08-07:pit-v1:factor-v1"


def test_quarterly_qlib_replaces_monthly_and_weekly():
    jobs = due_research_jobs(
        now=datetime(2026, 10, 3, 18, 30),
        trading_days={date(2026, 10, 2)},
        data_version="pit-v1",
        factor_version="factor-v1",
        strategy_version="strategy-v1",
    )
    assert [job.kind for job in jobs if job.kind.startswith("qlib_")] == ["qlib_quarterly"]
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests\test_research_training_schedule.py -q`

Expected: collection fails because `quant.research.training_schedule` does not exist.

- [ ] **Step 3: Implement immutable `ScheduledResearchJob` values and due rules**

Implement `factor_daily` at 16:20 on a trading day, `strategy_weekly` at Saturday 10:00, and Qlib at Saturday 18:30 with `quarterly > monthly > weekly`. Identity strings include market date/ISO week, data version, and factory version.

- [ ] **Step 4: Run the test file and verify GREEN**

Run: `python -m pytest tests\test_research_training_schedule.py -q`

Expected: all schedule tests pass.

### Task 2: Research job ledger and singleton lease

**Files:**
- Create: `quant/research/job_store.py`
- Create: `tests/test_research_job_store.py`

- [ ] **Step 1: Write failing lease and state tests**

```python
from datetime import datetime, timedelta, timezone
from quant.research.job_store import ResearchJobStore


def test_idempotency_and_heavy_lease_are_atomic(tmp_path):
    store = ResearchJobStore(tmp_path / "research_jobs.db")
    first = store.claim("qlib_weekly:2026-W32:v1:q1", kind="qlib_weekly", heavy=True, owner_pid=123)
    assert first.claimed is True
    assert store.claim("qlib_weekly:2026-W32:v1:q1", kind="qlib_weekly", heavy=True, owner_pid=124).claimed is False
    assert store.claim("qlib_monthly:2026-08:v1:q1", kind="qlib_monthly", heavy=True, owner_pid=125).claimed is False


def test_expired_owner_becomes_interrupted_before_retry(tmp_path):
    store = ResearchJobStore(tmp_path / "research_jobs.db")
    claim = store.claim("factor_daily:2026-08-07:v1:f1", kind="factor_daily", heavy=False, owner_pid=123)
    store.recover_expired(now=datetime.now(timezone.utc) + timedelta(minutes=10), process_alive=lambda _pid: False)
    assert store.get(claim.job_id)["status"] == "interrupted"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests\test_research_job_store.py -q`

Expected: collection fails because `quant.research.job_store` does not exist.

- [ ] **Step 3: Implement the SQLite ledger**

Use a unique `idempotency_key`, transactional heavy-lease claim, owner PID/token, stage/progress/heartbeat, bounded retry metadata, terminal states, and an audit table. Reject all scheduler attempts to write `paper_active`, `production_candidate`, `approved`, or `live`.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest tests\test_research_job_store.py -q`

Expected: all job-store tests pass.

### Task 3: Deterministic scheduler coordinator and hidden factories

**Files:**
- Create: `scripts/research_training_scheduler.py`
- Create: `tests/test_research_training_scheduler.py`
- Modify: `ai_tools.json`
- Modify: `tests/test_agent_tool_registry.py`
- Modify: `scripts/start_services.mjs`
- Modify: `scripts/service_lifecycle_contract_tests.mjs`

- [ ] **Step 1: Write failing coordinator and tool-boundary tests**

```python
def test_agent_registry_hides_research_factories():
    registry = load_registry()
    assert "run_factor_factory" not in registry.tools
    assert "run_strategy_factory" not in registry.tools
    assert "review_signal_quality" not in registry.aliases


def test_scheduler_blocks_strategy_without_matching_factor_success(tmp_path):
    result = run_due_once(now=SATURDAY_1000, store=empty_store(tmp_path), data_snapshot=ready_snapshot())
    assert result[0]["status"] == "blocked"
    assert result[0]["reason_code"] == "factor_prerequisite_missing"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests\test_research_training_scheduler.py tests\test_agent_tool_registry.py -q`

Expected: scheduler module is missing and existing tool assertions expose both factories.

- [ ] **Step 3: Implement the internal coordinator and service ownership**

The coordinator uses the pure due rules, claims jobs before execution, checks data/factor prerequisites, calls existing factory functions through internal imports, heartbeats the ledger, and records terminal evidence. Service startup identifies the process as `research-training-scheduler`; no HTTP or Agent action can directly trigger it.

- [ ] **Step 4: Remove visible factory tools and aliases**

Delete the two tool objects and `review_signal_quality` alias from `ai_tools.json`; keep their Python functions unchanged as scheduler internals.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `python -m pytest tests\test_research_training_scheduler.py tests\test_agent_tool_registry.py -q; node scripts\service_lifecycle_contract_tests.mjs`

Expected: all tests pass and the lifecycle contract reports success.

### Task 4: Six-year PIT collection and versioned quality gate

**Files:**
- Modify: `quant/qlib/collector.py`
- Modify: `quant/qlib/sources.py`
- Modify: `quant/qlib/quality_gate.py`
- Modify: `tests/test_qlib_collector.py`
- Modify: `tests/test_qlib_sources.py`
- Modify: `tests/test_qlib_quality_gate.py`

- [ ] **Step 1: Write failing deterministic-worker, hash, and lifecycle tests**

```python
def test_worker_count_is_bounded_and_manifest_hashes_every_artifact(tmp_path):
    result = collect_six_year_dataset(SYMBOLS, START, END, tmp_path, workers=99, track_fetcher=fake_tracks, reference_data=REFERENCE)
    assert result["worker_count"] == 8
    manifest = json.loads((tmp_path / "manifest.json").read_text("utf-8"))
    assert all(len(item["artifact_sha256"]) == 64 for item in manifest["symbols"].values())


def test_quality_coverage_uses_lifecycle_denominator():
    report = check_dataset_quality_from_manifest(manifest_with_new_listing_and_delisting())
    assert report["metrics"]["coverage"] == 1.0
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests\test_qlib_collector.py tests\test_qlib_sources.py tests\test_qlib_quality_gate.py -q`

Expected: new worker/hash/lifecycle APIs are absent.

- [ ] **Step 3: Implement bounded collection and fail-closed publication**

Use a sorted queue, default four workers and hard maximum eight, checkpoint every 25 completions, per-source timeout/circuit state, artifact SHA-256 and schema/range validation before reuse. Keep incomplete manifests at `status=incomplete`; quality/export/training checks require `status=complete` and matching manifest hash.

- [ ] **Step 4: Implement lifecycle-aware quality calculation**

Compute expected rows only between each symbol's listing and delisting dates and require the existing `qlib_phase1_gate_v1` thresholds without relaxation.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `python -m pytest tests\test_qlib_collector.py tests\test_qlib_sources.py tests\test_qlib_quality_gate.py tests\test_qlib_point_in_time.py -q`

Expected: all targeted Qlib data tests pass.

### Task 5: Audited obsolete-path migration

**Files:**
- Create: `scripts/qlib_path_migration.py`
- Create: `tests/test_qlib_path_migration.py`

- [ ] **Step 1: Write failing migration tests**

```python
def test_dry_run_never_mutates_and_reports_nested_paths(tmp_path):
    before = sha256(DB)
    report = migrate(db_path=DB, active_root=ACTIVE, dry_run=True)
    assert report["obsolete_active_count"] > 0
    assert sha256(DB) == before


def test_missing_target_is_invalidated_and_active_obsolete_count_is_zero(tmp_path):
    report = migrate(db_path=DB, active_root=ACTIVE, dry_run=False)
    assert report["post_scan_obsolete_active_count"] == 0
    assert report["backup_sha256"]
    assert load_missing_row(DB)["path"] == ""
    assert load_missing_row(DB)["status"] == "missing_historical"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests\test_qlib_path_migration.py -q`

Expected: migration module is missing.

- [ ] **Step 3: Implement dry-run, backup, transaction, and post-scan**

Scan path columns plus nested JSON in `datasets`, `experiments`, `models`, `workflow_runs`, and `jobs`. Never dereference a frozen path. Map by relative suffix only when the active target exists; otherwise clear the active path and mark the row invalid without changing historical audit/error fields. Store original values in a migration audit event inside the same transaction.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest tests\test_qlib_path_migration.py tests\test_qlib_paths.py tests\test_qlib_registry.py -q`

Expected: all path tests pass.

### Task 6: Fail-closed Agent research evidence projection

**Files:**
- Create: `quant/agent/research_evidence.py`
- Create: `tests/test_research_evidence.py`
- Modify: `scripts/agent_runner.py`
- Modify: `quant/agent/runtime.py`
- Modify: `tests/test_agent_runtime.py`

- [ ] **Step 1: Write failing projector tests**

```python
def test_qualified_qlib_and_shadow_factor_are_projected(tmp_path):
    evidence = project_research_evidence(registry=qualified_registry(tmp_path), now=NOW, fresh_pool={"600817"})
    assert {row["source"] for row in evidence} == {"qlib", "shadow_factor"}
    assert {row["instrument"] for row in evidence} == {"600817"}
    assert all(row["execution_authority"] is False for row in evidence)


@pytest.mark.parametrize("mutation", ["expired", "tampered", "gate_failed", "order_field", "non_finite"])
def test_invalid_research_is_removed(mutation, tmp_path):
    evidence = project_research_evidence(registry=mutated_registry(tmp_path, mutation), now=NOW, fresh_pool={"600817"})
    assert evidence == []


def test_research_cannot_expand_fresh_candidate_pool(tmp_path):
    evidence = project_research_evidence(registry=qualified_registry(tmp_path, instrument="300450"), now=NOW, fresh_pool={"600817"})
    assert evidence == []
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests\test_research_evidence.py tests\test_agent_runtime.py -q`

Expected: projector module is missing.

- [ ] **Step 3: Implement bounded hash/freshness/gate validation**

Validate quality report/gate version, manifest and artifact hashes, workflow state, dual-backtest signal-hash equality, candidate-only gate, shadow health/promotion/hash metrics, finite values, and forbidden execution keys. Return bounded native records with references and explicit false execution authority.

- [ ] **Step 4: Integrate the projection and preserve reduction authority**

`agent_runner` builds the fresh screener set, loads a read-only Registry, and replaces screen-only `approved_research` with screen rows plus valid projected records. Runtime candidate projection intersects every requested code with the fresh screen pool; absence of research evidence never blocks risk-reducing actions.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `python -m pytest tests\test_research_evidence.py tests\test_agent_runtime.py tests\test_agent_evidence.py -q`

Expected: all research-evidence and runtime tests pass.

### Task 7: Shared Qlib mode selection and no-overlap boundary

**Files:**
- Modify: `scripts/qlib_schedule.py`
- Modify: `tests/test_qlib_schedule.py`

- [ ] **Step 1: Write failing automatic-mode tests**

```python
def test_auto_mode_prioritizes_quarterly_over_monthly_and_weekly():
    assert select_mode(datetime(2026, 10, 3, 18, 30), trading_days=CALENDAR) == "quarterly"


def test_heavy_cycle_refuses_overlap(tmp_path):
    store = Registry(tmp_path / "qlib_meta.db")
    insert_running_heavy(store)
    assert run_registered_cycle(mode="auto", store=store)["reason_code"] == "heavy_job_active"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests\test_qlib_schedule.py -q`

Expected: `select_mode` or auto mode is absent.

- [ ] **Step 3: Implement shared selection and preserve one heavy job**

Select exactly one weekly/monthly/quarterly chain, register token/PID/stage/heartbeat, and refuse overlap before dispatch. Keep all gate and artifact completeness checks in the existing cycle.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest tests\test_qlib_schedule.py tests\test_qlib_jobs.py tests\test_qlib_job_worker.py -q`

Expected: all schedule/job tests pass.

### Task 8: Documentation and architecture handoff

**Files:**
- Modify: `README.md`
- Modify: `docs/XUANJI_HANDOFF.md`
- Modify: `docs/QLIB_LOCAL_TRAINING.md`

- [ ] **Step 1: Add architecture contract checks**

Extend `scripts/research_boundary_contract_tests.mjs` so it checks documentation names `ResearchTrainingScheduler`, `ResearchJobStore`, `ResearchEvidenceProjector`, the active Qlib root, the three schedules, and the no-auto-promotion boundary.

- [ ] **Step 2: Run the contract and verify RED**

Run: `node scripts\research_boundary_contract_tests.mjs`

Expected: documentation assertions fail before the new sections are written.

- [ ] **Step 3: Document relationships, operations, and completion definitions**

Add a data-to-training-to-evidence-to-Agent flow, schedule table, recovery commands, migration dry-run/apply commands, current-root rule, acceptance matrix, and separate definitions for code completion, six-year PIT completion, and Qlib phase-one acceptance.

- [ ] **Step 4: Run the contract and verify GREEN**

Run: `node scripts\research_boundary_contract_tests.mjs`

Expected: the research boundary contract passes.

### Task 9: Full verification and truthful acceptance report

**Files:**
- Verify only; no production change is authorized by this task.

- [ ] **Step 1: Run targeted and full Python tests**

Run: `python -m pytest tests\test_research_training_schedule.py tests\test_research_job_store.py tests\test_research_training_scheduler.py tests\test_qlib_path_migration.py tests\test_research_evidence.py tests\test_qlib_schedule.py tests\test_qlib_collector.py tests\test_qlib_sources.py tests\test_qlib_quality_gate.py -q`

Run: `python -m pytest -q`

Expected: zero failures; any skip is reported by name.

- [ ] **Step 2: Run all Node contracts, TypeScript, and Vite**

Run: `Get-ChildItem scripts -Filter '*contract_tests.mjs' | Sort-Object Name | ForEach-Object { node $_.FullName; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } }`

Run: `npx tsc --noEmit`

Run: `npm run build`

Expected: every command exits 0.

- [ ] **Step 3: Run Web/UI/API and browser-console verification**

Run the repository's `scripts/web_verify.mjs`, UI verification script, API smoke suite, and browser console inspection against `127.0.0.1:8888` and `127.0.0.1:8880`, without real orders.

Expected: zero failed checks and no uncaught browser errors.

- [ ] **Step 4: Run read-only Qlib acceptance and cross-reconcile data evidence**

Run: `python scripts\qlib_acceptance.py`

Expected for “Qlib 第一阶段验收完成”: exit 0 plus Alpha158, Alpha360, LightGBM, XGBoost, Linear, dual backtests, shadow signal, and two complete same-mode schedule successes. If external collection is incomplete or the command exits nonzero, report exact blockers and do not lower thresholds or claim data completion.

## Self-review result

- Spec coverage: all twelve design sections map to Tasks 1-9, including deterministic schedules, PIT data, migration, evidence admission, no promotion, recovery, documentation, and separate completion labels.
- Completeness scan: implementation steps and error-handling behavior are fully specified without deferred work markers.
- Type consistency: schedule identities, job ledger fields, evidence projection fields, and status names are consistent across tasks.
- Repository constraint: `.git` is absent, so the plan intentionally contains no commit commands; verification artifacts and file paths provide the audit trail for this workspace.
