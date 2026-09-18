# Research Layer Scheduling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved event-driven schedule for daily data, daily factors, daily research selections, Saturday Qlib PIT work, and Sunday F4 validation while preserving research-only authority.

**Architecture:** Keep Windows Task Scheduler as the small set of external clocks and use deterministic Python gates between stages. Extend the existing research ledger for daily selection ownership, add a pure selection builder plus a thin CLI, and make the daily pipeline validate every artifact before advancing. Separate Saturday Qlib due rules from Sunday strategy due rules so F4 never races the weekly PIT refresh.

**Tech Stack:** Python 3.14, pytest, SQLite `ResearchJobStore`, pandas/Parquet, PowerShell ScheduledTasks, Node contract tests, existing Vite frontend verification.

**Repository note:** This workspace has no `.git`; replace commit steps with an evidence checkpoint containing changed files and fresh test output. Do not initialize Git as part of this plan.

---

### Task 1: Separate daily, Saturday Qlib, and Sunday strategy due rules

**Files:**
- Modify: `quant/research/training_schedule.py`
- Modify: `tests/test_research_training_schedule.py`
- Modify: `tests/test_research_training_scheduler.py`

- [ ] **Step 1: Write failing schedule tests**

Add assertions that Friday 16:20 yields daily factor and selection work, Saturday 18:30 yields Qlib but no strategy, and Sunday 10:00 yields strategy but no Qlib:

```python
def test_daily_factor_and_selection_are_due_after_cutoff():
    jobs = _due(datetime(2026, 8, 7, 16, 20))
    assert [job.kind for job in jobs] == ["factor_daily", "research_selection_daily"]


def test_saturday_qlib_precedes_sunday_strategy():
    saturday = _due(datetime(2026, 8, 8, 18, 30))
    sunday = _due(datetime(2026, 8, 9, 10, 0))
    assert "qlib_weekly" in [job.kind for job in saturday]
    assert "strategy_weekly" not in [job.kind for job in saturday]
    assert "strategy_weekly" in [job.kind for job in sunday]
    assert not any(job.kind.startswith("qlib_") for job in sunday)
```

- [ ] **Step 2: Run RED verification**

Run:

```powershell
python -m pytest tests\test_research_training_schedule.py -q
```

Expected: failures because `research_selection_daily` is absent and strategy remains Saturday-only.

- [ ] **Step 3: Implement minimal due-rule changes**

Add immutable constants and return jobs in dependency order:

```python
FACTOR_CUTOFF = time(16, 20)
QLIB_WEEKDAY = 5
QLIB_CUTOFF = time(18, 30)
STRATEGY_WEEKDAY = 6
STRATEGY_CUTOFF = time(10, 0)
```

Daily selection identity must include the market date, daily data version, factor factory version, F4 validation ID and portfolio policy version. Extend `due_research_jobs` with `f4_validation_id` and `portfolio_policy_version` inputs; `_load_runtime_inputs` resolves them from the current F4 projection and policy evidence before scheduling. Construct:

```python
f"research_selection_daily:{market_date}:{data_version}:{factor_version}:{f4_validation_id}:{portfolio_policy_version}"
```

Return Saturday Qlib work only on `QLIB_WEEKDAY`; return Sunday strategy work only on `STRATEGY_WEEKDAY`.

- [ ] **Step 4: Run GREEN verification**

```powershell
python -m pytest tests\test_research_training_schedule.py tests\test_research_training_scheduler.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Record checkpoint**

Record modified files and the exact passing test count in the final evidence log because Git is unavailable.

### Task 2: Build a deterministic daily research-selection artifact

**Files:**
- Create: `quant/strategy/research_selection.py`
- Create: `tests/test_research_selection.py`

- [ ] **Step 1: Write failing builder tests**

Create small in-memory factor, industry and F4 fixtures and assert deterministic output:

```python
def test_rejected_f4_builds_diagnostic_research_only_portfolio():
    result = build_research_selection(
        factor_snapshot=_factor_snapshot(),
        factor_evaluation=_factor_evaluation(),
        f4_latest=_f4_latest(status="f4_rejected"),
        candidate_spec=_candidate_spec(),
        industry_records=_industries(),
        generated_at="2026-08-19T17:00:00+08:00",
    )
    assert result["selection_status"] == "diagnostic_research_portfolio"
    assert result["source_validation_rejected"] is True
    assert result["promotion_state"] == "research_only"
    assert result["execution_authority"] is False
    assert result["not_a_trade_signal"] is True
    assert sum(row["target_weight"] for row in result["positions"]) + result["cash_weight"] == 1.0
