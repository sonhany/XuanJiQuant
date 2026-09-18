# Market Browser Money Flow and Turnover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有市场浏览成交额 Top100 中增加换手率、主力净流入额和主力净流入占比，同时保留原有行情主源、排序、轮询和失败降级行为。

**Architecture:** 现有 `DbPanel -> /api/data -> data-stocks PersistentRunner -> data_runner -> market_data` 链路保持不变。`data_runner` 在现有 TopN 排序截取后调用 `market_data` 的批量补充函数；东方财富提供三项指标，腾讯只在东方财富缺失时补换手率，所有失败均降级为缺失值而不阻断股票列表。

**Tech Stack:** React 19、TypeScript、Node.js ES Modules、Python、Pytest、现有 Node 契约测试、Vite。

---

## 文件边界

**新增**

- `tests/test_market_money_flow.py`：数据源解析、缓存、腾讯降级和 TopN 合并回归测试。

**修改**

- `scripts/market_data.py`：东方财富批量指标适配及进程内短缓存。
- `quant/data/tencent_source.py`：保留腾讯原始实时行情字段 38 的换手率。
- `scripts/data_runner.py`：TopN 截取后统一合并新增指标。
- `scripts/data_browse_contract_tests.mjs`：前端字段、列、排序、CSV 和布局契约。
- `components/DbPanel.tsx`：类型、规范化、表格列、格式、来源说明和 CSV。
- `README.md`：完整调用链、来源口径、降级策略和维护边界。

**明确不修改**

- `server/router.mjs`、`server/routes/data.mjs`：现有只读 `stocks` 路由已经满足要求。
- SQLite schema、交易、风控、AI、因子、Qlib：新增指标只是市场浏览时的只读补充。

**Git 限制**

当前 `C:\Users\HYSHEN\XuanJiQuant` 没有 `.git` 元数据，无法执行提交步骤。每个任务以测试通过和文件差异复核作为检查点；若后续恢复 Git，再按任务边界分别提交。

### Task 1: 数据源解析与进程内短缓存

**Files:**

- Create: `tests/test_market_money_flow.py`
- Modify: `quant/data/tencent_source.py:175-210`
- Modify: `scripts/market_data.py:22-43,478-510`

- [ ] **Step 1: 写东方财富和腾讯字段的失败测试**

创建 `tests/test_market_money_flow.py`，先覆盖字段口径、缺失值和腾讯字段 38：

```python
import json
from unittest.mock import patch


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_tencent_quote_preserves_turnover_rate():
    from quant.data.tencent_source import _parse_qt_line

    parts = [""] * 39
    parts[1] = "贵州茅台"
    parts[2] = "600519"
    parts[3] = "1350.60"
    parts[4] = "1348.00"
    parts[5] = "1349.00"
    parts[6] = "1000"
    parts[30] = "20260801103000"
    parts[33] = "1360.00"
    parts[34] = "1340.00"
    parts[37] = "737346"
    parts[38] = "0.44"

    quote = _parse_qt_line('v_sh600519="' + "~".join(parts) + '";')

    assert quote["turnover_rate"] == 0.44
    assert quote["amount"] == 737346.0


def test_eastmoney_metrics_keep_zero_and_missing_distinct(monkeypatch):
    from scripts import market_data

    payload = {
        "data": {
            "diff": [
                {"f12": "600519", "f8": 0.44, "f62": -218031792.0, "f184": -2.96},
                {"f12": "000001", "f8": 0, "f62": 0, "f184": 0},
                {"f12": "300750", "f8": "-", "f62": None, "f184": None},
            ]
        }
    }
    monkeypatch.setattr(market_data.urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse(payload))
    market_data._STOCK_METRICS_CACHE.clear()

    result = market_data.fetch_stock_market_metrics(["600519", "000001", "300750"], use_cache=False)

    assert result["items"]["600519"]["main_net_inflow"] == -218031792.0
    assert result["items"]["600519"]["main_net_inflow_pct"] == -2.96
    assert result["items"]["600519"]["turnover_rate"] == 0.44
    assert result["items"]["000001"]["turnover_rate"] == 0.0
    assert result["items"]["300750"]["turnover_rate"] is None
```

