# Official Market Sentiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an official-source, auditable market-sentiment score to the global context and cockpit while keeping it shadow-only and unable to change trading policy or trigger orders.

**Architecture:** Create a focused Python sentiment module that owns source adapters, normalization, confidence, freshness, and caching. Integrate its output into `global_context`, copy it into the existing shadow-signal lane, and render a compact read-only summary in the cockpit. Existing hard risk rules and execution gates remain unchanged.

**Tech Stack:** Python 3 standard library, SQLite cache abstraction, pytest, React 19, TypeScript, Node source-contract tests, Vite.

**Workspace note:** The current directory is not a valid Git repository, so this plan intentionally omits commit steps and preserves all unrelated workspace changes.

---

### Task 1: Build the deterministic sentiment scoring core

**Files:**
- Create: `scripts/market_sentiment.py`
- Create: `tests/test_market_sentiment.py`

- [ ] **Step 1: Write failing score tests**

Add tests for interpolation, regime boundaries, partial coverage, stale
confidence, and the zero-confidence fallback:

```python
from scripts.market_sentiment import (
    score_market_sentiment,
    score_nfci,
    score_vix,
)


def test_vix_score_uses_defined_anchors_and_interpolation():
    assert score_vix(12) == 90
    assert score_vix(20) == 50
    assert score_vix(40) == 10
    assert score_vix(17.5) == 62.5


def test_nfci_score_uses_defined_anchors():
    assert score_nfci(-0.8) == 85
    assert score_nfci(0.0) == 50
    assert score_nfci(1.0) == 10


def test_partial_official_coverage_does_not_inflate_confidence():
    result = score_market_sentiment({
        "volatility": {"available": True, "score": 25, "weight": 50, "stale": False},
        "financial_conditions": {"available": False, "weight": 30},
        "futures_positioning": {"available": False, "weight": 20},
    })
    assert result["sentiment_score"] == 25
    assert result["sentiment_regime"] == "fear"
    assert result["confidence"] == 0.5


def test_stale_component_reduces_confidence():
    result = score_market_sentiment({
        "volatility": {"available": True, "score": 50, "weight": 50, "stale": True},
    })
    assert result["confidence"] == 0.25
    assert result["stale"] is True


def test_no_official_components_returns_neutral_zero_confidence():
    result = score_market_sentiment({})
    assert result["sentiment_score"] == 50
    assert result["sentiment_regime"] == "neutral"
    assert result["confidence"] == 0
    assert result["warnings"] == ["official_sources_unavailable"]
    assert result["mode"] == "shadow_only"
    assert result["can_change_trade_policy"] is False
    assert result["can_trigger_order"] is False
```

- [ ] **Step 2: Run the tests and confirm RED**

Run:

```powershell
python -m pytest tests/test_market_sentiment.py -q
```

Expected: collection fails because `scripts.market_sentiment` does not exist.

- [ ] **Step 3: Implement interpolation and score aggregation**

Create `scripts/market_sentiment.py` with:

