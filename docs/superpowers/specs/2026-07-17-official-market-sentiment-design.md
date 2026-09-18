# Official Market Sentiment Design

## Status

Approved direction: introduce official-source market sentiment as an
independent, shadow-only signal. Preserve the existing hard risk gateway and
do not allow the new score to trigger orders or relax trading restrictions.

## Goal

Add an auditable market-sentiment layer to the global context pipeline using
official or explicitly licensed sources. Display the result in the cockpit
with source provenance, freshness, and confidence.

## Approaches Considered

### A. Replace the current risk rules immediately

Use the new sentiment score to produce `normal`, `reduce_only`, and
`no_new_position`.

Rejected for the first phase because the new series has no local calibration
history and an official-source outage could alter trading behavior.

### B. Shadow-first official sentiment layer

Keep the current `risk_level` and `trade_policy` path unchanged. Add a separate
sentiment engine, cache its output, expose it to the cockpit, and pass it to the
existing shadow-signals lane.

Selected because it provides observable production data without granting the
new signal execution authority.

### C. Display official raw data without a composite score

Show VIX, Stock Connect activity, financial conditions, and futures data
without normalization.

Rejected because operators would still need to interpret incompatible units
and could not compare regimes consistently.

## Safety Boundary

The first phase must satisfy all of the following:

- `sentiment_score` cannot change `trade_policy`.
- `sentiment_score` cannot set `trade_allowed`.
- `sentiment_score` cannot create, remove, or resize an order.
- Missing official data produces neutral sentiment with zero confidence, not
  a bullish or low-risk result.
- Stale official data remains visible with a stale marker and reduced
  confidence.
- The existing verifier, risk gateway, T+1, position, exposure, turnover, and
  kill-switch rules remain unchanged.
- Unofficial Eastmoney and Sina signals may remain in the legacy global context
  but do not count as official sentiment evidence.

## Architecture

### `scripts/market_sentiment.py`

Owns official-source acquisition, normalization, scoring, freshness,
provenance, and caching.

Public function contracts:

- `collect_market_sentiment(*, now=None) -> dict`
- `score_market_sentiment(inputs: dict) -> dict`
- `get_market_sentiment_status() -> dict`

The module must not import the trading executor, order router, risk gateway, or
LLM client.

### `scripts/global_context.py`

Calls `collect_market_sentiment()` after legacy global quotes are collected.
The returned object is stored under:

```python
context["sentiment"] = sentiment
```

The existing `risk_level`, `risk_signals`, and `trade_policy` calculation stays
unchanged in the first phase.

### `quant/ai/shadow_signals.py`

Copies the sentiment regime, score, confidence, and source summary into the
existing shadow lane. It must keep:

```python
"can_change_trade_policy": False
"can_trigger_order": False
```

### `components/DashboardPanel.tsx`

The existing `全球实时动态` card gains a compact market-sentiment section:

- sentiment regime
- score from 0 to 100
- confidence percentage
- official source badges
- freshness or stale warning

No new settings or action buttons are added.

## Official Source Adapters

### Cboe VIX

Use the official Cboe daily VIX CSV:

```text
https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv
```

The adapter reads the newest valid row and records:

```python
{
    "source": "cboe",
    "series": "VIX",
    "value": close,
    "as_of": date,
    "official": True,
}
```

### FRED financial conditions

When `FRED_API_KEY` is configured, use the official FRED observations API for
`NFCI`. The adapter is optional and must fail closed to an unavailable source
record when the key or network is unavailable.

### HKEX Stock Connect

Use the official HKEX daily-statistics resource pattern published by the HKEX
Historical Daily page:

```text
/eng/csm/DailyStat/data_tab_daily_[YYYY][MM][DD]e.js
```

The adapter checks a bounded number of recent weekdays and parses the currently
published Northbound total turnover, trade count, daily quota balance, and ETF
turnover fields. Current Northbound daily statistics do not expose directional
buy and sell turnover, so HKEX is an official activity context source and does
not contribute a bullish or bearish component score. It must not infer the
discontinued legacy real-time net-flow definition.

### CFFEX index futures

Do not scrape the CFFEX website with undocumented selectors. Support an
official or licensed JSON endpoint configured through:

```text
CFFEX_MARKET_DATA_URL
```

When configured, accept only records containing contract, trading date, close,
spot close, volume, open interest, and previous open interest. Calculate the
futures basis and open-interest change locally; do not trust a provider-supplied
sentiment label. Until an authorized endpoint is configured, report this source
as unavailable and exclude it from confidence.

## Sentiment Semantics

`sentiment_score` uses a stable direction:

