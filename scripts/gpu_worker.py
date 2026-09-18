"""Offline GPU worker boundary for heavy research jobs.

This script is intentionally not imported by the API server. It is a manual
entry point for jobs that can consume large CPU/GPU resources without touching
the online trading path.

Examples:
  python scripts/gpu_worker.py status
  python scripts/gpu_worker.py factor-snapshot
  python scripts/gpu_worker.py strategy-scan --realistic
  python scripts/gpu_worker.py train --config configs/model_train.json
"""
import argparse
import json
import math
import os
import pickle
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
SNAPSHOT_PKL = DATA_DIR / "factor_snapshot.pkl"
SNAPSHOT_JSON = DATA_DIR / "factor_snapshot_latest.json"

GOVERNANCE_FIELDS = (
    "snapshot_id",
    "data_version",
    "as_of",
    "universe_version",
    "universe_policy",
    "active_count",
    "data_count",
    "eligible_count",
    "data_coverage",
    "excluded_reasons",
    "promotion_state",
    "execution_authority",
)


def governance_metadata(source: dict) -> dict:
    missing = [field for field in GOVERNANCE_FIELDS if field not in source]
    if missing:
        raise ValueError(
            "factor snapshot governance metadata missing: " + ", ".join(missing)
        )
    metadata = {field: source[field] for field in GOVERNANCE_FIELDS}
    if metadata["promotion_state"] != "research_only":
        raise ValueError("factor snapshot must remain research_only")
    if metadata["execution_authority"] is not False:
        raise ValueError("factor snapshot can never grant execution authority")
    return metadata


def emit(obj: dict) -> int:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))
    return 0 if obj.get("success", False) else 1