- [ ] **Step 2: 运行测试并确认因功能缺失而失败**

Run:

```powershell
python -m pytest tests/test_market_money_flow.py -q
```

Expected: FAIL，原因是 `turnover_rate` 未返回且 `fetch_stock_market_metrics` 不存在。

- [ ] **Step 3: 最小扩展腾讯字段 38**

在 `_QT_FIELDS` 增加字段，并在校验成功后附加可选换手率，避免改变 `validate_quote` 的既有必需字段：

```python
_QT_FIELDS = {
    "name": 1, "code": 2, "price": 3, "prev_close": 4, "open": 5,
    "volume": 6, "date_time": 30, "high": 33, "low": 34, "amount": 37,
    "turnover_rate": 38,
}

quote = validate_quote({
    "code": sym[2:] if sym[:2] in ("sh", "sz", "bj") else sym,
    "name": parts[_QT_FIELDS["name"]],
    "price": float(parts[_QT_FIELDS["price"]]),
    "open": float(parts[_QT_FIELDS["open"]]),
    "high": float(parts[_QT_FIELDS["high"]]),
    "low": float(parts[_QT_FIELDS["low"]]),
    "prev_close": float(parts[_QT_FIELDS["prev_close"]]),
    "volume": int(float(parts[_QT_FIELDS["volume"]])),
    "amount": float(parts[_QT_FIELDS["amount"]]) if parts[_QT_FIELDS["amount"]] else 0.0,
    "timestamp": ts,
})
turnover_raw = parts[_QT_FIELDS["turnover_rate"]] if len(parts) > _QT_FIELDS["turnover_rate"] else ""
quote["turnover_rate"] = float(turnover_raw) if turnover_raw not in ("", "-") else None
return quote
```

- [ ] **Step 4: 在 `market_data.py` 增加隔离式东方财富适配器**

增加进程内缓存和纯解析辅助函数，不写 SQLite：

```python
import math
import threading

STOCK_METRICS_TTL = 20
STOCK_METRICS_BATCH_SIZE = 50
_STOCK_METRICS_CACHE = {}
_STOCK_METRICS_LOCK = threading.Lock()


def _optional_float(value):
    if value in (None, "", "-"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _eastmoney_secid(code):
    pure = re.sub(r"\D", "", str(code or ""))[-6:]
    if len(pure) != 6:
        return ""
    market = "1" if pure.startswith(("5", "6", "9")) else "0"
    return f"{market}.{pure}"


def _fetch_eastmoney_stock_metrics(codes):
    result = {}
    for start in range(0, len(codes), STOCK_METRICS_BATCH_SIZE):
        chunk = codes[start:start + STOCK_METRICS_BATCH_SIZE]
        secids = ",".join(filter(None, (_eastmoney_secid(code) for code in chunk)))
        if not secids:
            continue
        url = (
            "https://push2delay.eastmoney.com/api/qt/ulist.np/get"
            "?fltt=2&invt=2&fields=f8,f12,f62,f184&secids=" + secids
        )
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"})
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        for item in ((payload.get("data") or {}).get("diff") or []):
            code = str(item.get("f12") or "")
            if not code:
                continue
            result[code] = {
                "turnover_rate": _optional_float(item.get("f8")),
                "main_net_inflow": _optional_float(item.get("f62")),
                "main_net_inflow_pct": _optional_float(item.get("f184")),
                "money_flow_source": "eastmoney",
                "turnover_source": "eastmoney",
            }
    return result
```

增加完整的编排函数：规范化去重、调用东方财富、仅对换手率缺失代码调用腾讯、返回来源元数据，并只缓存实际取得过上游数据的结果：

