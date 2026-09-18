"""Train the fixed three-state market regime model in the Qlib environment."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quant.qlib.paths import DEFAULT_DATA_ROOT, resolve_data_path
from quant.qlib.regime_model import REGIME_FEATURES, train_regime_model


Progress = Callable[[float, str], None]
DATASET_ID = "a_share_6y_daily"
RANDOM_STATE = 7


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def build_market_regime_frame(raw_dir: Path) -> pd.DataFrame:
    root = Path(raw_dir)
    files = sorted(root.glob("*.json"))
    if not files:
        raise RuntimeError(f"regime source dataset is empty: {root}")
    daily_returns: list[pd.DataFrame] = []
    for path in files:
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"invalid regime source file: {path.name}") from exc
        if not isinstance(rows, list):
            raise RuntimeError(f"invalid regime source rows: {path.name}")
        records = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            close = _finite_number(row.get("close"))
            if close is None or close <= 0:
                continue
            if int(row.get("tradable", 1) or 0) != 1:
                continue
            if int(row.get("listed", 1) or 0) != 1:
                continue
            if int(row.get("delisted", 0) or 0) != 0:
                continue
            records.append(
                {
                    "datetime": row.get("datetime"),
                    "close": close,
                }
            )
        if len(records) < 2:
            continue
        symbol = pd.DataFrame(records)
        symbol["datetime"] = pd.to_datetime(
            symbol["datetime"],
            errors="coerce",
        )
        symbol = (
            symbol.dropna(subset=["datetime"])
            .drop_duplicates("datetime", keep="last")
            .sort_values("datetime")
        )
        symbol["daily_return"] = symbol["close"].pct_change(fill_method=None)
        symbol.loc[
            symbol["daily_return"].abs() > 0.25,
            "daily_return",
        ] = np.nan
        daily_returns.append(
            symbol.loc[:, ["datetime", "daily_return"]].dropna()
        )
    if not daily_returns:
        raise RuntimeError("regime source dataset has no usable return series")

    panel = pd.concat(daily_returns, ignore_index=True)
    grouped = panel.groupby("datetime", sort=True)["daily_return"]
    market = pd.DataFrame(
        {
            "market_return": grouped.median(),
            "breadth": grouped.apply(
                lambda values: float((values > 0).mean())
            ),
        }
    )
    market = market.sort_index()
    market_level = (1.0 + market["market_return"]).cumprod()
    frame = pd.DataFrame(
        {
            "ret_20": market_level.pct_change(20, fill_method=None),
            "realized_vol_20": (
                market["market_return"].rolling(20).std(ddof=0)
                * math.sqrt(252.0)
            ),
            "breadth": market["breadth"].rolling(5).mean(),
        },
        index=market.index,
    )
    frame = frame.loc[:, list(REGIME_FEATURES)].dropna()
    if not np.isfinite(frame.to_numpy(dtype=float)).all():
        raise RuntimeError("regime feature construction produced non-finite data")
    if not frame.index.is_monotonic_increasing or not frame.index.is_unique:
        raise RuntimeError("regime feature rows are not uniquely time-ordered")
    return frame


def train_latest_regime(
    progress: Progress | None = None,
) -> dict[str, Any]:
    report = progress or (lambda *_: None)
    raw_dir = resolve_data_path("datasets", DATASET_ID, "raw")
    output_path = (
        Path(DEFAULT_DATA_ROOT)
        / "models"
        / "regime"
        / "regime-latest.joblib"
    )
    report(0.05, "Loading fixed six-year market dataset")
    frame = build_market_regime_frame(raw_dir)
    report(0.35, f"Training three-state HMM on {len(frame)} rows")
    result = train_regime_model(
        frame,
        feature_names=list(REGIME_FEATURES),
        output_path=output_path,
        random_state=RANDOM_STATE,
    )
    report(1.0, "Regime model trained and atomically published")
    return result


def main() -> int:
    result = train_latest_regime(
        lambda value, message: print(
            f"[{value:.1%}] {message}",
            file=sys.stderr,
            flush=True,
        )
    )
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