```python
from __future__ import annotations

from datetime import datetime
from typing import Any

from quant.data.cache import create_cache


cache = create_cache()

VIX_ANCHORS = [(12.0, 90.0), (15.0, 75.0), (20.0, 50.0), (30.0, 25.0), (40.0, 10.0)]
NFCI_ANCHORS = [(-0.8, 85.0), (-0.3, 65.0), (0.0, 50.0), (0.5, 25.0), (1.0, 10.0)]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _interpolate(value: float, anchors: list[tuple[float, float]]) -> float:
    value = float(value)
    if value <= anchors[0][0]:
        return anchors[0][1]
    if value >= anchors[-1][0]:
        return anchors[-1][1]
    for (x0, y0), (x1, y1) in zip(anchors, anchors[1:]):
        if x0 <= value <= x1:
            ratio = (value - x0) / (x1 - x0)
            return round(y0 + ratio * (y1 - y0), 2)
    return 50.0


def score_vix(value: float) -> float:
    return _interpolate(value, VIX_ANCHORS)


def score_nfci(value: float) -> float:
    return _interpolate(value, NFCI_ANCHORS)


def _regime(score: float) -> str:
    if score <= 20:
        return "extreme_fear"
    if score <= 40:
        return "fear"
    if score < 60:
        return "neutral"
    if score < 80:
        return "greed"
    return "extreme_greed"


def score_market_sentiment(inputs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    available = [
        item for item in inputs.values()
        if item.get("available") and item.get("score") is not None
    ]
    if not available:
        return {
            "generated_at": _now(),
            "sentiment_score": 50.0,
            "sentiment_regime": "neutral",
            "confidence": 0.0,
            "mode": "shadow_only",
            "can_change_trade_policy": False,
            "can_trigger_order": False,
            "stale": False,
            "warnings": ["official_sources_unavailable"],
        }
    denominator = sum(float(item["weight"]) for item in available)
    score = sum(float(item["score"]) * float(item["weight"]) for item in available) / denominator
    confidence = sum(
        float(item["weight"]) * (0.5 if item.get("stale") else 1.0)
        for item in available
    ) / 100.0
    return {
        "generated_at": _now(),
        "sentiment_score": round(score, 2),
        "sentiment_regime": _regime(score),
        "confidence": round(confidence, 2),
        "mode": "shadow_only",
        "can_change_trade_policy": False,
        "can_trigger_order": False,
        "stale": any(bool(item.get("stale")) for item in available),
        "warnings": [],
    }
```

- [ ] **Step 4: Run the focused tests and confirm GREEN**

Run:

```powershell
python -m pytest tests/test_market_sentiment.py -q
```

Expected: all Task 1 tests pass.

---

### Task 2: Add official-source adapters and source provenance

**Files:**
- Modify: `scripts/market_sentiment.py`
- Modify: `tests/test_market_sentiment.py`

- [ ] **Step 1: Write failing adapter tests**

Use mocked standard-library HTTP responses. Add:

```python
import json
from datetime import datetime
from unittest.mock import patch

from scripts.market_sentiment import (
    fetch_cboe_vix,
    fetch_cffex_positioning,
    fetch_fred_nfci,
    fetch_hkex_activity,
)


def test_cboe_adapter_reads_latest_valid_close():
    csv_text = (
        "DATE,OPEN,HIGH,LOW,CLOSE\n"
        "07/15/2026,16.20,16.57,15.64,15.67\n"
        "07/16/2026,15.82,17.23,15.77,16.73\n"
    )
    with patch("scripts.market_sentiment._http_get_text", return_value=csv_text):
        out = fetch_cboe_vix()
    assert out["available"] is True
    assert out["value"] == 16.73
    assert out["as_of"] == "2026-07-16"
    assert out["official"] is True


def test_fred_without_key_is_unavailable():
    out = fetch_fred_nfci(api_key="")
    assert out["available"] is False
    assert out["reason"] == "FRED_API_KEY_not_configured"


def test_fred_adapter_reads_latest_numeric_observation():
    payload = {"observations": [{"date": "2026-07-03", "value": "-0.45"}]}
    with patch("scripts.market_sentiment._http_get_text", return_value=json.dumps(payload)):
        out = fetch_fred_nfci(api_key="test")
    assert out["available"] is True
    assert out["value"] == -0.45


def test_hkex_adapter_treats_northbound_as_activity_not_direction():
    js_text = '''
    tabData = [{
      "date":"2026-07-17",
      "market":"SSE Northbound",
      "tradingDay":1,
      "content":[{"style":1,"table":{
        "schema":[["Total Turnover","Total Trade Count","DQB","ETF Turnover"]],
        "tr":[
          {"td":[["181,148.72"]]},
          {"td":[["8,426,622"]]},
          {"td":[["999,999,999"]]},
          {"td":[["3,477.57"]]}
        ]
      }}]
    }];
    '''
    with patch("scripts.market_sentiment._http_get_text", return_value=js_text):
        out = fetch_hkex_activity(now=datetime(2026, 7, 17, 18, 0))
    assert out["available"] is True
    assert out["directional"] is False
    assert out["total_turnover"] == 181148.72
    assert "score" not in out


def test_cffex_requires_configured_authorized_endpoint():
    assert fetch_cffex_positioning(url="")["available"] is False
```

