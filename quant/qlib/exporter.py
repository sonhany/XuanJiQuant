from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import pandas as pd


BASE_FIELDS = [
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "factor",
    "vwap",
    "tradable",
    "is_st",
    "st_unknown",
    "listed",
    "delisted",
    "paused",
    "limit_up",
    "limit_down",
]


def benchmark_reference_rows(
    payload: dict,
    *,
    expected_dataset_version: str,
) -> list[dict]:
    """Convert the governed CSI 300 reference into one native Qlib instrument."""

    if (
        not isinstance(payload, dict)
        or payload.get("status") != "passed"
        or str(payload.get("code") or "") != "000300"
        or str(payload.get("dataset_version") or "") != str(expected_dataset_version)
        or payload.get("research_only") is not True
        or payload.get("execution_authority") is not False
    ):
        raise ValueError("benchmark reference identity or authority mismatch")
    bars = payload.get("bars")
    if not isinstance(bars, list) or not bars:
        raise ValueError("benchmark reference has no bars")
    rows: list[dict] = []
    seen_dates: set[str] = set()
    for bar in bars:
        if not isinstance(bar, dict):
            raise ValueError("benchmark reference contains malformed bars")
        trade_date = str(bar.get("date") or bar.get("datetime") or "")[:10]
        if not trade_date or trade_date in seen_dates:
            raise ValueError("benchmark reference contains invalid or duplicate dates")
        required = {}
        for field in ("open", "high", "low", "close"):
            try:
                value = float(bar.get(field))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"benchmark reference missing numeric {field}") from exc
            if not np.isfinite(value):
                raise ValueError(f"benchmark reference has non-finite {field}")
            required[field] = value
        seen_dates.add(trade_date)
        rows.append(
            {
                "instrument": "SH000300",
                "datetime": trade_date,
                **required,
                "volume": float(bar.get("volume") or 0.0),
                "amount": float(bar.get("amount") or 0.0),
                "factor": 1.0,
                "tradable": 1,
                "listed": 1,
            }
        )
    return rows


