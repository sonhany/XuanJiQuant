# Qlib Local Training Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an isolated Qlib research environment, independent A-share data warehouse, reproducible LightGBM five-day excess-return baseline, Chinese research console, and resumable weekly retraining workflow.

**Architecture:** Python 3.11 creates `.venv-qlib`; all Qlib data and model artifacts live under `C:\Users\HYSHEN\XuanJiQuant\data\qlib`, outside the trading SQLite database. The existing Node API submits whitelisted jobs to a lightweight controller, while heavy collection, conversion, training, and evaluation execute in isolated child processes.

**Tech Stack:** Python 3.11, pyqlib, pandas, pyarrow, LightGBM, scikit-learn, SQLite, Parquet, Node.js, React 19, TypeScript, Vite, Playwright.

---

## File Map

- Create `requirements-qlib.txt`: pinned isolated research dependencies.
- Create `scripts/setup_qlib_env.ps1`: idempotent environment bootstrap.
- Create `quant/qlib/paths.py`: fixed and validated external paths.
- Create `quant/qlib/registry.py`: independent metadata schema and model registry.
- Create `quant/qlib/jobs.py`: job lifecycle, locking, cancellation, recovery.
- Create `quant/qlib/sources.py`: source adapters without `quant.data.cache`.
- Create `quant/qlib/collector.py`: resumable one-year/six-year collection.
- Create `quant/qlib/normalizer.py`: canonical bars and quality gates.
- Create `quant/qlib/exporter.py`: CSV/Parquet to Qlib bin preparation.
- Create `quant/qlib/dataset.py`: eligibility, labels, chronological splits.
- Create `quant/qlib/features.py`: Alpha158 plus native factor namespace.
- Create `quant/qlib/trainer.py`: LightGBM fitting and atomic artifacts.
- Create `quant/qlib/evaluator.py`: Rank IC and realistic portfolio metrics.
- Create `scripts/qlib_job_worker.py`: isolated job process.
- Create `scripts/qlib_train.py`: command-line training entry.
- Create `scripts/qlib_schedule.py`: Saturday retraining entry.
- Modify `scripts/qlib_runner.py`: Chinese status and controller actions.
- Modify `server/routes/qlib.mjs`: long-running API timeouts.
- Modify `server/router.mjs`: Qlib read/control action authorization.
- Replace `components/QlibResearchPanel.tsx`: Chinese operational console.
- Modify `README.md`: installation, paths, commands, safety boundary.
- Add tests under `tests/test_qlib_*.py` and Node contract tests under `scripts/`.

## Task 1: Isolated Python Environment

**Files:**
- Create: `requirements-qlib.txt`
- Create: `scripts/setup_qlib_env.ps1`
- Test: `tests/test_qlib_environment.py`

- [ ] **Step 1: Write the failing environment contract test**

```python
from pathlib import Path
from quant.qlib.environment import inspect_environment

def test_environment_uses_isolated_python(tmp_path):
    result = inspect_environment(tmp_path / ".venv-qlib", tmp_path / "warehouse")
    assert result["system_python_required"] == "3.11"
    assert result["inherits_system_site_packages"] is False
    assert result["data_root"] == str((tmp_path / "warehouse").resolve())
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m pytest tests/test_qlib_environment.py -q`

Expected: FAIL because `quant.qlib.environment` does not exist.

- [ ] **Step 3: Add environment inspection and bootstrap**

The bootstrap must invoke:

```powershell
& 'C:\Users\HYSHEN\AppData\Local\Programs\Python\Python311\python.exe' -m venv '.venv-qlib'
& '.\.venv-qlib\Scripts\python.exe' -m pip install --upgrade pip setuptools wheel
& '.\.venv-qlib\Scripts\python.exe' -m pip install -r requirements-qlib.txt
```

It must refuse Python versions other than 3.11 and must not use
`--system-site-packages`.

- [ ] **Step 4: Run environment tests**

Run: `python -m pytest tests/test_qlib_environment.py -q`

Expected: PASS.

