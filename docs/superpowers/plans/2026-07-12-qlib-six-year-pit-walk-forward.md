# Qlib Six-Year PIT Walk-Forward Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a six-year all-A-share Qlib dataset with dual-track adjustment validation, point-in-time listing/ST/delisting masks, hard data-quality gates, and rolling walk-forward LightGBM evaluation.

**Architecture:** Keep all research data under `C:\Users\HYSHEN\XuanJiQuant\data\qlib` and preserve `data/quant.db` isolation. TdxQuant remains the market-data authority; AkShare supplies exchange-backed name-change and delisting records; Sina, Tencent, and Baostock are explicitly bounded validation/fallback sources. Training consumes only quality-approved point-in-time samples and can produce only `candidate` or `rejected`.

**Tech Stack:** Python 3.11, pyqlib 0.9.7, pandas, NumPy, LightGBM, AkShare, TdxQuant local HTTP API, SQLite Qlib registry, React 19, TypeScript, Vite.

---

## File Map

**Create**

- `quant/qlib/corporate_actions.py`: adjusted-price and factor reconciliation.
- `quant/qlib/point_in_time.py`: listing, delisting, name-change, ST interval and daily-mask construction.
- `quant/qlib/quality_gate.py`: deterministic dataset quality checks and reason codes.
- `quant/qlib/walk_forward.py`: rolling-window generation and metric aggregation.
- `tests/test_qlib_corporate_actions.py`
- `tests/test_qlib_point_in_time.py`
- `tests/test_qlib_quality_gate.py`
- `tests/test_qlib_walk_forward.py`

**Modify**

- `quant/qlib/sources.py`: source-specific metadata, adjusted bars and delisted-universe acquisition.
- `quant/qlib/collector.py`: dual-track atomic files and resumable checkpoints.
- `quant/qlib/normalizer.py`: adjustment and PIT status fields.
- `quant/qlib/exporter.py`: factor and tradability features.
- `scripts/qlib_job_worker.py`: new pipeline jobs and dependency enforcement.
- `scripts/qlib_train.py`: six-year walk-forward preset.
- `scripts/qlib_runner.py`: fixed control-action whitelist.
- `scripts/qlib_schedule.py`: monthly PIT refresh and quarterly retraining.
- `components/QlibResearchPanel.tsx`
- `components/qlib/QlibDataPanel.tsx`
- `components/qlib/QlibTrainingPanel.tsx`
- `components/qlib/QlibExperimentsPanel.tsx`
- `components/qlib/QlibBacktestPanel.tsx`
- `scripts/qlib_control_contract_tests.mjs`
- `scripts/qlib_chinese_ui_contract_tests.mjs`
- `README.md`
- `docs/QLIB_LOCAL_TRAINING.md`

---

### Task 1: Install and Isolate AkShare

**Files:**
- Modify: `scripts/setup_qlib_env.ps1`
- Modify: `tests/test_qlib_environment.py`

- [ ] **Step 1: Write the failing dependency test**

```python
def test_qlib_environment_declares_akshare():
    source = Path("scripts/setup_qlib_env.ps1").read_text(encoding="utf-8")
    assert "akshare==" in source.lower()
```

- [ ] **Step 2: Verify the test fails**

Run:

```powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_environment.py -q
```

Expected: failure because AkShare is not declared.

- [ ] **Step 3: Pin and install AkShare**

Add `akshare==1.18.60` to the isolated setup package list, then run:

```powershell
.\.venv-qlib\Scripts\python.exe -m pip install akshare==1.18.60
```

- [ ] **Step 4: Verify imports and isolation**

```powershell
.\.venv-qlib\Scripts\python.exe -c "import akshare; print(akshare.__version__)"
```

Expected: `1.18.60`.

---

### Task 2: Add Dual-Track Corporate-Action Data

**Files:**
- Create: `quant/qlib/corporate_actions.py`
- Create: `tests/test_qlib_corporate_actions.py`
- Modify: `quant/qlib/sources.py`

- [ ] **Step 1: Write failing reconciliation tests**

```python
def test_reconcile_factor_uses_positive_tdx_factor():
    rows = reconcile_adjustment_rows(
        raw=[{"datetime": "2026-01-02", "close": 10.0, "factor": 0.5}],
        front=[{"datetime": "2026-01-02", "close": 5.0}],
        baostock_factors=[],
    )
    assert rows[0]["factor"] == 0.5
    assert rows[0]["factor_source"] == "tdxquant"


def test_reconcile_factor_rejects_non_positive_values():
    report = validate_adjustment_rows(
        [{"datetime": "2026-01-02", "close": 10.0, "factor": 0.0}]
    )
    assert report["passed"] is False
    assert "non_positive_factor" in report["reason_codes"]


def test_front_price_deviation_over_one_percent_is_reported():
    report = compare_front_prices(
        raw_close=10.0,
        factor=0.5,
        observed_front_close=5.2,
        tolerance=0.01,
    )
    assert report["deviation"] == pytest.approx(0.04)
    assert report["passed"] is False
```

