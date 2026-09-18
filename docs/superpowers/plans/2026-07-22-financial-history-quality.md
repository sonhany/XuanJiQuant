# Financial History Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Batch-fill standard profit and cash-flow fields for historical reports and expose explicit completeness and freshness status in the financial API and workbench.

**Architecture:** Put reusable quality calculations in `quant/data/financial_quality.py`. Extend the existing repair script with a resumable period-batched history mode that merges only non-empty source values. The read-only API returns computed quality metadata, and the existing financial page renders it as a compact status line.

**Tech Stack:** Python 3, SQLite cache, AkShare, pytest, React, TypeScript, Vite.

---

### Task 1: Financial quality model

**Files:**
- Create: `quant/data/financial_quality.py`
- Create: `tests/test_financial_quality.py`

- [ ] **Step 1: Write failing tests**

Test that:

```python
analyze_financial_history(
    [
        {"report_date": "20251231", "revenue": 1, "net_profit": 1, "operating_cash_flow": 1},
        {"report_date": "20260331", "revenue": 1, "net_profit": None, "operating_cash_flow": 1},
    ],
    as_of_date="20260722",
)
```

returns `latest_complete=False`, `complete_periods=1`, `total_periods=2`,
`completeness_ratio=0.5`, `expected_period="20260331"` and
`freshness_status="current"`. Also test that `20250930` is stale on
`20260722`, and that an empty history is `unknown`.

- [ ] **Step 2: Verify tests fail**

Run:

```powershell
python -m pytest tests/test_financial_quality.py -q
```

Expected: import failure because `quant.data.financial_quality` does not exist.

- [ ] **Step 3: Implement quality calculations**

Implement:

```python
REQUIRED_FINANCIAL_FIELDS = ("revenue", "net_profit", "operating_cash_flow")
expected_financial_period(as_of_date)
analyze_financial_history(records, as_of_date=None)
```

Use A-share filing windows: January-April expects prior Q3, May-August
expects current Q1, September-October expects current Q2, and
November-December expects current Q3.

- [ ] **Step 4: Verify tests pass**

Run the same pytest command and expect all tests to pass.

### Task 2: Historical period batch repair

**Files:**
- Modify: `scripts/repair_financial_abstracts.py`
- Modify: `tests/test_repair_financial_abstracts.py`

- [ ] **Step 1: Write failing repair tests**

Add tests proving that a period batch:

```python
backfill_historical_periods(
    ["300450", "300451"],
    cache,
    start_period="20250101",
    income_fetcher=fake_income,
    cashflow_fetcher=fake_cashflow,
)
```

fetches each missing report period once, merges `营业总收入`, `净利润` and
`经营性现金流-现金流量净额`, preserves existing ratios, and does not replace
records when a source is empty.

- [ ] **Step 2: Verify tests fail**

Run:

```powershell
python -m pytest tests/test_repair_financial_abstracts.py -q
```

Expected: attribute failure for `backfill_historical_periods`.

- [ ] **Step 3: Implement period batching**

Add `backfill_historical_periods` plus CLI flags:

```text
--history-only
--history-years 10
--history-start YYYYMMDD
--as-of YYYYMMDD
```

Group missing rows by report period, fetch the income and cash-flow tables once
per period, merge non-empty values, emit progress, and write a JSON report with
before/after complete-period counts and failures.

- [ ] **Step 4: Verify repair tests pass**

Run the focused repair tests and expect all to pass.

### Task 3: Read-only API quality metadata

**Files:**
- Modify: `scripts/data_runner.py`
- Modify: `tests/test_data_financials.py`

- [ ] **Step 1: Write failing API tests**

Assert that `action_financials` returns:

```python
{
    "quality": {
        "completeness": {
            "status": "partial",
            "complete_periods": 1,
            "total_periods": 2,
            "ratio": 0.5,
            "latest_complete": False,
            "latest_missing_fields": ["net_profit"],
        },
        "freshness": {
            "status": "current",
            "latest_period": "20260331",
            "expected_period": "20260331",
        },
    }
}
```

- [ ] **Step 2: Verify the API test fails**

Run:

```powershell
python -m pytest tests/test_data_financials.py -q
```

Expected: missing `quality`.

- [ ] **Step 3: Add quality metadata**

Call `analyze_financial_history(history)` inside `action_financials`. Keep the
endpoint read-only and preserve all existing fields.

- [ ] **Step 4: Verify API tests pass**

Run the focused API tests and expect all to pass.

### Task 4: Financial page status display

**Files:**
- Modify: `components/FinancialStatementsPanel.tsx`
- Modify: `scripts/financial_statements_contract_tests.mjs`

- [ ] **Step 1: Write failing contract assertions**

Require the component to render the labels `历史完整度`, `数据时效`,
`覆盖区间`, consume `data.quality.completeness` and
`data.quality.freshness`, and expose status text without animation.

- [ ] **Step 2: Verify the contract test fails**

Run:

```powershell
node scripts/financial_statements_contract_tests.mjs
```

Expected: missing financial quality status labels.

- [ ] **Step 3: Implement compact status line**

Extend `FinancialPayload` with quality types. Below the stock identity header,
render three inline status items:

```text
历史完整度  78.4% (40/51期)
数据时效    当前 / 滞后N季度
覆盖区间    2011 Q4 - 2026 Q1
```

Use existing colors, tabular/monospace numbers, Lucide icons, no gradients,
no animation, and stack cleanly below 720px.

- [ ] **Step 4: Verify frontend tests**

Run the contract test, `npx tsc --noEmit`, and `npm run build`.

### Task 5: Execute repair and verify

**Files:**
- Modify: `README.md`
- Generate: `logs/financial_history_repair_20260722.json`

- [ ] **Step 1: Run ten-year historical repair**

```powershell
python -u scripts/repair_financial_abstracts.py --history-only --history-years 10 --workers 4 --report logs/financial_history_repair_20260722.json
```

- [ ] **Step 2: Re-run the full audit**

Verify latest completeness, historical complete-period ratio, freshness
distribution, and residual failures without treating missing values as zero.

- [ ] **Step 3: Browser verification**

Query `300450`, `002731`, and `688121`. Confirm the quality line matches API
metadata, stale reports are visibly identified, responsive layout remains
stable, and the browser console has no errors.

- [ ] **Step 4: Update README**

Document quality definitions, filing-window freshness rules, repair commands,
report paths, and the rule that source gaps remain `--`.
