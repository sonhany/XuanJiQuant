# Stock Valuation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an auditable stock valuation workspace under Data Browse with absolute, relative, market, and independently generated GLM valuations, including Top100 right-click navigation.

**Architecture:** A dedicated Python valuation domain under `quant/valuation` performs deterministic calculations and persistence. `scripts/valuation_runner.py` exposes the domain through the existing persistent-runner protocol, `/api/valuation` provides the HTTP boundary, and a focused React `ValuationPanel` renders the four independent tracks. `DbPanel.tsx` only owns tab navigation and selected-stock handoff.

**Tech Stack:** Python 3, SQLite, NumPy/Pandas, existing TdxQuant/AkShare/Baostock adapters, GLM through `scripts/llm_client.py`, Node ESM HTTP routes, React 19, TypeScript, Vite, pytest, Node contract tests, in-app browser validation.

---

## File Map

**Create**

- `quant/valuation/__init__.py`: public valuation exports.
- `quant/valuation/contracts.py`: code validation, response states, numeric helpers.
- `quant/valuation/data.py`: TdxQuant-first quote/fundamental/history/peer data adapter.
- `quant/valuation/absolute.py`: cash-flow DCF and sensitivity matrix.
- `quant/valuation/relative.py`: PE/PB/PS/PEG peer valuation.
- `quant/valuation/market.py`: historical/industry/index/liquidity market valuation.
- `quant/valuation/glm.py`: GLM prompt, schema validation and independent valuation.
- `quant/valuation/store.py`: `stock_valuations` schema and persistence.
- `quant/valuation/service.py`: caching, orchestration, status isolation and audit.
- `scripts/valuation_runner.py`: stdin/stdout persistent runner actions.
- `server/routes/valuation.mjs`: `/api/valuation` route.
- `components/ValuationPanel.tsx`: valuation research workspace.
- `scripts/valuation_engine_tests.py`: Python unit tests.
- `scripts/valuation_api_contract_tests.mjs`: route and authorization contracts.
- `scripts/valuation_frontend_contract_tests.mjs`: tab, handoff and UI contracts.

**Modify**

- `server/router.mjs`: register `/api/valuation` and read-only actions.
- `components/DbPanel.tsx`: add valuation tab and Top100 right-click action.
- `README.md`: document valuation formulas, data sources, GLM boundary and usage.

The workspace currently has invalid Git metadata, so execution must not initialize Git or create commits without separate user authorization. Each task ends with a test checkpoint instead.

---

### Task 1: Contracts, Validation, and Persistence

**Files:**
- Create: `quant/valuation/contracts.py`
- Create: `quant/valuation/store.py`
- Create: `quant/valuation/__init__.py`
- Create: `scripts/valuation_engine_tests.py`

- [ ] **Step 1: Write failing validation and persistence tests**

Add tests that define the public contract:

```python
from quant.valuation.contracts import normalize_code, model_result
from quant.valuation.store import ensure_valuation_schema, save_valuation, latest_valuation


def test_normalize_code_accepts_main_a_share_and_rejects_920():
    assert normalize_code("300442.SZ") == "300442"
    assert normalize_code("SH600519") == "600519"
    assert normalize_code("920001") == ""
    assert normalize_code("<script>") == ""


def test_model_result_does_not_replace_missing_value_with_zero():
    result = model_result("absolute", "unavailable", error="missing cash flow")
    assert result["mid"] is None
    assert result["status"] == "unavailable"


def test_stock_valuation_round_trip(tmp_path):
    cache = make_temp_cache(tmp_path)
    assert ensure_valuation_schema(cache)
    valuation_id = save_valuation(cache, {
        "code": "300442",
        "name": "润泽科技",
        "valuation_type": "absolute",
        "status": "success",
        "data_date": "20260710",
        "report_period": "20260331",
        "formula_version": "absolute-v1",
        "input": {"price": 82.25},
        "output": {"mid": 88.0},
    })
    assert valuation_id
    assert latest_valuation(cache, "300442", "absolute")["output"]["mid"] == 88.0
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest scripts\valuation_engine_tests.py -q
```

Expected: collection fails because `quant.valuation` does not exist.