```

Add separate tests for version mismatch, missing factor fit, industry cap, stable `portfolio_id`, and exclusion of ineligible rows.

- [ ] **Step 2: Run RED verification**

```powershell
python -m pytest tests\test_research_selection.py -q
```

Expected: import failure because the builder does not exist.

- [ ] **Step 3: Implement the pure builder**

Implement `build_research_selection(...) -> dict[str, Any]` with these exact responsibilities:

1. Validate factor snapshot and evaluation date/version equality.
2. Read the latest frozen `factor_fits[-1]` from the F4 candidate spec.
3. Rank each selected factor cross-sectionally and apply frozen direction and weight.
4. Resolve effective-dated industry as of the selection date.
5. Call existing `PortfolioPolicy` and `build_target_weights`.
6. Add per-name score, target weight, reference close and top three factor contributions.
7. Hash canonical content excluding `generated_at` into `portfolio_id`.
8. Force research-only and no-execution fields regardless of input values.

Raise `ResearchSelectionBlocked(reason_code, detail)` for every failed prerequisite; do not return partial current output.

- [ ] **Step 4: Run GREEN verification**

```powershell
python -m pytest tests\test_research_selection.py tests\test_f4_portfolio.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Record checkpoint**

Record the builder schema version, test count and changed files.

### Task 3: Add the selection CLI and scheduler-owned ledger job

**Files:**
- Create: `scripts/generate_research_portfolio.py`
- Modify: `scripts/research_training_scheduler.py`
- Modify: `tests/test_research_training_scheduler.py`
- Create: `tests/test_generate_research_portfolio.py`

- [ ] **Step 1: Write failing CLI and scheduler tests**

Assert atomic versioned/latest output and scheduler ownership:

```python
def test_selection_handler_invokes_only_deterministic_generator(monkeypatch):
    calls = []
    monkeypatch.setattr(
        scheduler,
        "_run_deterministic_research_script",
        lambda name, *args, **kwargs: calls.append((name, args)) or {"success": True},
    )
    result = scheduler._selection_handler(_selection_job(), lambda *_args: None)
    assert calls == [("generate_research_portfolio.py", ("--once",))]
    assert result["execution_authority"] is False
```

Also assert `_block_reason` requires the exact successful factor job and that repeated selection claims are idempotent.

- [ ] **Step 2: Run RED verification**

```powershell
python -m pytest tests\test_generate_research_portfolio.py tests\test_research_training_scheduler.py -q
```

Expected: failures because the CLI, handler and job kind are absent.

- [ ] **Step 3: Implement minimal CLI and handler**

The CLI loads:

```text
data/factor_snapshot_latest.json
data/factor_evaluation.json
data/research/f4/latest.json
data/research/f4/<validation_id>/candidate_spec.json
data/research/industry/pit_industry.json
```

It calls the pure builder and atomically writes:

```text
data/research/selections/<portfolio_id>/portfolio.json
data/research/selections/latest.json
```

`_selection_handler` invokes only this script, then validates `latest.json`. Add it to `DEFAULT_HANDLERS`. `_block_reason` must require the exact daily factor identity to be `succeeded` before the generator can run.

- [ ] **Step 4: Run GREEN verification**

```powershell
python -m pytest tests\test_generate_research_portfolio.py tests\test_research_training_scheduler.py tests\test_research_job_store.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Record checkpoint**

Record script name, ledger job kind, idempotency format and fresh test count.

### Task 4: Enforce the complete daily data → factor → selection chain

**Files:**
- Modify: `scripts/run_daily_research_pipeline.py`
- Modify: `tests/test_daily_research_pipeline.py`

- [ ] **Step 1: Write failing pipeline tests**

Add a `selection_artifact_reader` seam and assert selection is validated after factors:

```python
def test_daily_pipeline_requires_current_selection_artifact():
    result = run_daily_pipeline(
        now=datetime(2026, 8, 19, 17, 0),
        snapshot_reader=lambda: _snapshot("2026-08-19"),
        command_runner=lambda *_args, **_kwargs: {"success": True},
        factor_artifact_reader=lambda: _factor("2026-08-19"),
        selection_artifact_reader=lambda: {"selection_date": "20260818"},
    )
    assert result["success"] is False
    assert result["reason_code"] == "research_selection_gate_failed"
```

Add success and factor-failure tests proving the selection stage cannot be skipped or run early.

- [ ] **Step 2: Run RED verification**

```powershell
python -m pytest tests\test_daily_research_pipeline.py -q
```

Expected: failure because the reader and selection gate are absent.

- [ ] **Step 3: Implement the selection artifact gate**

After factor validation, require selection fields:

```text
selection_date == expected_date
generated_from_snapshot_id == snapshot.snapshot_id
snapshot_data_version == snapshot.content_hash
promotion_state == research_only
execution_authority == false
not_a_trade_signal == true
positions is a non-empty list
```

Return `portfolio_id`, `selection_status` and position count in the successful daily pipeline result.

- [ ] **Step 4: Run GREEN verification**

```powershell
python -m pytest tests\test_daily_research_pipeline.py tests\test_factor_runner_input_governance.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Record checkpoint**

Record stage order and gate evidence.