- [ ] **Step 5: Install and verify**

Run: `powershell -ExecutionPolicy Bypass -File scripts\setup_qlib_env.ps1`

Run:

```powershell
.\.venv-qlib\Scripts\python.exe -c "import qlib, lightgbm, pandas, pyarrow; print(qlib.__version__)"
```

Expected: imports succeed in `.venv-qlib`.

## Task 2: External Warehouse and Metadata Registry

**Files:**
- Create: `quant/qlib/__init__.py`
- Create: `quant/qlib/paths.py`
- Create: `quant/qlib/registry.py`
- Create: `quant/qlib/jobs.py`
- Test: `tests/test_qlib_registry.py`
- Test: `tests/test_qlib_jobs.py`

- [ ] **Step 1: Write failing path and schema tests**

```python
def test_default_root_is_external_to_repo(monkeypatch):
    monkeypatch.delenv("QLIB_DATA_ROOT", raising=False)
    from quant.qlib.paths import data_root
    assert str(data_root()) == r"C:\Users\HYSHEN\XuanJiQuant\data\qlib"

def test_registry_creates_required_tables(tmp_path):
    from quant.qlib.registry import Registry
    registry = Registry(tmp_path / "qlib_meta.db")
    assert {"datasets", "jobs", "experiments", "models", "audit_events"} <= set(registry.table_names())
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_qlib_registry.py tests/test_qlib_jobs.py -q`

Expected: FAIL because registry and jobs modules are missing.

- [ ] **Step 3: Implement fixed paths and SQLite schema**

`paths.py` must resolve only descendants of `QLIB_DATA_ROOT`; `registry.py` must
create WAL-mode tables with timestamps, status constraints, JSON metadata, and
model SHA-256 fields.

- [ ] **Step 4: Implement job lifecycle**

Allowed transitions:

```text
queued -> running -> succeeded
queued -> cancelled
running -> cancelling -> cancelled
running -> failed
running -> interrupted
```

Only one job with status `queued`, `running`, or `cancelling` may hold the
heavy-job lock.

- [ ] **Step 5: Verify GREEN**

Run: `python -m pytest tests/test_qlib_registry.py tests/test_qlib_jobs.py -q`

Expected: PASS.

## Task 3: Independent Collection and Normalization

**Files:**
- Create: `quant/qlib/sources.py`
- Create: `quant/qlib/collector.py`
- Create: `quant/qlib/normalizer.py`
- Test: `tests/test_qlib_sources.py`
- Test: `tests/test_qlib_normalizer.py`
- Test: `tests/test_qlib_collector.py`

- [ ] **Step 1: Write failing isolation and normalization tests**

```python
def test_qlib_sources_do_not_import_trading_cache():
    source = Path("quant/qlib/sources.py").read_text(encoding="utf-8")
    assert "create_cache" not in source
    assert "quant.data.cache" not in source

def test_normalizer_rejects_duplicate_symbol_date():
    from quant.qlib.normalizer import normalize_daily_bars, DataQualityError
    rows = [
        {"instrument": "SH600000", "datetime": "2026-01-02", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1, "amount": 10},
        {"instrument": "SH600000", "datetime": "2026-01-02", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1, "amount": 10},
    ]
    with pytest.raises(DataQualityError):
        normalize_daily_bars(rows)
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_qlib_sources.py tests/test_qlib_normalizer.py tests/test_qlib_collector.py -q`

Expected: FAIL because collection modules are missing.

- [ ] **Step 3: Implement source chain**

Use TdxQuant as primary raw daily source, Baostock as historical cross-check,
and Tencent as latest-day fallback. Each result must include:

```python
{
    "instrument": "SH600000",
    "datetime": "2026-01-02",
    "open": 0.0,
    "high": 0.0,
    "low": 0.0,
    "close": 0.0,
    "volume": 0.0,
    "amount": 0.0,
    "factor": 1.0,
    "source": "tdxquant",
    "fetched_at": "ISO-8601",
}
```

- [ ] **Step 4: Implement resumable manifests**

