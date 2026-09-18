import json

import pandas as pd

from scripts.scan_strategies import multi_factor_backtest
from scripts import strategy_runner


def test_multi_factor_scan_uses_non_overlapping_holding_periods():
    dates = pd.bdate_range("2026-01-01", periods=40).strftime("%Y%m%d")
    mf = {
        "600519": pd.DataFrame({"date": dates, "close": range(100, 140), "factor": range(40)}),
        "000001": pd.DataFrame({"date": dates, "close": range(80, 120), "factor": range(40, 0, -1)}),
    }

    result = multi_factor_backtest(mf, {"factor": 1.0}, top_n=1, hold=5)

    assert result is not None
    assert result["n_periods"] <= 8


def test_market_scan_ignores_retired_scans_and_reads_f4_projection(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "strategy_scan.json").write_text(
        json.dumps({"realistic": False, "strategies": [{"factor": "ideal"}]}),
        encoding="utf-8",
    )
    (data_dir / "strategy_scan_realistic.json").write_text(
        json.dumps({"realistic": True, "strategies": [{"factor": "real"}]}),
        encoding="utf-8",
    )
    f4_dir = data_dir / "research" / "f4"
    f4_dir.mkdir(parents=True)
    latest_path = f4_dir / "latest.json"
    latest_path.write_text(
        json.dumps(
            {
                "validation_id": "f4-id",
                "status": "f4_blocked",
                "reasons": ["pit_manifest_incomplete"],
                "promotion_state": "research_only",
                "execution_authority": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(strategy_runner, "F4_LATEST_PATH", str(latest_path))

    result = strategy_runner.action_market_scan()

    assert result["success"] is True
    assert result["data"]["status"] == "f4_blocked"
    assert result["data"]["reasons"] == ["pit_manifest_incomplete"]
    assert result["data"]["source"] == "f4_latest_projection"
    assert "strategies" not in result["data"]
