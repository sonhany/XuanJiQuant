from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

import pandas as pd

from quant.backtest.engine import BacktestSimulator


ASHARE_BACKTEST_V1 = {
    "version": "ashare_backtest_v1",
    "initial_cash": 100_000_000.0,
    "commission_rate": 0.0003,
    "min_commission": 5.0,
    "stamp_tax_rate": 0.001,
    "transfer_fee_rate": 0.00001,
    "slippage_rate": 0.0001,
    "position_size_pct": 0.95,
    "allow_short": False,
    "enforce_limit": True,
    "max_volume_pct": 0.10,
    "enforce_t1": True,
}


def _pure_code(instrument: str) -> str:
    text = str(instrument).upper().strip()
    if text.startswith(("SH", "SZ", "BJ")):
        text = text[2:]
    return text.split(".")[-1].zfill(6)


def build_signal_bundle(
    prediction: pd.Series,
    workflow_run_id: str,
    dataset_version: str,
    *,
    topk: int,
    n_drop: int,
    excluded_instruments: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(prediction.index, pd.MultiIndex):
        raise ValueError("Qlib prediction must use a datetime/instrument MultiIndex")
    if "datetime" not in prediction.index.names or "instrument" not in prediction.index.names:
        raise ValueError("Qlib prediction index must contain datetime and instrument")
    topk_value = max(1, int(topk))
    drop_value = max(0, int(n_drop))
    frame = prediction.rename("score").reset_index()
    excluded = {str(value).upper().strip() for value in (excluded_instruments or set())}
    if excluded:
        frame = frame[~frame["instrument"].astype(str).str.upper().str.strip().isin(excluded)]
    frame["datetime"] = pd.to_datetime(frame["datetime"], errors="coerce")
    frame["score"] = pd.to_numeric(frame["score"], errors="coerce")
    if frame[["datetime", "score"]].isna().any().any():
        raise ValueError("Qlib prediction contains invalid datetime or score")

    current: set[str] = set()
    records: list[dict[str, Any]] = []
    for trade_date, group in frame.groupby("datetime", sort=True):
        scores = {
            str(row.instrument): float(row.score)
            for row in group.itertuples(index=False)
        }
        ranked = sorted(scores, key=lambda item: (-scores[item], item))
        desired = set(ranked[:topk_value])
        leaving = sorted(
            current - desired,
            key=lambda item: (scores.get(item, float("-inf")), item),
        )[:drop_value]
        target = current - set(leaving)
        entrants = [item for item in ranked if item in desired and item not in target]
        target.update(entrants[: max(0, topk_value - len(target))])
        day = pd.Timestamp(trade_date).strftime("%Y-%m-%d")
        for instrument in sorted(scores):
            signal = 0
            if instrument in target and instrument not in current:
                signal = 1
            elif instrument in current and instrument not in target:
                signal = -1
            if signal != 0:
                records.append(
                    {
                        "date": day,
                        "instrument": _pure_code(instrument),
                        "score": scores[instrument],
                        "signal": signal,
                    }
                )
        current = target

    identity = {
        "workflow_run_id": str(workflow_run_id),
        "dataset_version": str(dataset_version),
        "topk": topk_value,
        "n_drop": drop_value,
        "excluded_instruments": sorted(excluded),
        "records": records,
    }
    signal_hash = hashlib.sha256(
        json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    signals: dict[str, list[dict[str, Any]]] = {}
    for row in records:
        signals.setdefault(row["instrument"], []).append(
            {key: row[key] for key in ("date", "score", "signal")}
        )
    return {
        "workflow_run_id": str(workflow_run_id),
        "dataset_version": str(dataset_version),
        "topk": topk_value,
        "n_drop": drop_value,
        "signal_hash": signal_hash,
        "signals": signals,
    }


def _validate_klines(
    klines: dict[str, pd.DataFrame],
    signal_codes: set[str],
) -> None:
    required = ("date", "open", "high", "low", "close", "amount")
    for code in sorted(signal_codes):
        frame = klines.get(code)
        if frame is None or frame.empty:
            raise ValueError(f"missing test-window prices for {code}")
        missing = [column for column in required if column not in frame.columns]
        if missing:
            raise ValueError(f"missing columns: {', '.join(missing)}")
        numeric = frame[list(required[1:])].apply(pd.to_numeric, errors="coerce")
        if numeric.isna().any().any():
            raise ValueError(f"invalid OHLC/amount values for {code}")
        if (numeric[["open", "high", "low", "close"]] <= 0).any().any():
            raise ValueError(f"non-positive test-window prices for {code}")


def run_ashare_backtest(
    *,
    signal_bundle: dict[str, Any],
    klines: dict[str, pd.DataFrame],
    config: dict[str, Any] = ASHARE_BACKTEST_V1,
    simulator_factory: Callable[..., Any] = BacktestSimulator,
) -> dict[str, Any]:
    signals = dict(signal_bundle.get("signals") or {})
    _validate_klines(klines, set(signals))
    runtime_config = dict(config)
    version = str(runtime_config.pop("version", ""))
    if not version:
        raise ValueError("A-share backtest config version is required")
    simulator = simulator_factory(**runtime_config)
    simulator.add_signals(signals)
    simulator.add_klines(klines)
    result = dict(simulator.run())
    result.update(
        {
            "engine": "xuanji_ashare",
            "signal_hash": signal_bundle["signal_hash"],
            "config_version": version,
        }
    )
    return result
