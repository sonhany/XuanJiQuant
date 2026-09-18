from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,96}$")


def write_shadow_signal(
    *,
    output_dir: Path,
    model_id: str,
    workflow_run_id: str,
    dataset_version: str,
    signal_hash: str,
    predictions: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    if not SAFE_ID.fullmatch(str(model_id)):
        raise ValueError("invalid shadow signal model_id")
    if not SAFE_ID.fullmatch(str(workflow_run_id)):
        raise ValueError("invalid shadow signal workflow_run_id")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", str(signal_hash)):
        raise ValueError("invalid shadow signal hash")
    rows = []
    for index, source in enumerate(predictions, start=1):
        trade_date = str(source.get("date") or "")[:10]
        instrument = str(source.get("instrument") or "").upper()
        if not trade_date or not instrument:
            raise ValueError("shadow prediction requires date and instrument")
        rows.append(
            {
                "date": trade_date,
                "instrument": instrument,
                "score": float(source.get("score") or 0.0),
                "rank": int(source.get("rank") or index),
            }
        )
    if not rows:
        raise ValueError("shadow prediction is empty")
    trade_dates = {row["date"] for row in rows}
    if len(trade_dates) != 1:
        raise ValueError("shadow signal must contain exactly one trade date")
    trade_date = next(iter(trade_dates))
    payload = {
        "schema_version": "xuanji_shadow_signal_v1",
        "model_id": str(model_id),
        "workflow_run_id": str(workflow_run_id),
        "dataset_version": str(dataset_version),
        "signal_hash": str(signal_hash).lower(),
        "trade_date": trade_date,
        "predictions": sorted(rows, key=lambda row: (row["rank"], row["instrument"])),
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "safety_boundary": "shadow_research_signal_only",
        "execution_authority": False,
        "can_trigger_order": False,
    }
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    path = Path(output_dir) / str(model_id) / f"{trade_date}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + ".tmp")
    pending.write_bytes(encoded)
    pending.replace(path)
    return {
        "path": path,
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "trade_date": trade_date,
        "predictions": len(rows),
    }