- [ ] **Step 2: Run the tests and confirm RED**

Run:

```powershell
python -m pytest tests/test_market_sentiment.py -q
```

Expected: imports fail because adapter functions do not exist.

- [ ] **Step 3: Implement bounded HTTP and adapters**

Add a `_http_get_text()` helper using `urllib.request`, eight-second timeout,
one retry, explicit user agent, and no secret-bearing diagnostics.

Implement:

```python
import csv
import io
import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

CBOE_VIX_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
HKEX_DAILY_URL = "https://www.hkex.com.hk/eng/csm/DailyStat/data_tab_daily_{date}e.js"


def _http_get_text(url: str) -> str:
    last_error = None
    for attempt in range(2):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "XuanJiQuant/market-sentiment"},
            )
            with urllib.request.urlopen(req, timeout=8) as response:
                return response.read().decode("utf-8", errors="replace")
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(0.5)
    raise RuntimeError(str(last_error)[:160])


def _number(value: Any) -> float:
    return float(str(value).replace(",", "").strip())


def fetch_cboe_vix() -> dict[str, Any]:
    try:
        rows = list(csv.DictReader(io.StringIO(_http_get_text(CBOE_VIX_URL))))
        for row in reversed(rows):
            close = row.get("CLOSE")
            date = row.get("DATE")
            if close in (None, "") or not date:
                continue
            as_of = datetime.strptime(date, "%m/%d/%Y").strftime("%Y-%m-%d")
            return {
                "source": "cboe",
                "series": "VIX",
                "official": True,
                "available": True,
                "value": _number(close),
                "as_of": as_of,
            }
        return {
            "source": "cboe",
            "official": True,
            "available": False,
            "reason": "no_valid_VIX_rows",
        }
    except Exception as exc:
        return {
            "source": "cboe",
            "official": True,
            "available": False,
            "reason": str(exc)[:160],
        }


def fetch_fred_nfci(api_key: str | None = None) -> dict[str, Any]:
    key = api_key if api_key is not None else os.getenv("FRED_API_KEY", "")
    if not key:
        return {
            "source": "fred",
            "series": "NFCI",
            "official": True,
            "available": False,
            "reason": "FRED_API_KEY_not_configured",
        }
    query = urllib.parse.urlencode({
        "series_id": "NFCI",
        "api_key": key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 4,
    })
    try:
        payload = json.loads(_http_get_text(f"{FRED_OBSERVATIONS_URL}?{query}"))
        for row in payload.get("observations") or []:
            if row.get("value") in (None, "", "."):
                continue
            return {
                "source": "fred",
                "series": "NFCI",
                "official": True,
                "available": True,
                "value": _number(row["value"]),
                "as_of": row.get("date"),
            }
        return {
            "source": "fred",
            "series": "NFCI",
            "official": True,
            "available": False,
            "reason": "no_valid_NFCI_observations",
        }
    except Exception as exc:
        return {
            "source": "fred",
            "series": "NFCI",
            "official": True,
            "available": False,
            "reason": str(exc)[:160],
        }


def fetch_hkex_activity(now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now()
    for offset in range(7):
        day = current - timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        try:
            text = _http_get_text(HKEX_DAILY_URL.format(date=day.strftime("%Y%m%d")))
            match = re.search(r"tabData\s*=\s*(\[.*\])\s*;?\s*$", text, re.S)
            if not match:
                continue
            rows = json.loads(match.group(1))
            totals = {
                "total_turnover": 0.0,
                "trade_count": 0.0,
                "daily_quota_balance": 0.0,
                "etf_turnover": 0.0,
            }
            found = False
            for market in rows:
                if market.get("market") not in {"SSE Northbound", "SZSE Northbound"}:
                    continue
                trading_table = next(
                    (
                        item.get("table") or {}
                        for item in market.get("content") or []
                        if item.get("style") == 1
                    ),
                    {},
                )
                schema_rows = trading_table.get("schema") or []
                names = schema_rows[0] if schema_rows else []
                values = []
                for row in trading_table.get("tr") or []:
                    cells = row.get("td") or []
                    values.append(cells[0][0] if cells and cells[0] else "")
                data = dict(zip(names, values))
                totals["total_turnover"] += _number(data.get("Total Turnover") or 0)
                totals["trade_count"] += _number(data.get("Total Trade Count") or 0)
                totals["daily_quota_balance"] += _number(data.get("DQB") or 0)
                totals["etf_turnover"] += _number(data.get("ETF Turnover") or 0)
                found = True
            if found:
                return {
                    "source": "hkex",
                    "official": True,
                    "available": True,
                    "directional": False,
                    "as_of": day.strftime("%Y-%m-%d"),
                    **totals,
                }
        except Exception:
            continue
    return {
        "source": "hkex",
        "official": True,
        "available": False,
        "directional": False,
        "reason": "no_recent_northbound_daily_record",
    }


def fetch_cffex_positioning(url: str | None = None) -> dict[str, Any]:
    endpoint = url if url is not None else os.getenv("CFFEX_MARKET_DATA_URL", "")
    if not endpoint:
        return {
            "source": "cffex",
            "official": True,
            "available": False,
            "reason": "CFFEX_MARKET_DATA_URL_not_configured",
        }
    required = {
        "contract",
        "trading_date",
        "close",
        "spot_close",
        "volume",
        "open_interest",
        "previous_open_interest",
    }
    try:
        payload = json.loads(_http_get_text(endpoint))
        record = payload[0] if isinstance(payload, list) and payload else payload
        if not isinstance(record, dict) or not required.issubset(record):
            return {
                "source": "cffex",
                "official": True,
                "available": False,
                "reason": "invalid_authorized_CFFEX_payload",
            }
        close = _number(record["close"])
        spot_close = _number(record["spot_close"])
        open_interest = _number(record["open_interest"])
        previous_open_interest = _number(record["previous_open_interest"])
        if spot_close <= 0 or previous_open_interest <= 0:
            raise ValueError("invalid CFFEX denominator")
        basis_pct = (close / spot_close - 1.0) * 100
        oi_change_pct = (open_interest / previous_open_interest - 1.0) * 100
        score = _interpolate(
            basis_pct,
            [(-2.0, 10.0), (-1.0, 25.0), (0.0, 50.0), (1.0, 75.0), (2.0, 90.0)],
        )
        if oi_change_pct > 5:
            score += 5 if score > 50 else -5
        return {
            "source": "cffex",
            "official": True,
            "available": True,
            "as_of": str(record["trading_date"]),
            "contract": str(record["contract"]),
            "basis_pct": round(basis_pct, 3),
            "oi_change_pct": round(oi_change_pct, 3),
            "volume": _number(record["volume"]),
            "score": round(max(0.0, min(100.0, score)), 2),
        }
    except Exception as exc:
        return {
            "source": "cffex",
            "official": True,
            "available": False,
            "reason": str(exc)[:160],
        }
```