- [ ] **Step 2: Run tests and confirm missing implementation**

```powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_corporate_actions.py -q
```

Expected: import failure for `quant.qlib.corporate_actions`.

- [ ] **Step 3: Implement reconciliation**

Implement:

```python
FACTOR_PRIORITY = ("tdxquant", "baostock", "derived")

def compare_front_prices(raw_close, factor, observed_front_close, tolerance=0.01) -> dict:
    expected = float(raw_close) * float(factor)
    deviation = abs(float(observed_front_close) / expected - 1.0) if expected > 0 else float("inf")
    return {"expected": expected, "deviation": deviation, "passed": deviation <= tolerance}
```

`reconcile_adjustment_rows` must preserve raw prices, attach `factor`,
`factor_source`, `front_close_observed`, `front_close_expected`, and
`front_price_deviation`.

- [ ] **Step 4: Add adjusted TdxQuant source call**

Extend `fetch_daily_history` or add `fetch_daily_history_tracks` to request:

```python
fetch_klines_allow_price_jumps(..., dividend_type="none")
fetch_klines_allow_price_jumps(..., dividend_type="front")
```

Do not replace raw OHLC with front-adjusted OHLC.

- [ ] **Step 5: Verify corporate-action tests**

```powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_corporate_actions.py tests\test_qlib_sources.py -q
```

Expected: all pass.

---

### Task 3: Build Point-in-Time Security Status

**Files:**
- Create: `quant/qlib/point_in_time.py`
- Create: `tests/test_qlib_point_in_time.py`
- Modify: `quant/qlib/sources.py`

- [ ] **Step 1: Write failing interval tests**

```python
def test_name_changes_create_shenzhen_st_interval():
    changes = [
        {"date": "2021-01-05", "before": "测试股份", "after": "ST测试"},
        {"date": "2022-06-01", "before": "ST测试", "after": "测试股份"},
    ]
    assert build_st_intervals("SZ000001", changes) == [
        {"start_date": "2021-01-05", "end_date": "2022-05-31", "status": "st"}
    ]


def test_unknown_historical_st_is_not_normal():
    mask = build_daily_mask(
        "SH600000",
        "2021-01-05",
        listing_date="1999-11-10",
        delisting_date="",
        st_intervals=[],
        historical_st_uncertain=True,
        volume=100,
    )
    assert mask["st_status"] == "unknown"
    assert mask["tradable"] is False


def test_samples_after_delisting_are_not_tradable():
    mask = build_daily_mask(
        "SZ000005",
        "2024-04-29",
        listing_date="1990-12-10",
        delisting_date="2024-04-26",
        st_intervals=[],
        historical_st_uncertain=False,
        volume=100,
    )
    assert mask["delisted"] is True
    assert mask["tradable"] is False
```

- [ ] **Step 2: Verify tests fail**

```powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_point_in_time.py -q
```

- [ ] **Step 3: Implement AkShare metadata adapters**

Add functions returning normalized rows:

```python
fetch_akshare_current_universe()
fetch_sz_name_changes()
fetch_sh_delistings()
fetch_sz_delistings()
fetch_current_st_universe()
```

Use explicit Unicode column mappings and convert all dates to `YYYY-MM-DD`.
Network errors return a structured source-health record; they must not silently
return “normal” status.

- [ ] **Step 4: Implement interval and mask builders**

`build_daily_mask` must return:

```python
{
    "listed": bool,
    "delisted": bool,
    "is_st": bool,
    "st_status": "normal" | "st" | "unknown",
    "paused": bool,
    "limit_up": bool,
    "limit_down": bool,
    "tradable": bool,
    "status_sources": list[str],
}
```

- [ ] **Step 5: Verify PIT tests**

```powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_point_in_time.py tests\test_qlib_sources.py -q
```

---

### Task 4: Extend the Resumable Six-Year Collector

**Files:**
- Modify: `quant/qlib/collector.py`
- Modify: `scripts/qlib_job_worker.py`
- Modify: `tests/test_qlib_collector.py`
- Modify: `tests/test_qlib_job_worker.py`

- [ ] **Step 1: Write failing dual-track checkpoint tests**