- [ ] **Step 3: Implement the contracts**

`contracts.py` must expose:

```python
VALID_STATUSES = {"success", "partial", "unavailable", "error"}

def normalize_code(value: object) -> str:
    raw = str(value or "").strip().upper()
    raw = raw.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
    if raw.startswith(("SH", "SZ", "BJ")):
        raw = raw[2:]
    if not re.fullmatch(r"\d{6}", raw) or raw.startswith("920"):
        return ""
    if not raw.startswith(("000", "001", "002", "003", "300", "301", "600", "601", "603", "605", "688", "689")):
        return ""
    return raw

def model_result(kind: str, status: str, *, low=None, mid=None, high=None,
                 confidence=None, error="", details=None, warnings=None) -> dict:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid valuation status: {status}")
    return {
        "type": kind,
        "status": status,
        "low": safe_number(low),
        "mid": safe_number(mid),
        "high": safe_number(high),
        "confidence": safe_number(confidence),
        "details": details or {},
        "warnings": warnings or [],
        "error": str(error or ""),
    }
```

- [ ] **Step 4: Implement structured storage**

`store.py` creates:

```sql
CREATE TABLE IF NOT EXISTS stock_valuations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    valuation_id TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    valuation_type TEXT NOT NULL,
    status TEXT NOT NULL,
    data_date TEXT,
    report_period TEXT,
    formula_version TEXT,
    model_version TEXT,
    prompt_version TEXT,
    input_payload TEXT NOT NULL,
    output_payload TEXT NOT NULL,
    created_at TEXT NOT NULL
)
```

Add indexes on `(code, valuation_type, created_at)` and `valuation_id`. Serialize with
`ensure_ascii=False`, return parsed `input` and `output` objects, and use the cache's
existing SQLite connection instead of opening a second database connection.

- [ ] **Step 5: Run the focused tests and verify GREEN**

Run:

```powershell
python -m pytest scripts\valuation_engine_tests.py -q
```

Expected: validation and persistence tests pass.

---

### Task 2: TdxQuant-First Valuation Data Adapter

**Files:**
- Create: `quant/valuation/data.py`
- Modify: `scripts/valuation_engine_tests.py`

- [ ] **Step 1: Write failing normalized-data tests**

Use a representative TdxQuant stock-info payload:

```python
def test_normalize_tdx_fundamentals_maps_units_and_fields():
    raw = {
        "Name": "润泽科技",
        "J_mgsy": "1.42",
        "J_mgjzc": "8.74",
        "J_yysy": "183957.77",
        "J_jly": "58222.96",
        "J_jyxjl": "131585.34",
        "J_zgb": "164104.20",
        "J_zzc": "4709551.50",
        "J_cqfz": "221075.45",
        "rs_hycode_sim": "X4203",
    }
    out = normalize_tdx_fundamentals("300442", raw)
    assert out["eps"] == 1.42
    assert out["total_shares"] == 1_641_042_000
    assert out["revenue"] == 1_839_577_700
    assert out["industry_code"] == "X4203"
```

Add tests for:

- latest quote from TdxQuant snapshot with `stock_daily_summary` fallback;
- `fin:abstract:<code>` history with JSON `NaN` values converted to `None`;
- industry fallback through Baostock cache refresh;
- K-line coverage metadata;
- peer collection capped at 24 codes and excluding ST/920xxx.

- [ ] **Step 2: Run the adapter tests and verify RED**

Run:

```powershell
python -m pytest scripts\valuation_engine_tests.py -q
```

Expected: imports or assertions fail because `quant/valuation/data.py` is absent.

- [ ] **Step 3: Implement normalized TdxQuant fundamentals**

Map official fields without relying on mojibake names:

