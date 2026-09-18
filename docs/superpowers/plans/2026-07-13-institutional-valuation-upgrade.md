# Institutional Valuation Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the stock valuation module with correct FCFE/FCFF discounting, point-in-time financial inputs, quality-matched peers, non-duplicative consensus pricing, and historical model calibration.

**Architecture:** Add focused financial-normalization and calibration modules under `quant/valuation`. Keep absolute, relative, market and GLM tracks independently auditable, but introduce a deterministic consensus layer where absolute and relative models form base value and market state applies exactly once. Preserve the existing API and frontend navigation.

**Tech Stack:** Python 3, SQLite, existing cache/data adapters, pytest, React 19, TypeScript, Vite, Node contract tests.

---

### Task 1: Point-in-Time and TTM Financial Metrics

**Files:**
- Create: `quant/valuation/financials.py`
- Modify: `quant/valuation/data.py`
- Modify: `quant/data/akshare_source.py`
- Test: `scripts/valuation_engine_tests.py`

- [x] Add failing tests for announcement-date filtering, cumulative-report TTM calculation and `report_period_only` quality.
- [x] Run `python -m pytest scripts/valuation_engine_tests.py -q -k "point_in_time or ttm"` and verify the assertions fail.
- [x] Implement `filter_point_in_time_records(records, valuation_as_of)` and `build_ttm_metrics(records)`.
- [x] Add `valuation_as_of`, `financial_as_of`, `point_in_time_quality`, `ttm` and `annual_records` to financial-history output.
- [x] Run the focused tests and verify they pass.

### Task 2: Correct FCFE and FCFF Discounting

**Files:**
- Modify: `quant/valuation/absolute.py`
- Test: `scripts/valuation_engine_tests.py`

- [x] Add failing tests proving FCFE uses `Ke`, FCFF uses full WACC, and the labels differ.
- [x] Add a failing test for normalized three-year cash flow and a five-year growth-decay schedule.
- [x] Implement `cost_of_equity`, `weighted_average_cost_of_capital`, normalized annual cash flow and three-stage forecast helpers.
- [x] Expose `discount_rate_type`, `cost_of_equity`, `wacc_components`, `normalized_cash_flow` and `forecast_schedule`.
- [x] Run all absolute valuation tests.

### Task 3: Profit-Growth PEG and Similarity-Weighted Peers

**Files:**
- Modify: `quant/valuation/data.py`
- Modify: `quant/valuation/service.py`
- Modify: `quant/valuation/relative.py`
- Test: `scripts/valuation_engine_tests.py`

- [x] Add failing tests that distinguish revenue growth from profit growth for PEG.
- [x] Add failing tests for market-cap, ROE, margin and growth peer similarity.
- [x] Include profit growth, ROE, net margin and similarity weight in peer evaluation.
- [x] Implement weighted peer quantiles and method-quality weights.
- [x] Run relative valuation and peer collection tests.

### Task 4: Historical Calibration Store

**Files:**
- Create: `quant/valuation/calibration.py`
- Modify: `quant/valuation/store.py`
- Test: `scripts/valuation_engine_tests.py`

- [x] Add schema and round-trip tests for valuation forecasts.
- [x] Add failing tests for neutral prior below 20 samples and bounded reliability at 20 or more samples.
- [x] Create `valuation_forecasts` and `valuation_model_calibration` tables using the existing cache connection.
- [x] Implement forecast recording, matured-outcome updates and reliability calculation.
- [x] Run calibration tests.

### Task 5: Non-Duplicative Consensus and Market Adjustment

**Files:**
- Create: `quant/valuation/consensus.py`
- Modify: `quant/valuation/service.py`
- Modify: `quant/valuation/market.py`
- Test: `scripts/valuation_engine_tests.py`

- [x] Add a failing test showing the final midpoint is not the arithmetic mean of absolute, relative and market tracks.
- [x] Add tests for confidence, data-quality and calibration-weight composition.
- [x] Implement base-value weighting from absolute and relative tracks only.
- [x] Pass the base value to the market model and expose one final adjusted value plus weight provenance.
- [x] Record forecasts after successful deterministic analysis.
- [x] Run service and market tests.

### Task 6: Frontend Labels and Diagnostics

**Files:**
- Modify: `components/ValuationPanel.tsx`
- Modify: `scripts/valuation_frontend_contract_tests.mjs`

- [x] Add frontend contract assertions for Ke/WACC labels, consensus weights, PIT quality and forecast schedule.
- [x] Render the final consensus midpoint instead of averaging three track midpoints.
- [x] Render discount-rate type, normalized cash flow, model weights and PIT quality without adding nested cards.
- [x] Run `node scripts/valuation_frontend_contract_tests.mjs`.

### Task 7: Documentation and Full Verification

**Files:**
- Modify: `README.md`

- [x] Document FCFE/Ke, FCFF/WACC, TTM/PIT, peer similarity, consensus and calibration semantics.
- [x] Run `python -m pytest scripts/valuation_engine_tests.py -q`.
- [x] Run `node scripts/valuation_api_contract_tests.mjs`.
- [x] Run `node scripts/valuation_frontend_contract_tests.mjs`.
- [x] Run `python -m compileall -q quant/valuation`.
- [x] Run `npm run build`.
- [x] Restart the backend and verify two stocks through `/api/valuation`.
- [x] Verify the valuation page with the in-app browser, including one manual GLM call.