Every adapter returns `source`, `official`, `available`, `as_of`, and either
validated values or a short `reason`.

- [ ] **Step 4: Add collection, freshness, cache, and provenance**

Implement `collect_market_sentiment()` and `get_market_sentiment_status()`:

```python
def collect_market_sentiment(*, now=None) -> dict[str, Any]:
    cboe = fetch_cboe_vix()
    fred = fetch_fred_nfci()
    hkex = fetch_hkex_activity(now=now)
    cffex = fetch_cffex_positioning()

    components = {
        "volatility": {
            **cboe,
            "weight": 50,
            "score": score_vix(cboe["value"]) if cboe.get("available") else None,
        },
        "financial_conditions": {
            **fred,
            "weight": 30,
            "score": score_nfci(fred["value"]) if fred.get("available") else None,
        },
        "futures_positioning": {**cffex, "weight": 20},
        "cross_border_activity": hkex,
    }
    result = score_market_sentiment(components)
    result["components"] = components
    result["sources"] = [
        {
            "source": item.get("source"),
            "official": bool(item.get("official")),
            "status": "stale" if item.get("stale") else (
                "live" if item.get("available") else "unavailable"
            ),
            "as_of": item.get("as_of"),
            "reason": item.get("reason"),
        }
        for item in (cboe, fred, hkex, cffex)
    ]
    cache.set("global:sentiment:latest", result)
    cache.set(f"global:sentiment:{datetime.now():%Y%m%d}", result)
    return result


def get_market_sentiment_status() -> dict[str, Any]:
    return cache.get("global:sentiment:latest") or score_market_sentiment({})
```