def gpu_status() -> dict:
    status = {
        "success": True,
        "online_api_attached": False,
        "nvidia_smi": None,
        "torch": {"installed": False, "import_ok": False, "cuda_available": False},
        "recommendation": "Use this worker only for offline factor snapshots, full-market backtests, model training, or local LLM experiments.",
    }

    try:
        r = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total,memory.used,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=10,
        )
        status["nvidia_smi"] = {
            "ok": r.returncode == 0,
            "stdout": r.stdout.strip(),
            "stderr": r.stderr.strip(),
        }
    except Exception as exc:
        status["nvidia_smi"] = {"ok": False, "error": str(exc)}

    try:
        import torch  # type: ignore

        status["torch"] = {
            "installed": True,
            "import_ok": True,
            "version": getattr(torch, "__version__", None),
            "cuda_version": getattr(torch.version, "cuda", None),
            "cuda_available": bool(torch.cuda.is_available()),
            "device_count": int(torch.cuda.device_count()),
            "device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        }
    except Exception as exc:
        status["torch"] = {
            "installed": True,
            "import_ok": False,
            "cuda_available": False,
            "error": str(exc)[:800],
        }

    return status


def build_factor_snapshot_latest(
    *,
    source_path: str | Path | None = None,
    output_path: str | Path | None = None,
    update_global_cache: bool | None = None,
) -> dict:
    """Build a lightweight latest-cross-section JSON from factor_snapshot.pkl."""
    source = Path(source_path).resolve() if source_path is not None else SNAPSHOT_PKL
    output = Path(output_path).resolve() if output_path is not None else SNAPSHOT_JSON
    if not source.exists():
        return {
            "success": False,
            "error": f"{source} not found. Run scripts/evaluate_factors.py first.",
        }

    sys.path.insert(0, str(ROOT))
    from quant.data.cache import create_cache

    t0 = time.time()
    cache = create_cache()
    with source.open("rb") as f:
        obj = pickle.load(f)
    metadata = governance_metadata(obj)

    rows = []
    base_cols = {"date", "open", "high", "low", "close", "volume", "amount"}
    for code, fdf in (obj.get("mf") or {}).items():
        if fdf is None or getattr(fdf, "empty", True):
            continue
        try:
            latest = fdf.iloc[-1]
            prev = fdf.iloc[-2] if len(fdf) >= 2 else latest
            close = float(latest.get("close", 0) or 0)
            prev_close = float(prev.get("close", close) or close)
            change_pct = round((close - prev_close) / prev_close * 100, 2) if prev_close else 0
            factors = {}
            for col in fdf.columns:
                if col in base_cols:
                    continue
                try:
                    value = float(latest.get(col))
                    if not math.isnan(value) and not math.isinf(value):
                        factors[col] = round(value, 4)
                except Exception:
                    continue
            if factors:
                latest_date = str(latest.get("date") or "").replace("-", "")[:8]
                rows.append(
                    {
                        "code": code,
                        "name": cache.get(f"stock:name:{code}") or code,
                        "date": latest_date,
                        "close": round(close, 2),
                        "change_pct": change_pct,
                        "factors": factors,
                    }
                )
        except Exception:
            continue

    snapshot = {
        "rows": rows,
        "_ts": time.time(),
        "n": len(rows),
        "source": "gpu_worker_factor_snapshot_latest",
        "saved_at": obj.get("saved_at"),
        "latest_kline_date": obj.get("latest_kline_date"),
        **metadata,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(
        f"{output.name}.{os.getpid()}.{time.time_ns()}.tmp"
    )
    try:
        with temporary.open("w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, separators=(",", ":"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
    publish_cache = (
        bool(update_global_cache)
        if update_global_cache is not None
        else source == SNAPSHOT_PKL and output == SNAPSHOT_JSON
    )
    if publish_cache:
        cache.set("factor:snapshot", snapshot, ttl=1800)

    return {
        "success": True,
        "task": "factor-snapshot",
        "rows": len(rows),
        "output": str(output),
        "size_mb": round(output.stat().st_size / 1024 / 1024, 2),
        "elapsed_seconds": round(time.time() - t0, 2),
    }


def run_strategy_scan(realistic: bool) -> dict:
    cmd = [sys.executable, str(ROOT / "scripts" / "scan_strategies.py")]
    if realistic:
        cmd.append("--realistic")
    t0 = time.time()
    r = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=60 * 60)
    return {
        "success": r.returncode == 0,
        "task": "strategy-scan",
        "realistic": realistic,
        "elapsed_seconds": round(time.time() - t0, 2),
        "stdout_tail": (r.stdout or "")[-2000:],
        "stderr_tail": (r.stderr or "")[-2000:],
    }


def train_model(config_path: str) -> dict:
    status = gpu_status()
    if not status.get("torch", {}).get("import_ok") or not status.get("torch", {}).get("cuda_available"):
        return {
            "success": False,
            "task": "train",
            "error": "CUDA torch runtime is not available. Fix the offline GPU Python environment before training.",
            "gpu_status": status,
        }
    cfg = Path(config_path)
    if not cfg.exists():
        return {
            "success": False,
            "task": "train",
            "error": f"training config not found: {cfg}",
        }
    return {
        "success": False,
        "task": "train",
        "error": "No model training implementation is wired yet. The GPU boundary is ready; add a trainer module for the chosen model architecture.",
        "config": str(cfg),
        "gpu_status": status,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline GPU worker for XuanJi heavy jobs")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("factor-snapshot")
    scan = sub.add_parser("strategy-scan")
    scan.add_argument("--realistic", action="store_true")
    train = sub.add_parser("train")
    train.add_argument("--config", required=True)
    args = parser.parse_args()

    if args.command == "status":
        return emit(gpu_status())
    if args.command == "factor-snapshot":
        return emit(build_factor_snapshot_latest())
    if args.command == "strategy-scan":
        return emit(run_strategy_scan(realistic=args.realistic))
    if args.command == "train":
        return emit(train_model(args.config))
    return emit({"success": False, "error": f"unknown command: {args.command}"})


if __name__ == "__main__":
    raise SystemExit(main())