```python
def _metric_code(value):
    pure = re.sub(r"\D", "", str(value or ""))[-6:]
    return pure if len(pure) == 6 else ""


def _empty_stock_metric():
    return {
        "turnover_rate": None,
        "main_net_inflow": None,
        "main_net_inflow_pct": None,
        "money_flow_source": None,
        "turnover_source": None,
    }


def fetch_stock_market_metrics(codes, use_cache=True):
    normalized = []
    for value in codes or []:
        code = _metric_code(value)
        if code and code not in normalized:
            normalized.append(code)
    if not normalized:
        return {"items": {}, "fetched_at": "", "source": "unavailable"}

    cache_key = tuple(normalized)
    now = time.time()
    if use_cache:
        with _STOCK_METRICS_LOCK:
            cached = _STOCK_METRICS_CACHE.get(cache_key)
            if cached and now - cached["time"] < STOCK_METRICS_TTL:
                return cached["payload"]

    items = {code: _empty_stock_metric() for code in normalized}
    eastmoney_items = {}
    try:
        eastmoney_items = _fetch_eastmoney_stock_metrics(normalized)
    except Exception as exc:
        logger.debug("fetch stock metrics from eastmoney failed: %s", exc)
    for code, metric in eastmoney_items.items():
        if code in items:
            items[code].update(metric)

    missing_turnover = [code for code in normalized if items[code]["turnover_rate"] is None]
    tencent_items = {}
    if missing_turnover:
        try:
            from quant.data.tencent_source import fetch_quotes as fetch_tencent_quotes
            tencent_items = fetch_tencent_quotes(missing_turnover)
        except Exception as exc:
            logger.debug("fetch turnover fallback from tencent failed: %s", exc)
    for code in missing_turnover:
        turnover = _optional_float((tencent_items.get(code) or {}).get("turnover_rate"))
        if turnover is not None:
            items[code]["turnover_rate"] = turnover
            items[code]["turnover_source"] = "tencent"

    payload = {
        "items": items,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": "eastmoney" if eastmoney_items else ("tencent_turnover" if tencent_items else "unavailable"),
    }
    if eastmoney_items or tencent_items:
        with _STOCK_METRICS_LOCK:
            _STOCK_METRICS_CACHE[cache_key] = {"time": now, "payload": payload}
    return payload
```

- [ ] **Step 5: 增加腾讯降级和缓存失败测试**

在同一测试文件追加：

```python
def test_metrics_use_tencent_only_for_missing_turnover(monkeypatch):
    from scripts import market_data
    from quant.data import tencent_source

    monkeypatch.setattr(market_data, "_fetch_eastmoney_stock_metrics", lambda codes: {
        "600519": {
            "turnover_rate": None,
            "main_net_inflow": -10.0,
            "main_net_inflow_pct": -1.0,
            "money_flow_source": "eastmoney",
            "turnover_source": "eastmoney",
        }
    })
    monkeypatch.setattr(tencent_source, "fetch_quotes", lambda codes: {
        "600519": {"turnover_rate": 0.44}
    })
    market_data._STOCK_METRICS_CACHE.clear()

    result = market_data.fetch_stock_market_metrics(["600519"], use_cache=False)

    assert result["items"]["600519"]["turnover_rate"] == 0.44
    assert result["items"]["600519"]["turnover_source"] == "tencent"
    assert result["items"]["600519"]["main_net_inflow"] == -10.0
```

- [ ] **Step 6: 运行数据源测试至通过**

Run:

```powershell
python -m pytest tests/test_market_money_flow.py -q
```

Expected: PASS，且没有真实外部网络请求。

### Task 2: Top100 截取后合并，保持原有排序和失败边界

**Files:**

- Modify: `tests/test_market_money_flow.py`
- Modify: `scripts/data_runner.py:193-285,290-354,357-428`