Each dataset collection writes `manifest.json` with requested date range,
completed symbols, failed symbols, source counts, checksum, and status. A rerun
must skip completed symbols unless `--refresh` is set.

- [ ] **Step 5: Verify GREEN**

Run: `python -m pytest tests/test_qlib_sources.py tests/test_qlib_normalizer.py tests/test_qlib_collector.py -q`

Expected: PASS.

## Task 4: Qlib Dataset and Label Construction

**Files:**
- Create: `quant/qlib/exporter.py`
- Create: `quant/qlib/dataset.py`
- Create: `quant/qlib/features.py`
- Test: `tests/test_qlib_dataset.py`
- Test: `tests/test_qlib_exporter.py`

- [ ] **Step 1: Write failing no-lookahead tests**

```python
def test_five_day_excess_label_uses_future_only():
    from quant.qlib.dataset import build_excess_label
    close = pd.Series([10, 11, 12, 13, 14, 15], index=pd.date_range("2026-01-01", periods=6))
    benchmark = pd.Series([100, 101, 102, 103, 104, 105], index=close.index)
    label = build_excess_label(close, benchmark, horizon=5)
    expected = (15 / 10 - 1) - (105 / 100 - 1)
    assert label.iloc[0] == pytest.approx(expected)
    assert label.iloc[1:].isna().all()
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_qlib_dataset.py tests/test_qlib_exporter.py -q`

Expected: FAIL because dataset/exporter modules are missing.

- [ ] **Step 3: Implement chronological split and eligibility**

Exclude `920xxx`, ST/delisting names, fewer than 120 trading days, fewer than 18
valid days in the latest 20, invalid prices, and missing feature/label windows.
Return exclusion reason codes.

- [ ] **Step 4: Implement Qlib conversion**

Generate calendar, instruments, canonical CSV/Parquet, then call Qlib
`dump_bin.py` through `.venv-qlib`. Do not invoke shell text; use an argument
array and fixed paths.

- [ ] **Step 5: Verify GREEN**

Run: `python -m pytest tests/test_qlib_dataset.py tests/test_qlib_exporter.py -q`

Expected: PASS.

## Task 5: LightGBM Training, Evaluation, and Atomic Artifacts

**Files:**
- Create: `quant/qlib/trainer.py`
- Create: `quant/qlib/evaluator.py`
- Test: `tests/test_qlib_trainer.py`
- Test: `tests/test_qlib_evaluator.py`

- [ ] **Step 1: Write failing reproducibility and promotion tests**

```python
def test_model_round_trip_is_reproducible(tmp_path, tiny_dataset):
    from quant.qlib.trainer import train_lightgbm, load_model
    result = train_lightgbm(tiny_dataset, output_dir=tmp_path, seed=42)
    restored = load_model(result["model_path"])
    assert np.allclose(result["test_predictions"], restored.predict(tiny_dataset["test_x"]))
    assert len(result["sha256"]) == 64

def test_failed_metrics_are_rejected():
    from quant.qlib.evaluator import promotion_status
    assert promotion_status({"rank_ic": 0.01, "icir": 0.5, "sharpe": 1.0, "max_drawdown": -0.1, "after_cost_long_short": 0.1}) == "rejected"
```

- [ ] **Step 2: Verify RED**

Run: `python -m pytest tests/test_qlib_trainer.py tests/test_qlib_evaluator.py -q`

Expected: FAIL because trainer/evaluator modules are missing.

- [ ] **Step 3: Implement LightGBM baseline**

Use fixed safe defaults:

```python
{
    "objective": "regression",
    "learning_rate": 0.03,
    "n_estimators": 500,
    "num_leaves": 31,
    "max_depth": -1,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "random_state": 42,
    "n_jobs": -1,
}
```

Save into a temporary experiment directory and atomically rename only after
model reload and prediction checks pass.

- [ ] **Step 4: Implement metrics and status**

Candidate thresholds are Rank IC `>= 0.02`, ICIR `>= 0.30`, after-cost
long-short return `> 0`, Sharpe `>= 0.80`, maximum drawdown no worse than
`-0.20`, and no material sign reversal across segments.