```python
TDX_UNIT_10K = 10_000.0

def normalize_tdx_fundamentals(code: str, raw: dict) -> dict:
    return {
        "code": code,
        "name": decode_name(raw.get("Name")) or code,
        "eps": number(raw.get("J_mgsy")),
        "bvps": number(raw.get("J_mgjzc")),
        "revenue": scaled(raw.get("J_yysy"), TDX_UNIT_10K),
        "net_profit": scaled(raw.get("J_jly"), TDX_UNIT_10K),
        "operating_cash_flow": scaled(raw.get("J_jyxjl"), TDX_UNIT_10K),
        "total_shares": scaled(raw.get("J_zgb"), TDX_UNIT_10K),
        "total_assets": scaled(raw.get("J_zzc"), TDX_UNIT_10K),
        "long_term_debt": scaled(raw.get("J_cqfz"), TDX_UNIT_10K),
        "industry_code": str(raw.get("rs_hycode_sim") or ""),
        "is_st": str(raw.get("IsSTGP") or "0") == "1",
        "source": "tdx_quant_stock_info",
    }
```

If TdxQuant is unavailable, read cached `fin:abstract:<code>` and call the existing
AkShare reconciler only for the selected stock. Preserve all warnings and source names.

- [ ] **Step 4: Implement peer and market inputs**

`ValuationDataProvider` must:

- read quote and daily history from existing sources/cache;
- ensure industry cache exists by invoking a reusable Baostock industry loader once;
- select same-industry peers from `stock:industry:*`;
- rank candidates by amount and data availability;
- fetch at most 24 peer stock-info records concurrently with a bounded pool;
- cache normalized stock info under `valuation:fundamental:<code>` for 24 hours;
- fetch benchmark index K-lines and derive breadth/liquidity from `stock_daily_summary`;
- never scan external sources on every cached request.

- [ ] **Step 5: Verify the adapter**

Run:

```powershell
python -m pytest scripts\valuation_engine_tests.py -q
```

Expected: all data-adapter tests pass without writing to production tables when a temporary cache is supplied.

---

### Task 3: Deterministic Valuation Engines

**Files:**
- Create: `quant/valuation/absolute.py`
- Create: `quant/valuation/relative.py`
- Create: `quant/valuation/market.py`
- Modify: `scripts/valuation_engine_tests.py`

- [ ] **Step 1: Write failing calculation tests**

Define deterministic expectations:

```python
def test_absolute_valuation_returns_three_ordered_scenarios():
    result = absolute_valuation(sample_inputs())
    assert result["status"] in {"success", "partial"}
    assert 0 < result["low"] < result["mid"] < result["high"]
    assert len(result["details"]["sensitivity"]) == 9


def test_relative_valuation_uses_only_valid_multiples():
    result = relative_valuation(target, peers)
    assert result["details"]["sample_count"] == 3
    assert result["details"]["excluded_count"] == 2
    assert set(result["details"]["methods"]) >= {"pe", "pb", "ps"}


def test_market_valuation_reports_actual_coverage():
    result = market_valuation(target, history_18_months, market_context)
    assert result["status"] == "partial"
    assert result["details"]["coverage_months"] == 18
    assert "不足3年" in result["warnings"][0]
```

Also cover negative EPS, negative book value, missing cash flow, invalid WACC, outlier
winsorization, PEG with non-positive growth, and bounded market adjustments.

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m pytest scripts\valuation_engine_tests.py -q
```

Expected: engine modules are missing.

- [ ] **Step 3: Implement absolute valuation**

Use operating cash flow less explicit capex when available. If capex is absent, calculate
a disclosed maintenance-capex proxy and mark the result `partial`.

```python
def discounted_cash_flow(base_cash, growth, discount, terminal_growth, years=5):
    if base_cash <= 0 or not (terminal_growth < discount < 0.30):
        return None
    flows = [base_cash * (1 + growth) ** year for year in range(1, years + 1)]
    pv = sum(flow / (1 + discount) ** year for year, flow in enumerate(flows, 1))
    terminal = flows[-1] * (1 + terminal_growth) / (discount - terminal_growth)
    return pv + terminal / (1 + discount) ** years