- [ ] **Step 1: 写 TopN 后合并的失败测试**

追加测试，断言资金接口只收到截取后的代码且不改变成交额顺序：

```python
def test_top_stocks_enrich_after_limit_without_resorting(monkeypatch):
    from scripts import data_runner, market_data

    monkeypatch.setattr(data_runner, "_available_stock_codes", lambda: ["600001", "600002", "600003"])
    monkeypatch.setattr(data_runner, "_stock_name", lambda code: code)
    monkeypatch.setattr(market_data, "fetch_realtime", lambda codes, use_cache=True: {
        "sh600001": {"name": "A", "price": 10, "prev_close": 9, "high": 10, "low": 9, "chg_pct": 1, "volume": 10, "amount": 300, "source": "sina", "time": "10:00:00"},
        "sh600002": {"name": "B", "price": 10, "prev_close": 9, "high": 10, "low": 9, "chg_pct": 1, "volume": 10, "amount": 200, "source": "sina", "time": "10:00:00"},
        "sh600003": {"name": "C", "price": 10, "prev_close": 9, "high": 10, "low": 9, "chg_pct": 1, "volume": 10, "amount": 100, "source": "sina", "time": "10:00:00"},
    })
    seen = []
    monkeypatch.setattr(market_data, "fetch_stock_market_metrics", lambda codes, use_cache=True: (
        seen.extend(codes) or {
            "items": {code: {"turnover_rate": i + 1.0, "main_net_inflow": i * 10.0, "main_net_inflow_pct": i * 0.1} for i, code in enumerate(codes)},
            "fetched_at": "2026-08-01T10:00:00",
            "source": "eastmoney",
        }
    ))

    result = data_runner._top_realtime_stocks(sort_by="amount", limit=2, bypass_cache=True)

    assert seen == ["600001", "600002"]
    assert [row["code"] for row in result["stocks"]] == ["600001", "600002"]
    assert result["stocks"][0]["turnover_rate"] == 1.0
    assert result["market_metrics"]["source"] == "eastmoney"
```

- [ ] **Step 2: 运行目标测试并确认失败**

Run:

```powershell
python -m pytest tests/test_market_money_flow.py::test_top_stocks_enrich_after_limit_without_resorting -q
```

Expected: FAIL，返回行没有新增字段且补充函数未调用。

- [ ] **Step 3: 增加统一合并函数**

在 `data_runner.py` 增加：

```python
MARKET_METRIC_FIELDS = (
    "turnover_rate", "main_net_inflow", "main_net_inflow_pct",
    "money_flow_source", "turnover_source",
)


def _enrich_stock_market_metrics(stocks):
    default_meta = {"source": "unavailable", "fetched_at": "", "available": False}
    if not stocks:
        return default_meta
    try:
        from scripts.market_data import fetch_stock_market_metrics
        payload = fetch_stock_market_metrics([row.get("code") for row in stocks], use_cache=True)
        items = payload.get("items") if isinstance(payload, dict) else {}
        for row in stocks:
            metric = (items or {}).get(str(row.get("code") or ""), {})
            for field in MARKET_METRIC_FIELDS:
                row[field] = metric.get(field)
        return {
            "source": payload.get("source") or "eastmoney",
            "fetched_at": payload.get("fetched_at") or "",
            "available": any((items or {}).values()),
        }
    except Exception:
        for row in stocks:
            for field in MARKET_METRIC_FIELDS:
                row[field] = None
        return default_meta
```

在三个返回路径中均先完成原有排序/切片，再调用此函数，并把结果放入顶层 `market_metrics`。不要在合并后重新排序。

- [ ] **Step 4: 写异常不阻断原列表的失败测试**