```python
def test_collector_writes_raw_adjusted_and_pit_files(tmp_path):
    result = collect_six_year_symbol(
        "SH600000",
        "2020-07-01",
        "2026-07-12",
        tmp_path,
        track_fetcher=fake_tracks,
        metadata=fake_metadata,
    )
    assert (tmp_path / "raw" / "SH600000.json").exists()
    assert (tmp_path / "adjusted" / "SH600000.json").exists()
    assert (tmp_path / "point_in_time" / "daily_masks" / "SH600000.json").exists()
    assert result["status"] == "complete"


def test_resume_requires_all_symbol_artifacts(tmp_path):
    # A raw file without adjusted/PIT files is not considered completed.
    assert symbol_artifacts_complete(tmp_path, "SH600000") is False
```

- [ ] **Step 2: Verify tests fail**

```powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_collector.py tests\test_qlib_job_worker.py -q
```

- [ ] **Step 3: Implement atomic per-track storage**

Write each symbol to temporary files and rename only after raw, adjusted and PIT
payloads validate. Manifest entries must include:

```python
{
    "symbol": "SH600000",
    "raw_rows": 1450,
    "adjusted_rows": 1450,
    "mask_rows": 1450,
    "sources": ["tdxquant"],
    "factor_anomalies": 0,
    "completed_at": "...",
}
```

- [ ] **Step 4: Include historical delisted symbols**

Build collection instruments as:

```python
current_universe | sh_delisted_within_window | sz_delisted_within_window
```

Do not remove a symbol only because it is absent from the current TdxQuant list.

- [ ] **Step 5: Verify collector tests**

```powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_collector.py tests\test_qlib_job_worker.py -q
```

---

### Task 5: Add the Dataset Quality Gate

**Files:**
- Create: `quant/qlib/quality_gate.py`
- Create: `tests/test_qlib_quality_gate.py`
- Modify: `scripts/qlib_job_worker.py`

- [ ] **Step 1: Write failing reason-code tests**

```python
def test_quality_gate_rejects_low_coverage():
    result = check_dataset_quality(
        requested=100,
        completed=97,
        recent_coverage=1.0,
        trading_days=1400,
        latest_date_matches=True,
        duplicate_rows=0,
        invalid_ohlc=0,
        non_positive_factors=0,
        unknown_st_samples=0,
        invalid_lifecycle_samples=0,
    )
    assert result["passed"] is False
    assert "coverage_below_98pct" in result["reason_codes"]


def test_quality_gate_accepts_all_thresholds():
    result = check_dataset_quality(
        requested=100,
        completed=99,
        recent_coverage=0.995,
        trading_days=1400,
        latest_date_matches=True,
        duplicate_rows=0,
        invalid_ohlc=0,
        non_positive_factors=0,
        unknown_st_samples=0,
        invalid_lifecycle_samples=0,
    )
    assert result["passed"] is True
```

- [ ] **Step 2: Verify tests fail**

```powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_quality_gate.py -q
```

- [ ] **Step 3: Implement deterministic checks**

Reason codes must include:

```text
coverage_below_98pct
recent_coverage_below_99pct
trading_days_below_1200
latest_date_mismatch
duplicate_rows
invalid_ohlc
non_positive_factor
unknown_st_in_training
invalid_lifecycle_sample
```

- [ ] **Step 4: Persist the report and block downstream jobs**

Write:

```text
datasets/a_share_6y_daily/quality_report.json
```

`export_six_years` and `train_walk_forward` must raise
`dataset quality gate failed: <reason codes>` unless `passed=true`.

- [ ] **Step 5: Verify quality-gate tests**

```powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_quality_gate.py tests\test_qlib_job_worker.py -q
```

---

### Task 6: Export PIT Features to Qlib

**Files:**
- Modify: `quant/qlib/normalizer.py`
- Modify: `quant/qlib/exporter.py`
- Modify: `tests/test_qlib_normalizer.py`
- Modify: `tests/test_qlib_exporter.py`

- [ ] **Step 1: Write failing export tests**

```python
def test_exporter_writes_factor_and_tradable_features(tmp_path):
    result = write_qlib_bin(sample_pit_frame(), tmp_path)
    feature_dir = tmp_path / "features" / "sh600000"
    assert (feature_dir / "factor.day.bin").exists()
    assert (feature_dir / "tradable.day.bin").exists()
    assert (feature_dir / "is_st.day.bin").exists()
    assert (feature_dir / "listed.day.bin").exists()
```

- [ ] **Step 2: Verify tests fail**

```powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_normalizer.py tests\test_qlib_exporter.py -q
```

- [ ] **Step 3: Add feature fields**

Extend `BASE_FIELDS` with:

```python
"tradable", "is_st", "st_unknown", "listed", "delisted", "paused",
"limit_up", "limit_down"
```

Only quality-approved rows enter the exported Qlib bin.

- [ ] **Step 4: Verify exporter tests**

```powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_normalizer.py tests\test_qlib_exporter.py -q
```

---

### Task 7: Implement Walk-Forward Training

**Files:**
- Create: `quant/qlib/walk_forward.py`
- Create: `tests/test_qlib_walk_forward.py`
- Modify: `scripts/qlib_train.py`
- Modify: `tests/test_qlib_train_entry.py`

- [ ] **Step 1: Write failing window tests**

```python
def test_walk_forward_windows_are_ordered_and_non_overlapping():
    calendar = pd.date_range("2020-01-01", "2026-07-01", freq="B")
    windows = build_walk_forward_windows(
        calendar,
        train_months=36,
        valid_months=6,
        test_months=6,
        step_months=3,
    )
    assert len(windows) >= 4
    for window in windows:
        assert window["train"][1] < window["valid"][0]
        assert window["valid"][1] < window["test"][0]


def test_walk_forward_candidate_requires_all_hard_metrics():
    status = aggregate_promotion_status(
        windows=[passing_window()] * 7 + [failing_but_allowed_window()] * 3,
        quality_passed=True,
    )
    assert status == "candidate"


def test_walk_forward_is_rejected_on_quality_failure():
    assert aggregate_promotion_status([passing_window()] * 8, False) == "rejected"
```

- [ ] **Step 2: Verify tests fail**

```powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_walk_forward.py -q
```

- [ ] **Step 3: Implement fixed rolling windows**

Use:

```python
train_months=36
valid_months=6
test_months=6
step_months=3
```

Each window gets a unique ID and isolated artifact directory.

- [ ] **Step 4: Implement aggregate promotion**

Require:

```python
minimum_windows = 4
median_rank_ic >= 0.02
median_icir >= 0.30
positive_rank_ic_ratio >= 0.70
aggregate_after_cost_long_short > 0
aggregate_sharpe >= 0.80
max_drawdown >= -0.20
worst_rank_ic >= -0.03
quality_passed is True
```

- [ ] **Step 5: Add `six-year-walk-forward` preset**

`run_preset` must support:

```text
six-year-walk-forward
```

Save `window_metrics.json`, `aggregate_metrics.json`, predictions and model
checksums. No window may fit processors outside its training dates.

- [ ] **Step 6: Verify walk-forward tests**

```powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_walk_forward.py tests\test_qlib_train_entry.py -q
```

---

### Task 8: Wire Jobs, API and Scheduling

**Files:**
- Modify: `scripts/qlib_job_worker.py`
- Modify: `scripts/qlib_runner.py`
- Modify: `scripts/qlib_schedule.py`
- Modify: `tests/test_qlib_job_worker.py`
- Modify: `tests/test_qlib_runner_actions.py`
- Modify: `scripts/qlib_control_contract_tests.mjs`
- Modify: `scripts/qlib_schedule_contract_tests.mjs`

- [ ] **Step 1: Write failing action and dependency tests**

Expected control actions:

```text
build_point_in_time
quality_six_years
export_six_years
train_walk_forward
```

Add a test proving `train_walk_forward` refuses to start without a passed
quality report.

- [ ] **Step 2: Verify tests fail**

```powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_job_worker.py tests\test_qlib_runner_actions.py -q
node scripts\qlib_control_contract_tests.mjs
```

- [ ] **Step 3: Implement fixed job dispatch**

No action accepts shell commands, arbitrary paths, Python expressions or custom
module names. Dataset ID remains whitelist validated.

- [ ] **Step 4: Update schedules**

Keep Saturday one-year updates. Add:

```text
monthly_pit_refresh: first Saturday of month after 18:30
quarterly_walk_forward: first Saturday of Jan/Apr/Jul/Oct after PIT quality pass
```

Both retain the intraday safety gate.

- [ ] **Step 5: Verify API and schedule contracts**

```powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_job_worker.py tests\test_qlib_runner_actions.py -q
node scripts\qlib_control_contract_tests.mjs
node scripts\qlib_schedule_contract_tests.mjs
```

---

### Task 9: Add Chinese UI for PIT and Walk-Forward

