#!/usr/bin/env python
"""Run the single-writer, resumable six-year PIT collection."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant.qlib.collector import collect_six_year_dataset  # noqa: E402
from quant.qlib.sources import SOURCE_CIRCUIT  # noqa: E402


DEFAULT_ROOT = PROJECT_ROOT / "data" / "qlib" / "datasets" / "a_share_6y_daily"


class CollectionRunLock:
    """Windows advisory lock preventing overlapping manifest writers."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.handle = None

    def __enter__(self):
        import msvcrt

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            self.handle.close()
            self.handle = None
            raise RuntimeError("six-year PIT collection is already running") from exc
        return self

    def __exit__(self, exc_type, exc, traceback):
        import msvcrt

        if self.handle is not None:
            self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            self.handle.close()
            self.handle = None


def load_reference(dataset_root: Path) -> dict:
    path = dataset_root / "point_in_time" / "reference_data.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("reference_data.json must contain an object")
    health = value.get("source_health") or {}
    if health.get("passed") is not True:
        raise RuntimeError("reference data source health has not passed")
    if not value.get("current_universe") or not value.get("delistings"):
        raise RuntimeError("reference data universe or delisting ledger is empty")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--start-date", default="2020-08-01")
    parser.add_argument("--end-date", default="2026-08-14")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--circuit-cooldown", type=float, default=2.0)
    args = parser.parse_args()
    dataset_root = args.dataset_root.resolve()
    reference = load_reference(dataset_root)
    instruments = [row["instrument"] for row in reference["current_universe"]]
    SOURCE_CIRCUIT.cooldown_seconds = max(1.0, float(args.circuit_cooldown))
    print(
        json.dumps(
            {
                "event": "reference_loaded",
                "current_universe": len(instruments),
                "name_changes": len(reference.get("name_changes") or []),
                "delistings": len(reference.get("delistings") or []),
                "fetched_at": (reference.get("source_health") or {}).get("fetched_at"),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    with CollectionRunLock(dataset_root / ".collection.lock"):
        result = collect_six_year_dataset(
            instruments,
            args.start_date,
            args.end_date,
            dataset_root,
            reference_data=reference,
            checkpoint_every=25,
            workers=max(1, min(2, int(args.workers))),
            failure_abort_after=1000,
            failure_abort_ratio=1.0,
            progress_callback=lambda done, total: print(
                json.dumps(
                    {
                        "event": "progress",
                        "processed": done,
                        "requested": total,
                        "percent": round(done / max(total, 1) * 100, 2),
                    }
                ),
                flush=True,
            ),
        )
    print(json.dumps({"event": "complete", **result}, ensure_ascii=False), flush=True)
    return 0 if result.get("status") == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