```python
def test_metric_failure_does_not_break_top_stocks(monkeypatch):
    from scripts import data_runner, market_data

    rows = [{"code": "600519", "amount": 100.0}]
    monkeypatch.setattr(market_data, "fetch_stock_market_metrics", lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("upstream timeout")))

    meta = data_runner._enrich_stock_market_metrics(rows)

    assert rows[0]["code"] == "600519"
    assert rows[0]["main_net_inflow"] is None
    assert meta["available"] is False
```

- [ ] **Step 5: 运行新增与既有数据链路测试**

Run:

```powershell
python -m pytest tests/test_market_money_flow.py scripts/data_source_chain_contract_tests.py -q
```

Expected: 全部 PASS；既有成交量单位、TdxQuant 主源和成交额重排测试不回归。

### Task 3: 市场浏览三列、排序、CSV 与可用布局

**Files:**

- Modify: `scripts/data_browse_contract_tests.mjs:16-34`
- Modify: `components/DbPanel.tsx:11,277-290,464-489,740-855`

- [ ] **Step 1: 先增加前端失败契约**

在 `testMarketBrowseRequestsTop100ByAmount` 中追加：

```javascript
assert(src.includes('turnover_rate') && src.includes('main_net_inflow') && src.includes('main_net_inflow_pct'), 'market browse should normalize all market metric fields');
assert(src.includes("label: '换手率'") && src.includes("label: '主力净流入'") && src.includes("label: '主力净占比'"), 'market browse should render three sortable metric columns');
assert(src.includes("'换手率','主力净流入','主力净占比'"), 'market browse CSV should export the three metrics');
assert(src.includes("overflowX: 'auto'") && src.includes('minWidth:'), 'market browse table should remain usable with the detail panel open');
assert(src.includes('资金流：东方财富') && src.includes('换手率：东方财富/腾讯降级'), 'market browse should document field provenance');
```

- [ ] **Step 2: 运行契约并确认失败**

Run:

```powershell
node scripts/data_browse_contract_tests.mjs
```

Expected: FAIL，提示新增字段或列不存在。

- [ ] **Step 3: 扩展 `Stock` 类型和规范化逻辑**

```typescript
interface Stock {
  code: string;
  name: string;
  change_pct: number;
  volume: number;
  amount: number;
  price?: number;
  change?: number;
  amplitude?: number;
  turnover_rate?: number | null;
  main_net_inflow?: number | null;
  main_net_inflow_pct?: number | null;
  money_flow_source?: string | null;
  turnover_source?: string | null;
  latest_time?: string;
  source?: string;
  prev_close?: number;
  high?: number;
  low?: number;
}
```

规范化时使用“空值保持 `null`”的函数，不能用 `Number(value ?? 0)`：

```typescript
const optionalNumber = (value: unknown): number | null => {
  if (value === null || value === undefined || value === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
};
```

- [ ] **Step 4: 增加三列和显示规则**

在列定义中将三列放在振幅之后：

```typescript
{ label: '换手率', key: 'turnover_rate', align: 'right' },
{ label: '主力净流入', key: 'main_net_inflow', align: 'right' },
{ label: '主力净占比', key: 'main_net_inflow_pct', align: 'right' },
```

行渲染必须用 `value == null` 判断缺失。主力资金颜色复用 A 股正红负绿规则，真实零值显示 `0.00`。排序把 `null` 放到末尾，不把它转换为零：

```typescript
const compareNullableNumber = (a: number | null | undefined, b: number | null | undefined, direction: 'asc' | 'desc') => {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  return direction === 'desc' ? b - a : a - b;
};
```

- [ ] **Step 5: 更新 CSV、来源说明和横向滚动**

CSV 表头和行增加三项原始数值；缺失导出空字符串。表格外层使用 `overflowX: 'auto'`，表格设置足够容纳全部列的 `minWidth`。在 Top100 状态行增加：

```text
行情：TdxQuant 优先/新浪腾讯降级 · 资金流：东方财富 · 换手率：东方财富/腾讯降级
```

- [ ] **Step 6: 运行前端契约、类型检查和构建**