def _normalize_export_frame(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    data["instrument"] = data["instrument"].astype(str).str.upper()
    data["datetime"] = pd.to_datetime(data["datetime"], errors="coerce")
    if data["datetime"].isna().any():
        raise ValueError("invalid datetime rows")
    data = data.sort_values(["instrument", "datetime"])
    if data.duplicated(["instrument", "datetime"]).any():
        raise ValueError("duplicate instrument/datetime rows")
    factor_values = (
        data["factor"]
        if "factor" in data.columns
        else pd.Series(1.0, index=data.index)
    )
    volume_values = (
        data["volume"]
        if "volume" in data.columns
        else pd.Series(0.0, index=data.index)
    )
    amount_values = (
        data["amount"]
        if "amount" in data.columns
        else pd.Series(0.0, index=data.index)
    )
    data["factor"] = pd.to_numeric(factor_values, errors="coerce").fillna(1.0)
    volume = pd.to_numeric(volume_values, errors="coerce").replace(0, np.nan)
    amount = pd.to_numeric(amount_values, errors="coerce")
    data["vwap"] = (amount / volume).replace([np.inf, -np.inf], np.nan)
    for field in BASE_FIELDS:
        if field not in data.columns:
            data[field] = 1.0 if field in {"factor", "tradable", "listed"} else 0.0
    return data


def write_qlib_bin(frame: pd.DataFrame, target_dir: Path) -> dict:
    target_dir = Path(target_dir)
    calendars_dir = target_dir / "calendars"
    instruments_dir = target_dir / "instruments"
    features_dir = target_dir / "features"
    calendars_dir.mkdir(parents=True, exist_ok=True)
    instruments_dir.mkdir(parents=True, exist_ok=True)
    features_dir.mkdir(parents=True, exist_ok=True)

    data = _normalize_export_frame(frame)

    calendar = pd.DatetimeIndex(sorted(data["datetime"].unique()))
    calendar_lookup = {value: index for index, value in enumerate(calendar)}
    (calendars_dir / "day.txt").write_text(
        "\n".join(value.strftime("%Y-%m-%d") for value in calendar) + "\n",
        encoding="utf-8",
    )

    instrument_lines = []
    written_files = 0
    for instrument, group in data.groupby("instrument", sort=True):
        group = group.sort_values("datetime")
        start_date = group["datetime"].iloc[0]
        end_date = group["datetime"].iloc[-1]
        start_index = calendar_lookup[start_date]
        end_index = calendar_lookup[end_date]
        aligned = group.set_index("datetime").reindex(calendar[start_index : end_index + 1])
        instrument_lines.append(
            f"{instrument}\t{start_date:%Y-%m-%d}\t{end_date:%Y-%m-%d}"
        )
        instrument_dir = features_dir / instrument.lower()
        instrument_dir.mkdir(parents=True, exist_ok=True)
        for field in BASE_FIELDS:
            values = pd.to_numeric(aligned[field], errors="coerce").to_numpy(
                dtype="<f4"
            )
            payload = np.hstack(
                [np.asarray([start_index], dtype="<f4"), values]
            ).astype("<f4")
            payload.tofile(instrument_dir / f"{field}.day.bin")
            written_files += 1

    (instruments_dir / "all.txt").write_text(
        "\n".join(instrument_lines) + "\n",
        encoding="utf-8",
    )
    return {
        "calendar_days": len(calendar),
        "instruments": len(instrument_lines),
        "feature_files": written_files,
        "target_dir": str(target_dir.resolve()),
    }


def write_qlib_bin_from_json_files(
    paths: Iterable[Path],
    target_dir: Path,
    *,
    progress: Callable[[int, int], None] | None = None,
    universe_exclusions: set[str] | None = None,
) -> dict:
    """Write native Qlib files with bounded memory using one symbol at a time."""
    files = [Path(path) for path in paths]
    if not files:
        raise ValueError("no JSON files to export")
    calendar_values: set[pd.Timestamp] = set()
    file_instruments: dict[Path, str] = {}
    seen_instruments: set[str] = set()
    for path in files:
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list) or not rows:
            continue
        frame = pd.DataFrame(rows)
        if "instrument" not in frame.columns or "datetime" not in frame.columns:
            raise ValueError(f"missing export identity columns: {path.name}")
        instruments = sorted(frame["instrument"].astype(str).str.upper().unique())
        if len(instruments) != 1:
            raise ValueError(f"raw file must contain one instrument: {path.name}")
        instrument = instruments[0]
        if instrument in seen_instruments:
            raise ValueError(f"instrument appears in multiple raw files: {instrument}")
        dates = pd.to_datetime(frame["datetime"], errors="coerce")
        if dates.isna().any() or frame.assign(datetime=dates).duplicated(
            ["instrument", "datetime"]
        ).any():
            raise ValueError(f"invalid or duplicate export rows: {path.name}")
        seen_instruments.add(instrument)
        file_instruments[path] = instrument
        calendar_values.update(pd.Timestamp(value) for value in dates.unique())
    if not calendar_values:
        raise ValueError("JSON files contain no export rows")

    target = Path(target_dir)
    calendars_dir = target / "calendars"
    instruments_dir = target / "instruments"
    features_dir = target / "features"
    calendars_dir.mkdir(parents=True, exist_ok=True)
    instruments_dir.mkdir(parents=True, exist_ok=True)
    features_dir.mkdir(parents=True, exist_ok=True)
    calendar = pd.DatetimeIndex(sorted(calendar_values))
    calendar_lookup = {value: index for index, value in enumerate(calendar)}
    (calendars_dir / "day.txt").write_text(
        "\n".join(value.strftime("%Y-%m-%d") for value in calendar) + "\n",
        encoding="utf-8",
    )

    excluded = {str(value).upper() for value in (universe_exclusions or set())}
    provider_instrument_lines: list[str] = []
    market_instrument_lines: list[str] = []
    written_files = 0
    export_files = sorted(file_instruments, key=lambda path: file_instruments[path])
    for index, path in enumerate(export_files, start=1):
        data = _normalize_export_frame(
            pd.DataFrame(json.loads(path.read_text(encoding="utf-8")))
        )
        instrument = file_instruments[path]
        group = data[data["instrument"] == instrument].sort_values("datetime")
        start_date = group["datetime"].iloc[0]
        end_date = group["datetime"].iloc[-1]
        start_index = calendar_lookup[start_date]
        end_index = calendar_lookup[end_date]
        aligned = group.set_index("datetime").reindex(calendar[start_index : end_index + 1])
        instrument_line = f"{instrument}\t{start_date:%Y-%m-%d}\t{end_date:%Y-%m-%d}"
        provider_instrument_lines.append(instrument_line)
        if instrument not in excluded:
            market_instrument_lines.append(instrument_line)
        instrument_dir = features_dir / instrument.lower()
        instrument_dir.mkdir(parents=True, exist_ok=True)
        for field in BASE_FIELDS:
            values = pd.to_numeric(aligned[field], errors="coerce").to_numpy(dtype="<f4")
            np.hstack([np.asarray([start_index], dtype="<f4"), values]).astype(
                "<f4"
            ).tofile(instrument_dir / f"{field}.day.bin")
            written_files += 1
        if progress is not None:
            progress(index, len(export_files))

    (instruments_dir / "all.txt").write_text(
        "\n".join(provider_instrument_lines) + "\n", encoding="utf-8"
    )
    (instruments_dir / "market.txt").write_text(
        "\n".join(market_instrument_lines) + "\n", encoding="utf-8"
    )
    return {
        "calendar_days": len(calendar),
        "instruments": len(market_instrument_lines),
        "provider_instruments": len(provider_instrument_lines),
        "feature_instruments": len(export_files),
        "feature_files": written_files,
        "target_dir": str(target.resolve()),
        "streaming": True,
    }