Use the previous cached component when a current fetch fails, mark it stale,
halve that component's confidence contribution, and add a source warning.

- [ ] **Step 5: Run focused tests**

Run:

```powershell
python -m pytest tests/test_market_sentiment.py -q
```

Expected: all scoring and adapter tests pass without live network access.

---

### Task 3: Integrate sentiment into global context and shadow signals

**Files:**
- Modify: `scripts/global_context.py`
- Modify: `quant/ai/shadow_signals.py`
- Modify: `scripts/global_context_source_contract_tests.py`
- Create: `tests/test_market_sentiment_integration.py`

- [ ] **Step 1: Write failing integration tests**

Add:

```python
from unittest.mock import patch


def test_global_context_adds_sentiment_without_changing_legacy_policy():
    from scripts import global_context

    sentiment = {
        "sentiment_score": 10,
        "sentiment_regime": "extreme_fear",
        "confidence": 1.0,
        "mode": "shadow_only",
        "can_change_trade_policy": False,
        "can_trigger_order": False,
    }
    with patch.object(global_context, "_fetch_tdx_indices", return_value={}), \
         patch.object(global_context, "_fetch_sina_indices", return_value={}), \
         patch.object(global_context, "_fetch_jin10_macro", return_value={"quotes": []}), \
         patch("scripts.market_data.fetch_sector_flow", return_value=[]), \
         patch("scripts.market_data.fetch_northbound", return_value={}), \
         patch("scripts.market_sentiment.collect_market_sentiment", return_value=sentiment):
        out = global_context.collect_global_context()
    assert out["sentiment"] == sentiment
    assert out["trade_policy"] == "normal"


def test_shadow_signals_include_sentiment_without_execution_authority():
    from quant.ai.shadow_signals import build_shadow_signals

    class Cache:
        def __init__(self):
            self.data = {
                "global:context:latest": {
                    "sentiment": {
                        "sentiment_score": 25,
                        "sentiment_regime": "fear",
                        "confidence": 0.5,
                        "sources": [{"source": "cboe", "status": "live"}],
                    }
                }
            }
        def get(self, key):
            return self.data.get(key)
        def set(self, key, value):
            self.data[key] = value

    out = build_shadow_signals(Cache(), source="unit")
    sentiment = next(item for item in out["signals"] if item["type"] == "market_sentiment")
    assert sentiment["value"] == 25
    assert out["can_change_trade_policy"] is False
    assert out["can_trigger_order"] is False
```

- [ ] **Step 2: Run the tests and confirm RED**

Run:

```powershell
python -m pytest tests/test_market_sentiment_integration.py -q
```

Expected: missing `sentiment` in global context and no market-sentiment shadow
signal.

- [ ] **Step 3: Add fail-closed global-context integration**

In `collect_global_context()`:

```python
try:
    from scripts.market_sentiment import collect_market_sentiment
    sentiment = collect_market_sentiment()
except Exception as exc:
    sentiment = {
        "sentiment_score": 50.0,
        "sentiment_regime": "neutral",
        "confidence": 0.0,
        "mode": "shadow_only",
        "can_change_trade_policy": False,
        "can_trigger_order": False,
        "warnings": [f"sentiment_unavailable:{str(exc)[:120]}"],
    }
```