```text
0   = extreme risk-off / fear
50  = neutral
100 = extreme risk-on / greed
```

Regimes:

| Score | Regime |
|---:|---|
| 0-20 | `extreme_fear` |
| 21-40 | `fear` |
| 41-59 | `neutral` |
| 60-79 | `greed` |
| 80-100 | `extreme_greed` |

The first-phase weighted model:

| Component | Available source | Weight |
|---|---|---:|
| Volatility | Cboe VIX | 50 |
| Financial conditions | FRED NFCI | 30 |
| Index-futures positioning | Authorized CFFEX feed | 20 |

Unavailable components are removed from the weighted denominator. Confidence
is the sum of available component weights divided by 100, reduced by freshness.
HKEX activity is displayed as official context but does not add confidence to
the directional sentiment score.

### Component normalization

Cboe VIX:

| VIX | Component score |
|---:|---:|
| <= 12 | 90 |
| 15 | 75 |
| 20 | 50 |
| 30 | 25 |
| >= 40 | 10 |

Values between anchors use linear interpolation.

HKEX Northbound activity:

The adapter reports total turnover, trade count, quota balance, and ETF
turnover. These values are not mapped to a directional component score because
the official Northbound daily record does not contain buy/sell turnover.

FRED NFCI:

| NFCI | Component score |
|---:|---:|
| <= -0.8 | 85 |
| -0.3 | 65 |
| 0.0 | 50 |
| 0.5 | 25 |
| >= 1.0 | 10 |

CFFEX:

The first phase scores only validated CSI 300 futures basis and open-interest
change supplied by the authorized endpoint:

```text
basis_pct = (futures_close / spot_close - 1) * 100
```

Basis anchors are `-2% -> 10`, `-1% -> 25`, `0% -> 50`, `1% -> 75`,
and `2% -> 90`, with linear interpolation. When open interest rises more than
5%, move the score five points farther away from neutral to confirm the basis
direction. Without valid close, spot close, current open interest, and previous
open interest, the component is unavailable rather than guessed.

## Output Contract

```python
{
    "generated_at": "YYYY-MM-DD HH:MM:SS",
    "sentiment_score": 0.0,
    "sentiment_regime": "neutral",
    "confidence": 0.0,
    "mode": "shadow_only",
    "can_change_trade_policy": False,
    "can_trigger_order": False,
    "components": {
        "volatility": {"available": True, "score": 50, "weight": 50},
        "cross_border_activity": {"available": True, "directional": False},
        "financial_conditions": {"available": False, "weight": 30},
        "futures_positioning": {"available": False, "weight": 20},
    },
    "sources": [
        {
            "source": "cboe",
            "official": True,
            "status": "live|stale|unavailable",
            "as_of": "YYYY-MM-DD",
        }
    ],
    "stale": False,
    "warnings": [],
}
```

Cache keys:

```text
global:sentiment:latest
global:sentiment:<YYYYMMDD>
```

## Freshness And Failure Handling

- Cboe VIX and HKEX daily data are fresh through the latest completed trading
  day.
- FRED NFCI is weekly and remains valid for ten calendar days.
- CFFEX freshness comes from the authorized record trading date.
- Network fetches use short timeouts and bounded retries.
- A fetch failure may reuse the latest cached source value, marked `stale`.
- If no official component is available, return score `50`, regime `neutral`,
  confidence `0`, and warning `official_sources_unavailable`.
- Source errors are truncated and stored as diagnostics; secrets and API keys
  are never returned.

## Testing

### Unit tests

- VIX interpolation at anchors and between anchors.
- HKEX buy-ratio normalization.
- Weighted score with all, partial, and no components.
- Confidence reduction for stale data.
- Neutral zero-confidence fallback.
- Output contract always preserves shadow-only flags.

### Adapter tests

Use mocked HTTP responses for Cboe, FRED, HKEX, and configured CFFEX data. Tests
must not require live internet access.

### Integration tests

- `global_context` includes `sentiment` without changing legacy risk policy.
- `shadow_signals` includes sentiment and still cannot change policy or trigger
  orders.
- Cockpit contract requires score, regime, confidence, provenance, and stale
  state.

### Verification

Run focused Python tests, existing global-context contracts, control-surface
contracts, production build, and desktop/narrow browser validation. Browser
validation must not save configuration, run the scheduler, or submit a paper
trade.

## Documentation

Update `README.md` to explain:

- the difference between hard `risk_level` and shadow `sentiment_score`
- official source priority and optional credentials
- cache keys and freshness rules
- the fact that sentiment cannot directly trigger trading