### Task 5: Make Windows schedules reproducible and ordered

**Files:**
- Create: `scripts/install_research_schedules.ps1`
- Modify: `scripts/install_qlib_schedule.ps1`
- Create: `scripts/research_schedule_contract_tests.mjs`

- [ ] **Step 1: Write a failing contract test**

The Node contract must assert that the installer declares:

```javascript
assert(src.includes('XuanJiQuant-Research-Daily'));
assert(src.includes('MON,TUE,WED,THU,FRI'));
assert(src.includes('16:20'));
assert(src.includes('XuanJiQuant-Strategy-Weekly'));
assert(src.includes('SUN'));
assert(src.includes('10:00'));
assert(src.includes('RestartCount'));
assert(src.includes('IgnoreNew'));
```

The Qlib installer contract must retain Saturday 18:30 and add a project working directory plus `IgnoreNew`.

- [ ] **Step 2: Run RED verification**

```powershell
node scripts\research_schedule_contract_tests.mjs
```

Expected: failure because the unified installer does not exist.

- [ ] **Step 3: Implement the PowerShell installer**

Use `New-ScheduledTaskAction`, `New-ScheduledTaskTrigger`, `New-ScheduledTaskSettingsSet` and `Register-ScheduledTask`. Preserve exact project-root actions, `StartWhenAvailable`, four-hour limits, daily 15-minute ×3 retries and strategy 30-minute ×2 retries. Do not touch unrelated tasks.

- [ ] **Step 4: Run GREEN verification and install tasks**

```powershell
node scripts\research_schedule_contract_tests.mjs
powershell -ExecutionPolicy Bypass -File scripts\install_research_schedules.ps1
```

Then inspect only the three named tasks with `Get-ScheduledTask` and `Get-ScheduledTaskInfo`.

- [ ] **Step 5: Record checkpoint**

Record task names, actions, working directories, triggers, retry settings and next run times.

### Task 6: Update handoff and visible state contracts

**Files:**
- Modify: `README.md`
- Modify: `docs/XUANJI_HANDOFF.md`
- Modify: `docs/XUANJI_SYSTEM_WORKFLOW_MAP.md`
- Modify: `scripts/research_boundary_contract_tests.mjs`

- [ ] **Step 1: Write failing documentation contracts**

Require all authoritative docs to name the daily 16:20 event chain, Saturday 18:30 Qlib task, Sunday 10:00 F4 task, daily research selection artifact, failure closure and research-only authority.

- [ ] **Step 2: Run RED verification**

```powershell
node scripts\research_boundary_contract_tests.mjs
```

Expected: failure because Sunday ordering and automatic daily selection are not documented.

- [ ] **Step 3: Update the three handoff documents**

Document module ownership, exact task commands, artifact paths, idempotency identities, retry policy, status wording and manual recovery commands. Label runtime timestamps as snapshots rather than permanent facts.

- [ ] **Step 4: Run GREEN verification**

```powershell
node scripts\research_boundary_contract_tests.mjs
node scripts\service_lifecycle_contract_tests.mjs
```

Expected: both contract suites pass.

- [ ] **Step 5: Record checkpoint**

Record the exact documentation lines and passing contract output.

### Task 7: End-to-end verification

**Files:**
- Verify only; no new production files unless a failing verification exposes a scoped defect.

- [ ] **Step 1: Run focused Python regression**

```powershell
python -m pytest tests\test_research_training_schedule.py tests\test_research_training_scheduler.py tests\test_research_job_store.py tests\test_research_selection.py tests\test_generate_research_portfolio.py tests\test_daily_research_pipeline.py tests\test_factor_runner_input_governance.py tests\test_f4_contracts.py tests\test_f4_portfolio.py -q
```

- [ ] **Step 2: Run Node and build verification**

```powershell
node scripts\research_schedule_contract_tests.mjs
node scripts\research_boundary_contract_tests.mjs
node scripts\service_lifecycle_contract_tests.mjs
npm run typecheck
npm run build
```

- [ ] **Step 3: Run the current-date daily chain once**

```powershell
python scripts\run_daily_research_pipeline.py --workers 8
```

Verify snapshot, factor and selection dates and hashes match. Do not run any trade or paper endpoint.

- [ ] **Step 4: Verify read-only APIs and tasks**

Call factor and strategy read APIs, inspect `data/research/selections/latest.json`, and inspect the three Scheduled Tasks. Confirm all research artifacts expose no execution authority.

- [ ] **Step 5: Run proportional full regression**

Run the repository Python suite, all Node contracts, TypeScript, Vite build, Web/UI verification and browser console inspection because scheduler and daily research ownership are cross-cutting.

- [ ] **Step 6: Produce final evidence report**

Report current timestamp, files changed, RED/GREEN evidence, test counts, artifact IDs, task schedules, performance, remaining blockers and the explicit no-trading boundary. Do not call the implementation complete if any current-version gate or scheduled-task contract is failing.