Store it as `context["sentiment"]`. Do not reference it in the legacy
`risk_level` or `trade_policy` branches.

- [ ] **Step 4: Add the shadow signal**

In `build_shadow_signals()`:

```python
sentiment = global_ctx.get("sentiment") or {}
if sentiment:
    signals.append({
        "type": "market_sentiment",
        "signal": sentiment.get("sentiment_regime") or "neutral",
        "value": sentiment.get("sentiment_score", 50),
        "confidence": sentiment.get("confidence", 0),
        "sources": [
            item.get("source")
            for item in sentiment.get("sources") or []
            if item.get("status") in {"live", "stale"}
        ],
        "severity": "info",
    })
```

- [ ] **Step 5: Extend the existing source contract**

Patch `collect_market_sentiment()` in
`scripts/global_context_source_contract_tests.py`, assert it appears in the
returned context, and retain the existing TdxQuant-first assertions.

- [ ] **Step 6: Run integration and existing contracts**

Run:

```powershell
python -m pytest tests/test_market_sentiment_integration.py -q
python scripts/global_context_source_contract_tests.py
python scripts/verify_paper_rules.py
```

Expected: all commands pass and shadow flags remain false.

---

### Task 4: Display market sentiment in the cockpit

**Files:**
- Modify: `components/DashboardPanel.tsx`
- Create: `scripts/market_sentiment_frontend_contract_tests.mjs`

- [ ] **Step 1: Write the failing frontend contract**

Create:

```javascript
import fs from 'node:fs';
import assert from 'node:assert/strict';

const dashboard = fs.readFileSync('components/DashboardPanel.tsx', 'utf8');

for (const contract of [
  'global?.sentiment',
  '市场情绪',
  '情绪置信度',
  '官方来源',
  'sentiment_score',
  'sentiment_regime',
  'confidence',
]) {
  assert(dashboard.includes(contract), `cockpit must render ${contract}`);
}

assert(
  !dashboard.includes('sentiment.trade_policy') &&
    !dashboard.includes('sentiment.trade_allowed'),
  'cockpit sentiment must remain read-only and separate from execution policy',
);

console.log('market sentiment frontend contract tests passed');
```

- [ ] **Step 2: Run the contract and confirm RED**

Run:

```powershell
node scripts/market_sentiment_frontend_contract_tests.mjs
```

Expected: failure on the first missing sentiment contract.

- [ ] **Step 3: Add compact read-only rendering**

In `DashboardPanel`, derive:

```tsx
const sentiment = global?.sentiment;
const sentimentLabels: Record<string, string> = {
  extreme_fear: '极度谨慎',
  fear: '谨慎',
  neutral: '中性',
  greed: '积极',
  extreme_greed: '过热',
};
const sentimentScore = Number(sentiment?.sentiment_score ?? 50);
const sentimentConfidence = Number(sentiment?.confidence ?? 0) * 100;
const sentimentSources = (sentiment?.sources || [])
  .filter((source: any) => source?.status === 'live' || source?.status === 'stale');
```

Inside `全球实时动态`, add a compact band below risk level and trade policy:

```tsx
{sentiment && (
  <div style={{ marginTop: 8, padding: 9, background: '#0B0F1A', borderRadius: 6 }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap' }}>
      <div>
        <div style={{ fontSize: 9, color: '#64748B' }}>市场情绪</div>
        <div style={{ fontSize: 13, color: '#E2E8F0', fontWeight: 700 }}>
          {sentimentLabels[sentiment.sentiment_regime] || '中性'} · {sentimentScore.toFixed(1)}
        </div>
      </div>
      <div>
        <div style={{ fontSize: 9, color: '#64748B' }}>情绪置信度</div>
        <div style={{ fontSize: 13, color: '#38BDF8', fontWeight: 700 }}>
          {sentimentConfidence.toFixed(0)}%
        </div>
      </div>
    </div>
    <div style={{ fontSize: 9, color: '#64748B', marginTop: 6 }}>
      官方来源: {sentimentSources.map((source: any) => source.source).join(' · ') || '暂无可用数据'}
    </div>
    {sentiment.stale && (
      <div style={{ fontSize: 9, color: '#FBBF24', marginTop: 4 }}>
        情绪数据包含过期缓存
      </div>
    )}
  </div>
)}
```