- [ ] **Step 5: Verify GREEN**

Run: `python -m pytest tests/test_qlib_trainer.py tests/test_qlib_evaluator.py -q`

Expected: PASS.

## Task 6: Worker, API, and Authorization

**Files:**
- Create: `scripts/qlib_job_worker.py`
- Create: `scripts/qlib_train.py`
- Create: `scripts/qlib_schedule.py`
- Modify: `scripts/qlib_runner.py`
- Modify: `server/routes/qlib.mjs`
- Modify: `server/router.mjs`
- Test: `tests/test_qlib_runner_actions.py`
- Test: `scripts/qlib_control_contract_tests.mjs`

- [ ] **Step 1: Write failing action contracts**

Read-only actions:

```text
status, catalog, datasets, jobs, experiments, models, reports, job_log
```

Control actions:

```text
setup, collect_one_year, collect_six_years, export, train_smoke,
train_one_year, cancel_job, promote_shadow
```

Tests must assert control actions are absent from `READ_ONLY_ACTIONS`.

- [ ] **Step 2: Verify RED**

Run:

```powershell
python -m pytest tests/test_qlib_runner_actions.py -q
node scripts/qlib_control_contract_tests.mjs
```

Expected: FAIL because actions are not implemented.

- [ ] **Step 3: Implement controller actions**

The API may submit only named presets. It must never accept command strings,
Python expressions, arbitrary file paths, or dependency package names.

- [ ] **Step 4: Implement detached jobs**

Use `.venv-qlib\Scripts\python.exe` with `Start-Process -WindowStyle Hidden` or
Node `spawn` with `detached: true`, `windowsHide: true`, and persisted PID/job
metadata. API calls return immediately with a job ID.

- [ ] **Step 5: Verify GREEN**

Run the same Python and Node tests; expected PASS.

## Task 7: Chinese Qlib Research Console

**Files:**
- Replace: `components/QlibResearchPanel.tsx`
- Create: `components/qlib/QlibOverview.tsx`
- Create: `components/qlib/QlibDataPanel.tsx`
- Create: `components/qlib/QlibTrainingPanel.tsx`
- Create: `components/qlib/QlibExperimentsPanel.tsx`
- Create: `components/qlib/QlibModelsPanel.tsx`
- Create: `components/qlib/QlibBacktestPanel.tsx`
- Create: `components/qlib/QlibLogsPanel.tsx`
- Create: `scripts/qlib_chinese_ui_contract_tests.mjs`

- [ ] **Step 1: Write failing Chinese UI contract**

Assert the component includes:

```text
研究总览, 数据准备, 模型训练, 实验记录, 模型仓库, 回测评估, 任务日志
```

Also assert no Unicode replacement characters or existing mojibake fragments
remain in Qlib components.

- [ ] **Step 2: Verify RED**

Run: `node scripts/qlib_chinese_ui_contract_tests.mjs`

Expected: FAIL against the current corrupted Qlib page.

- [ ] **Step 3: Implement the tabbed console**

Fetch independent status requests in parallel, poll an active job every two
seconds, stop polling when no active job exists, and render fixed-height status
areas so progress changes do not shift the layout.

- [ ] **Step 4: Implement safe controls**

Buttons submit only fixed actions. Disabled and error states must be visible.
The page must state that models are offline research outputs and cannot bypass
paper trading or risk controls.

- [ ] **Step 5: Verify GREEN and build**

Run:

```powershell
node scripts/qlib_chinese_ui_contract_tests.mjs
npm run build
```

Expected: both succeed.

## Task 8: Installation Smoke and First Model

**Files:**
- Project data: `C:\Users\HYSHEN\XuanJiQuant\data\qlib\raw\qlib_demo`
- Project data: `C:\Users\HYSHEN\XuanJiQuant\data\qlib\models`
- Project data: `C:\Users\HYSHEN\XuanJiQuant\data\qlib\reports`