```

Create conservative/base/optimistic scenarios with bounded growth, WACC and terminal
growth. Convert equity value to per-share value, subtract debt/add cash only when present,
and return no value when total shares are unavailable.

- [ ] **Step 4: Implement relative valuation**

Calculate target prices independently:

```python
pe_price = peer_median_pe * target_eps
pb_price = peer_median_pb * target_bvps
ps_price = peer_median_ps * target_revenue_per_share
peg_price = peer_median_peg * positive_growth_rate * target_eps
```

Use median and 25th/75th percentiles after IQR filtering. Keep method-level values visible;
the track midpoint is the median of valid method prices.

- [ ] **Step 5: Implement market valuation**

Calculate:

- target historical return/valuation proxy percentile;
- peer/industry valuation percentile;
- index regime;
- breadth from positive `change_pct`;
- liquidity from current amount versus trailing summary.

Combine bounded factors:

```python
adjustment = clamp(
    0.40 * own_factor + 0.30 * industry_factor +
    0.20 * index_factor + 0.10 * liquidity_factor,
    -0.20,
    0.20,
)
```

Apply the adjustment to the deterministic reference midpoint and expose every component.

- [ ] **Step 6: Run tests and verify GREEN**

Run:

```powershell
python -m pytest scripts\valuation_engine_tests.py -q
```

Expected: deterministic engine tests pass.

---

### Task 4: GLM Contract and Valuation Orchestration

**Files:**
- Create: `quant/valuation/glm.py`
- Create: `quant/valuation/service.py`
- Modify: `scripts/valuation_engine_tests.py`

- [ ] **Step 1: Write failing GLM and orchestration tests**

Test accepted and rejected outputs:

```python
VALID_GLM = {
    "target_low": 75.0,
    "target_mid": 88.0,
    "target_high": 102.0,
    "confidence": 0.72,
    "assumptions": ["收入保持增长"],
    "drivers": ["算力基础设施需求"],
    "risks": ["资本开支"],
    "invalidation_conditions": ["增长显著低于预期"],
    "model_version": "glm-5.2",
    "prompt_version": "valuation-v1",
}

def test_validate_glm_rejects_unordered_prices():
    bad = {**VALID_GLM, "target_low": 100, "target_high": 80}
    assert validate_glm_output(bad)["status"] == "error"


def test_service_isolates_failed_tracks():
    result = service.analyze("300442")
    assert set(result["valuations"]) == {"absolute", "relative", "market"}
    assert result["valuations"]["absolute"]["status"] == "unavailable"
    assert result["valuations"]["relative"]["status"] == "success"
```

Test cache signature changes when price date, report period or formula version changes.

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m pytest scripts\valuation_engine_tests.py -q
```

Expected: GLM/service imports fail.

- [ ] **Step 3: Implement strict GLM validation**

`glm.py` calls:

```python
chat_json(
    "glm",
    system_prompt,
    json.dumps(structured_input, ensure_ascii=False),
    temperature=0.2,
    timeout=45,
    max_tokens=1400,
    scene="valuation",
)
```

Validate required arrays, confidence in `[0, 1]`, positive ordered prices, and a maximum
price distance of five times the current price. Return `error` instead of repairing
invalid model output.

- [ ] **Step 4: Implement the service**

`ValuationService` exposes:

```python
def analyze(self, code: str, force: bool = False) -> dict: ...
def glm_analyze(self, code: str, force: bool = False) -> dict: ...
def latest(self, code: str) -> dict: ...
```

The service:

- builds one normalized input snapshot;
- runs deterministic tracks independently;
- saves every track to `stock_valuations`;
- writes `audit_events` with event type `stock_valuation`;
- caches deterministic results for 30 minutes by data signature;
- caches GLM results by data signature/model/prompt version;
- never calls GLM from `analyze`;
- never emits order intent or trading actions.

- [ ] **Step 5: Run the complete Python valuation suite**

Run:

```powershell
python -m pytest scripts\valuation_engine_tests.py -q
```

Expected: all valuation tests pass.

---

### Task 5: Runner, HTTP Route, and Authorization

**Files:**
- Create: `scripts/valuation_runner.py`
- Create: `server/routes/valuation.mjs`
- Create: `scripts/valuation_api_contract_tests.mjs`
- Modify: `server/router.mjs`

- [ ] **Step 1: Write failing API contract tests**

Assert:

```javascript
assert(router.includes("'/api/valuation'"));
assert(router.includes("'analyze'") && router.includes("'latest'"));
assert(!readOnlyValuationBlock.includes("'glm_analyze'"));
assert(route.includes("new PersistentRunner('valuation_runner.py')"));
assert(runner.includes("'analyze': action_analyze"));
assert(runner.includes("'glm_analyze': action_glm_analyze"));
assert(runner.includes("'latest': action_latest"));
```

Add a live API check when port `8880` is available:

- `analyze` with `300442` returns HTTP 200 and three deterministic tracks;
- `analyze` with `920001` returns HTTP 400;
- unauthenticated `glm_analyze` returns HTTP 403 when API token is configured.

- [ ] **Step 2: Run the Node contract test and verify RED**

Run:

```powershell
node scripts\valuation_api_contract_tests.mjs
```

Expected: route/runner assertions fail.

- [ ] **Step 3: Implement the runner protocol**

`valuation_runner.py` reads newline-delimited JSON, dispatches the three actions, catches
exceptions per request, and returns:

```json
{"id":"request-id","success":true,"data":{}}
```

Invalid codes return `{"success": false, "status": 400, "error": "invalid code"}`.

- [ ] **Step 4: Implement and register `/api/valuation`**

Follow `server/routes/factor.mjs`:

```javascript
const runner = new PersistentRunner('valuation_runner.py');

export async function handleValuation(req, res) {
  const body = await readBody(req);
  log('INFO', `[Valuation] action=${body.action || 'latest'} code=${body.code || ''}`);
  try {
    const data = await runner.call(body);
    return json(res, data.success ? 200 : Number(data.status || 500), data);
  } catch (error) {
    return json(res, 500, { success: false, error: `估值服务异常: ${error.message}` });
  }
}
```

Register `analyze` and `latest` as read-only. Keep `glm_analyze` protected because it
consumes model quota and writes audit records.

- [ ] **Step 5: Restart the backend and verify API GREEN**

Restart only the backend process through the project launcher, then run:

```powershell
node scripts\valuation_api_contract_tests.mjs
```

Expected: contract and live API checks pass.

---

### Task 6: Valuation Research Workspace

**Files:**
- Create: `components/ValuationPanel.tsx`
- Create: `scripts/valuation_frontend_contract_tests.mjs`
- Modify: `components/DbPanel.tsx`

- [ ] **Step 1: Write failing frontend contracts**

Assert:

```javascript
assert(dbPanel.includes("{ key: 'valuation', label: '股票估值'"));
assert(dbPanel.indexOf("key: 'valuation'") < dbPanel.indexOf("key: 'realtime'"));
assert(dbPanel.includes('ctxMenuGoValuation'));
assert(dbPanel.includes('<ValuationPanel'));
assert(dbPanel.includes('股票估值'));
assert(panel.includes("action: 'analyze'"));
assert(panel.includes("action: 'glm_analyze'"));
assert(panel.includes('绝对估值'));
assert(panel.includes('相对估值'));
assert(panel.includes('市场估值'));
assert(panel.includes('GLM 模型估值'));
```

Also verify the context menu retains its existing three actions.

- [ ] **Step 2: Run the frontend contract and verify RED**

Run:

```powershell
node scripts\valuation_frontend_contract_tests.mjs
```

Expected: missing tab/component/action assertions fail.

- [ ] **Step 3: Implement `ValuationPanel`**

Props:

```typescript
interface ValuationPanelProps {
  initialCode: string;
  initialName?: string;
  requestKey: number;
}
```

State separates deterministic loading from GLM loading. On `initialCode/requestKey`
change, call `analyze`. The GLM button calls `glm_analyze` only after explicit click.
Independent cards render `status`, `low/mid/high`, confidence, warnings and errors.

Use:

- five stable summary columns with responsive `minmax`;
- four un-nested result panels;
- explicit data-date/source badges;
- a DCF sensitivity table;
- peer sample and exclusion details;
- market component scores;
- GLM assumptions/drivers/risks;
- a bottom audit/data-quality section.

Do not define inline React components inside `ValuationPanel`; extract reusable
`SummaryMetric`, `ValuationTrack`, and `StatusBadge` at module scope.

- [ ] **Step 4: Wire the Data Browse tab and right-click action**