Run:

```powershell
node scripts/data_browse_contract_tests.mjs
npx tsc --noEmit
npm run build
```

Expected: 三条命令均退出码 0。

### Task 4: README 架构交接更新

**Files:**

- Modify: `README.md:89-110`

- [ ] **Step 1: 在 README 增加完整调用链**

在“工作区与关键调用链”加入：

```text
DbPanel 市场浏览
  -> POST /api/data { action: "stocks", limit: 100, sort_by: "amount" }
  -> server/router.mjs（只读白名单）
  -> server/routes/data.mjs（data-stocks PersistentRunner）
  -> scripts/data_runner.py::action_stocks
  -> scripts/market_data.py::fetch_realtime
       -> TdxQuant 主源 / 腾讯成交额补全 / 新浪腾讯降级
  -> 按成交额排序并截取 Top100
  -> scripts/market_data.py::fetch_stock_market_metrics
       -> 东方财富：换手率、主力净流入额、主力净流入占比
       -> 腾讯：仅在东方财富缺失时补换手率
  -> DbPanel 表格、前端排序和 CSV
```

- [ ] **Step 2: 写明维护边界**

README 同节增加字段表及以下约束：东方财富不接管行情主源或 Top100 排名；补充失败显示缺失且不阻断股票列表；不得在 React 或 Node 路由中直接请求外部行情源；不修改 SQLite schema；新增字段必须保持来源可追踪。

- [ ] **Step 3: 核对 README 与实现名称一致**

Run:

```powershell
rg -n "fetch_stock_market_metrics|main_net_inflow|turnover_rate|东方财富|腾讯" README.md scripts/market_data.py scripts/data_runner.py components/DbPanel.tsx
```

Expected: README 中的函数名、字段名和来源与代码一致，不出现旧项目名称。

### Task 5: 全链路验证与交付

**Files:**

- Verify only; no planned production edits.

- [ ] **Step 1: 运行聚焦回归**

```powershell
python -m pytest tests/test_market_money_flow.py scripts/data_source_chain_contract_tests.py -q
node scripts/data_browse_contract_tests.mjs
node scripts/data_browser_latency_contract_tests.mjs
```

Expected: 全部退出码 0。

- [ ] **Step 2: 运行完整 Python 与 Node 契约验证**

运行项目的完整 Python 测试、TypeScript 检查和 Vite 构建：

```powershell
python -m pytest -q
npx tsc --noEmit
npm run build
```

Expected: Pytest 无失败，TypeScript 和 Vite 构建退出码均为 0。

- [ ] **Step 3: 对运行 API 做只读验收**

```powershell
$body = @{ action='stocks'; limit=100; sort_by='amount'; force_refresh=$true } | ConvertTo-Json -Compress
$response = Invoke-RestMethod -Uri 'http://127.0.0.1:8880/api/data' -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 30
$response.data.stocks | Select-Object -First 5 code,name,amount,turnover_rate,main_net_inflow,main_net_inflow_pct,money_flow_source,turnover_source
```

Expected: 请求成功；新增字段存在；有效数据具有来源；`amount` 仍保持降序。若东方财富当时不可用，股票列表仍成功且新增字段为缺失。

- [ ] **Step 4: 浏览器布局验收**

打开 `http://127.0.0.1:8888`，进入“市场数据 → 数据浏览 → 市场浏览”，验证：

1. 三列可见并可排序。
2. 正负颜色、缺失和零值区分正确。
3. CSV 包含三列。
4. 点击股票打开逐笔详情后表格可以横向滚动，没有覆盖或不可点击内容。
5. 浏览器控制台无新增 error/warn。

- [ ] **Step 5: 最终差异复核**

确认实际修改文件只落在计划边界内；若出现额外文件，逐项说明原因。由于工作区没有 Git，使用文件清单和测试输出代替提交哈希作为交接证据。