Do not add settings, refresh actions, or references from sentiment to
`trade_policy`.

- [ ] **Step 4: Run frontend contracts**

Run:

```powershell
node scripts/market_sentiment_frontend_contract_tests.mjs
node scripts/control_surface_layout_contract_tests.mjs
```

Expected: both pass.

---

### Task 5: Document credentials, provenance, and safety

**Files:**
- Modify: `.env.example`
- Modify: `README.md`

- [ ] **Step 1: Add optional official-source configuration**

Add:

```dotenv
# Official market sentiment sources
FRED_API_KEY=
CFFEX_MARKET_DATA_URL=
```

Do not add real credentials or an undocumented default CFFEX endpoint.

- [ ] **Step 2: Update README**

Document:

```markdown
### 市场风险与市场情绪

- `risk_level` 是现有硬风险状态，可影响 `trade_policy`
- `sentiment_score` 是 0-100 的官方数据影子评分，50 为中性
- 情绪评分不能直接触发订单、放宽风控或改变交易权限
- Cboe VIX 为默认官方来源
- FRED NFCI 需要 `FRED_API_KEY`
- HKEX Northbound 仅作为官方交易活跃度上下文，不推断净流入
- CFFEX 只接受 `CFFEX_MARKET_DATA_URL` 指向的授权数据接口
- 数据缺失返回中性、零置信度，并保留来源和新鲜度审计
```

Add cache keys:

```text
global:sentiment:latest
global:sentiment:<YYYYMMDD>
```

- [ ] **Step 3: Run documentation/source contracts**

Run:

```powershell
node scripts/market_sentiment_frontend_contract_tests.mjs
rg -n "sentiment_score|FRED_API_KEY|CFFEX_MARKET_DATA_URL|shadow" README.md .env.example
```

Expected: all required configuration and safety terms are present.

---

### Task 6: Full verification

**Files:**
- Verify: `scripts/market_sentiment.py`
- Verify: `scripts/global_context.py`
- Verify: `quant/ai/shadow_signals.py`
- Verify: `components/DashboardPanel.tsx`
- Verify: `README.md`

- [ ] **Step 1: Run focused tests**

```powershell
python -m pytest tests/test_market_sentiment.py tests/test_market_sentiment_integration.py -q
python scripts/global_context_source_contract_tests.py
node scripts/market_sentiment_frontend_contract_tests.mjs
```

- [ ] **Step 2: Run trading-boundary regressions**

```powershell
python scripts/verify_paper_rules.py
python -m pytest tests/test_ai_verifier.py tests/test_risk_gateway.py -q
node scripts/control_surface_layout_contract_tests.mjs
node scripts/paper_screen_realtime_contract_tests.mjs
```

- [ ] **Step 3: Run production build**

```powershell
npm run build
```

Expected: build exits zero. Record, but do not treat, the existing chunk-size
warning as a sentiment regression.

- [ ] **Step 4: Run live read-only collection**

```powershell
python scripts/market_sentiment.py --run
```

Verify:

- Cboe is live or explicitly unavailable.
- FRED and CFFEX are unavailable when optional configuration is absent.
- HKEX activity does not expose a directional score.
- Output always contains shadow-only flags.
- No API key appears in output.

- [ ] **Step 5: Browser validation**

The flow under test is:

```text
open cockpit -> inspect global market card -> verify sentiment score,
confidence, official sources, and stale state -> resize to narrow desktop
```

Verify at 1280x720 and 1024x900:

- no horizontal overflow
- no overlap in the global market card
- risk level and trade policy remain visually separate from market sentiment
- official-source text wraps cleanly
- no framework overlay
- no relevant browser console warnings or errors

Open and close the scheduling drawer for interaction proof. Do not save
configuration, run the scheduler, run an AI loop, or submit a paper trade.