- [ ] **Step 1: Download official Qlib demo data**

Run the official Qlib data command through `.venv-qlib` into
`C:\Users\HYSHEN\XuanJiQuant\data\qlib\raw\qlib_demo`.

- [ ] **Step 2: Run Alpha158 and LightGBM smoke training**

Run: `.\.venv-qlib\Scripts\python.exe scripts\qlib_train.py --preset official-demo`

Expected: experiment status `succeeded`, model reload succeeds, and report is
marked `official_demo_smoke`.

- [ ] **Step 3: Verify model artifacts**

Check model file, SHA-256, config, feature list, predictions, metrics, and
report all share the same experiment ID.

- [ ] **Step 4: Start independent one-year collection**

Run: `.\.venv-qlib\Scripts\python.exe scripts\qlib_job_worker.py collect_one_year`

Expected: resumable manifest appears under `C:\Users\HYSHEN\XuanJiQuant\data\qlib\jobs`.

- [ ] **Step 5: Train the one-year baseline when quality gates pass**

Run: `.\.venv-qlib\Scripts\python.exe scripts\qlib_train.py --preset one-year`

Expected: a model is stored as `candidate` or `rejected` based solely on
metrics; the code does not force candidate status.

## Task 9: Scheduler, Documentation, and Regression Tests

**Files:**
- Modify: `README.md`
- Create: `scripts/qlib_schedule_contract_tests.mjs`
- Modify: scheduler configuration using the existing project scheduler pattern.

- [ ] **Step 1: Add a failing schedule contract**

Assert weekly retraining is Saturday-only, refuses intraday heavy execution,
and preserves the previous model on failure.

- [ ] **Step 2: Verify RED**

Run: `node scripts/qlib_schedule_contract_tests.mjs`

Expected: FAIL until schedule wiring exists.

- [ ] **Step 3: Wire weekly retraining**

The schedule sequence is:

```text
incremental collect -> quality gate -> export -> train -> evaluate -> register
```

It must not promote beyond `candidate`.

- [ ] **Step 4: Update README**

Document environment path, warehouse path, commands, Chinese page, model
boundaries, recovery procedures, and actual completed/pending status.

- [ ] **Step 5: Verify GREEN**

Run the schedule contract and README link checks; expected PASS.

## Task 10: Full Verification and Browser QA

**Files:**
- No committed temporary artifacts.

- [ ] **Step 1: Run focused Qlib tests**

Run:

```powershell
python -m pytest tests\test_qlib_*.py -q
node scripts\qlib_panel_contract_tests.mjs
node scripts\qlib_control_contract_tests.mjs
node scripts\qlib_chinese_ui_contract_tests.mjs
node scripts\qlib_schedule_contract_tests.mjs
```

- [ ] **Step 2: Run project regression**

Run the existing core Python suite, Node contracts, `npm run build`, seven-layer
smoke, paper rules, and security checks.

- [ ] **Step 3: Start services**

Start backend on `127.0.0.1:8880` and frontend on `127.0.0.1:8888`, using hidden
background windows.

- [ ] **Step 4: Browser plugin QA**

Flow:

```text
app login -> Qlib研究 -> 数据准备 -> 模型训练 -> 实验记录 -> 模型仓库
```

Verify page identity, nonblank content, no framework overlay, no relevant
console warnings/errors, Chinese text, active-job polling, and at least one
real interaction with observable state change.

- [ ] **Step 5: Resource and isolation verification**

Confirm Qlib processes use `.venv-qlib`, artifacts are under
`C:\Users\HYSHEN\XuanJiQuant\data\qlib`, no Qlib records are written to `quant.db`, and
online trading services remain responsive during an offline job.

- [ ] **Step 6: Record actual status**

Update README with installed versions, completed smoke experiment ID, model
status, one-year/six-year collection progress, and any remaining limitations.

## Execution Note

This workspace is not a Git repository. Replace each normal commit checkpoint
with a test checkpoint and a concise changed-file review. Do not initialize a
new Git repository as part of this work.