**Files:**
- Modify: `components/QlibResearchPanel.tsx`
- Modify: `components/qlib/QlibDataPanel.tsx`
- Modify: `components/qlib/QlibTrainingPanel.tsx`
- Modify: `components/qlib/QlibExperimentsPanel.tsx`
- Modify: `components/qlib/QlibBacktestPanel.tsx`
- Modify: `scripts/qlib_chinese_ui_contract_tests.mjs`

- [ ] **Step 1: Write failing UI contract assertions**

Require these labels:

```text
六年原始行情
点时状态覆盖率
复权校验异常
历史退市股票
ST 未知区间
数据质量门禁
Walk-Forward 六年基线
窗口通过率
最差窗口
```

- [ ] **Step 2: Verify the UI contract fails**

```powershell
node scripts\qlib_chinese_ui_contract_tests.mjs
```

- [ ] **Step 3: Implement the controls and metrics**

Buttons call only the fixed API actions. Disable export/training buttons when
the quality report is absent or failed. Experiments and backtests display
window-level metrics before aggregate metrics.

- [ ] **Step 4: Verify UI and build**

```powershell
node scripts\qlib_chinese_ui_contract_tests.mjs
npm run build
```

---

### Task 10: Run Small-Pool Integration Before Full Collection

**Files:**
- Modify only if test evidence reveals a defect.

- [ ] **Step 1: Run a mixed lifecycle sample**

Use:

```text
600000 current Shanghai
000001 current Shenzhen
000005 recently delisted Shenzhen
600087 delisted Shanghai
300750 current ChiNext
```

Collect six-year data into a temporary dataset, not `a_share_6y_daily`.

- [ ] **Step 2: Verify quality artifacts**

Check:

```text
raw and adjusted row counts
factor positivity
listing/delisting masks
ST unknown handling
source health
no quant.db access
```

- [ ] **Step 3: Run a reduced walk-forward**

Use the same production window generator but allow the sample test fixture to
shorten history. Confirm model artifacts reload and produce only
`candidate` or `rejected`.

- [ ] **Step 4: Run focused regression tests**

```powershell
$files = Get-ChildItem tests -Filter 'test_qlib_*.py' | ForEach-Object FullName
.\.venv-qlib\Scripts\python.exe -m pytest @files -q
.\.venv-qlib\Scripts\python.exe -m pytest scripts\tdx_quant_source_contract_tests.py scripts\data_source_chain_contract_tests.py -q
```

---

### Task 11: Start the Full Resumable Six-Year Job

**Files:**
- Runtime data only under `C:\Users\HYSHEN\XuanJiQuant\data\qlib`.

- [ ] **Step 1: Submit the collection**

```powershell
'{"action":"collect_six_years"}' |
  .\.venv-qlib\Scripts\python.exe scripts\qlib_runner.py
```

- [ ] **Step 2: Confirm the detached worker**

Verify registry status is `running`, PID exists, progress advances, and the
manifest updates every 25 symbols.

- [ ] **Step 3: Do not train early**

Do not start export or walk-forward training until collection, PIT build and
quality gate complete. If collection extends beyond the current session, leave
the worker running and report the exact job ID and progress.

---

### Task 12: Documentation and Final Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/QLIB_LOCAL_TRAINING.md`

- [ ] **Step 1: Update operational documentation**

Document data paths, source responsibilities, task actions, quality reason
codes, walk-forward windows, model boundaries, schedule and recovery commands.

- [ ] **Step 2: Run fresh verification**

```powershell
$files = Get-ChildItem tests -Filter 'test_qlib_*.py' | ForEach-Object FullName
.\.venv-qlib\Scripts\python.exe -m pytest @files -q
node scripts\qlib_panel_contract_tests.mjs
node scripts\qlib_control_contract_tests.mjs
node scripts\qlib_chinese_ui_contract_tests.mjs
node scripts\qlib_schedule_contract_tests.mjs
npm run build
node scripts\web_verify.mjs
```

- [ ] **Step 3: Verify through the in-app browser**

Check Qlib overview, data, training, experiment, model, backtest and task-log
pages. Confirm no white screen, no overlapping controls, correct Chinese
labels, correct quality state and preserved safety boundary.

- [ ] **Step 4: Record the actual state**

README must distinguish:

```text
implemented
verified on small pool
full collection running
full collection complete
quality passed/failed
walk-forward trained/not trained
```

Do not describe a running or failed job as complete.

---

## Execution Notes

- The current workspace is not recognized as a valid Git repository, so commit
  steps are intentionally omitted. Preserve unrelated user files and changes.
- Use `apply_patch` for manual code edits.
- Do not start GPU training in this plan.
- Do not alter verifier, risk gateway, paper-trading limits or live-trading
  configuration.