In `DbPanel.tsx`:

```typescript
type DbTab = 'browse' | 'valuation' | 'realtime' | 'kline' | 'manage';
const [valuationStock, setValuationStock] = useState({ code: '300442', name: '' });
const [valuationRequestKey, setValuationRequestKey] = useState(0);

const ctxMenuGoValuation = (stock: Stock) => {
  setValuationStock({ code: stock.code, name: stock.name || stock.code });
  setValuationRequestKey(value => value + 1);
  setTab('valuation');
  setCtxMenu(null);
};
```

Add a `Scale` icon menu action labeled “股票估值” and render:

```tsx
{tab === 'valuation' && (
  <ValuationPanel
    initialCode={valuationStock.code}
    initialName={valuationStock.name}
    requestKey={valuationRequestKey}
  />
)}
```

- [ ] **Step 5: Run frontend contracts and build**

Run:

```powershell
node scripts\valuation_frontend_contract_tests.mjs
npm run build
```

Expected: frontend contracts pass and Vite build exits 0.

---

### Task 7: Documentation and Full Verification

**Files:**
- Modify: `README.md`
- Modify: `scripts/web_verify.mjs`

- [ ] **Step 1: Add a valuation check to Web verification**

Add read-only `analyze` verification for `300442`:

```javascript
const valuation = await post('/api/valuation', { action: 'analyze', code: '300442' });
check(
  '股票估值 — 三类规则模型',
  valuation.success &&
  ['absolute', 'relative', 'market'].every(key => valuation.data?.valuations?.[key]),
);
```

Do not automatically call GLM in `web_verify.mjs`; GLM connectivity is already tested
separately and automated valuation calls would waste quota.

- [ ] **Step 2: Update README**

Document:

- the new Data Browse tab and Top100 right-click action;
- four independent valuation tracks;
- formulas and data-source priority;
- partial/unavailable status meaning;
- manual-only GLM behavior;
- `stock_valuations`, `model_calls`, and `audit_events`;
- `/api/valuation` actions;
- explicit research-only/non-trading boundary.

- [ ] **Step 3: Run the complete automated suite**

Run:

```powershell
$py = @(Get-ChildItem scripts -File -Filter '*tests.py' | ForEach-Object FullName) +
      @(Get-ChildItem tests -Recurse -File -Filter 'test_*.py' -ErrorAction SilentlyContinue | ForEach-Object FullName)
python -m pytest -q $py

$failed = @()
$node = Get-ChildItem scripts -File -Filter '*_tests.mjs' |
  Where-Object { $_.Name -ne 'hourly_loop_test.mjs' }
foreach ($file in $node) {
  node $file.FullName
  if ($LASTEXITCODE -ne 0) { $failed += $file.Name }
}
if ($failed.Count) { throw "Node test failures: $($failed -join ', ')" }

npm run build
node scripts\web_verify.mjs
```

Expected: zero Python failures, zero Node failures, successful build, and all Web checks pass.

- [ ] **Step 4: Perform browser interaction validation**

Using the in-app browser:

1. Open Data Browse and confirm “股票估值” follows “市场浏览”.
2. Enter `300442` and run deterministic valuation.
3. Confirm all four tracks are present and GLM remains uncalled initially.
4. Return to Market Browse, right-click a Top100 row, and choose “股票估值”.
5. Confirm navigation carries the selected code/name and automatically reruns deterministic valuation.
6. Click “运行 GLM 估值” once and confirm independent target range, confidence, assumptions and risks.
7. Verify partial/unavailable tracks do not blank the page.
8. Inspect console errors and network failures.

- [ ] **Step 5: Verify persistence and audit**

Run a read-only SQLite query:

```powershell
python -c "import sqlite3; c=sqlite3.connect('data/quant.db'); print(c.execute('pragma integrity_check').fetchone()[0]); print(c.execute('select valuation_type,status,count(*) from stock_valuations group by valuation_type,status').fetchall()); print(c.execute(\"select count(*) from model_calls where scene='valuation'\").fetchone()[0])"
```

Expected: integrity `ok`, deterministic rows present, and one GLM valuation model call after the manual browser test.

