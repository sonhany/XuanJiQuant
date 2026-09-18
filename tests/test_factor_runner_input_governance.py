from __future__ import annotations

import hashlib
import json

import pandas as pd
import pytest

from quant.data.cache import MemoryCache
from quant.data.snapshot import DataSnapshot, publish_snapshot


@pytest.fixture(autouse=True)
def _isolate_authoritative_publication_root(tmp_path, monkeypatch):
    import scripts.factor_runner as factor_runner

    monkeypatch.setattr(
        factor_runner,
        "RESEARCH_PUBLICATION_ROOT",
        tmp_path / "isolated-publication",
    )


def _bars(date: str, count: int = 35):
    return [
        {
            "date": date if index == count - 1 else f"202607{(index % 28) + 1:02d}",
            "open": 10,
            "high": 11,
            "low": 9,
            "close": 10,
            "volume": 1000,
            "amount": 10000,
        }
        for index in range(count)
    ]


def _governed_cache(codes: list[str]) -> MemoryCache:
    cache = MemoryCache()
    cache.set("stock:universe", codes)
    for code in codes:
        cache.set(f"kline:{code}:d", _bars("20260813"))
    version = hashlib.sha256(",".join(codes).encode("utf-8")).hexdigest()
    publish_snapshot(
        cache,
        DataSnapshot(
            snapshot_id="daily-20260813",
            dataset="a_share_daily",
            as_of="2026-08-13",
            published_at="2026-08-14T13:00:00+08:00",
            universe_version=version,
            expected_count=len(codes),
            available_count=len(codes),
            source_chain=("tdx_quant",),
            content_hash="d" * 64,
            quality_status="passed",
            freshness_status="fresh",
        ),
    )
    return cache


def test_single_stock_factor_calculation_passes_code_for_fundamentals(monkeypatch):
    import scripts.factor_runner as factor_runner

    cache = MemoryCache()
    cache.set("kline:600519:d", _bars("20260813"))
    seen = []

    class Engine:
        def compute_all(self, frame, code=None):
            seen.append(code)
            out = frame.copy()
            out["roe"] = 0.2
            return out

    monkeypatch.setattr(factor_runner, "cache", cache)
    monkeypatch.setattr(factor_runner, "engine", Engine())

    result = factor_runner.action_factors({"code": "600519"})

    assert result["success"] is True
    assert seen == ["600519"]
    assert result["diagnostic_only"] is True


def test_factor_ranking_uses_only_contract_eligible_codes(tmp_path, monkeypatch):
    import scripts.factor_runner as factor_runner

    cache = _governed_cache(["600519", "002808"])
    cache.set("stock:name:600519", "贵州茅台")
    cache.set("stock:name:002808", "恒久退")
    cache.set(
        "factor:snapshot",
        {
            "snapshot_id": "daily-20260813",
            "data_version": "d" * 64,
            "universe_version": hashlib.sha256("600519,002808".encode()).hexdigest(),
            "as_of": "20260813",
            "rows": [
                {"code": "600519", "name": "贵州茅台", "factors": {"ret_5": 0.1}},
                {"code": "002808", "name": "恒久退", "factors": {"ret_5": 0.9}},
            ],
        },
    )
    monkeypatch.setattr(factor_runner, "cache", cache)
    monkeypatch.setattr(factor_runner, "SNAPSHOT_JSON_PATH", str(tmp_path / "missing.json"))
    monkeypatch.setattr(factor_runner, "get_expected_date", lambda: "20260813")

    result = factor_runner.action_factor_stocks({"factor_name": "ret_5"})

    assert result["success"] is True
    assert [row["code"] for row in result["data"]["top"]] == ["600519"]
    assert result["data"]["n_stocks"] == 1
    assert result["data"]["data_version"] == "d" * 64
    assert result["data"]["universe_policy"] == "current_tradeable_v1"
    assert result["data"]["promotion_state"] == "research_only"
    assert result["data"]["execution_authority"] is False


def test_factor_ranking_rejects_projection_version_mismatch(tmp_path, monkeypatch):
    import scripts.factor_runner as factor_runner

    cache = _governed_cache(["600519"])
    cache.set("stock:name:600519", "贵州茅台")
    cache.set(
        "factor:snapshot",
        {
            "snapshot_id": "daily-old",
            "data_version": "old",
            "rows": [{"code": "600519", "factors": {"ret_5": 0.1}}],
        },
    )
    monkeypatch.setattr(factor_runner, "cache", cache)
    monkeypatch.setattr(factor_runner, "SNAPSHOT_JSON_PATH", str(tmp_path / "missing.json"))
    monkeypatch.setattr(factor_runner, "get_expected_date", lambda: "20260813")

    result = factor_runner.action_factor_stocks({"factor_name": "ret_5"})

    assert result["success"] is False
    assert result["reason_code"] == "factor_projection_version_mismatch"


def test_market_evaluation_rejects_data_version_mismatch(tmp_path, monkeypatch):
    import scripts.factor_runner as factor_runner

    cache = _governed_cache(["600519"])
    cache.set("stock:name:600519", "贵州茅台")
    evaluation = tmp_path / "factor_evaluation.json"
    evaluation.write_text(
        json.dumps({"data_version": "old", "factors": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr(factor_runner, "cache", cache)
    monkeypatch.setattr(factor_runner, "EVALUATION_PATH", str(evaluation), raising=False)
    monkeypatch.setattr(factor_runner, "get_expected_date", lambda: "20260813")

    result = factor_runner.action_market_eval({})

    assert result["success"] is False
    assert result["reason_code"] == "factor_evaluation_version_mismatch"


def test_market_evaluation_serves_last_complete_generation_during_refresh(tmp_path, monkeypatch):
    import scripts.factor_runner as factor_runner

    cache = _governed_cache(["600519"])
    evaluation = tmp_path / "factor_evaluation.json"
    evaluation.write_text(
        json.dumps(
            {
                "snapshot_id": "daily-20260812",
                "data_version": "old-version",
                "target_date": "20260812",
                "factors": [{"factor": "ret_5", "abs_ic_1d": 0.04}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(factor_runner, "cache", cache)
    monkeypatch.setattr(factor_runner, "get_expected_date", lambda: "20260813")
    publication_root = tmp_path / "daily"
    publication_root.mkdir()
    (publication_root / "latest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(factor_runner, "RESEARCH_PUBLICATION_ROOT", publication_root)
    monkeypatch.setattr(
        factor_runner,
        "resolve_complete_artifact",
        lambda _root, name: evaluation if name == "factor_evaluation.json" else None,
        raising=False,
    )
    monkeypatch.setattr(
        factor_runner,
        "read_publication_status",
        lambda _root: {
            "state": "refreshing",
            "target_date": "20260813",
            "last_complete_generation_id": "generation-old",
        },
        raising=False,
    )

    result = factor_runner.action_market_eval({})

    assert result["success"] is True
    assert result["data"]["snapshot_id"] == "daily-20260812"
    assert result["data"]["is_current"] is False
    assert result["data"]["research_refresh"]["state"] == "refreshing"
    assert result["data"]["research_refresh"]["target_date"] == "20260813"


def test_factor_ranking_uses_complete_generation_rows_without_new_universe_relabel(
    tmp_path, monkeypatch
):
    import scripts.factor_runner as factor_runner

    cache = _governed_cache(["600519"])
    projection = tmp_path / "factor_snapshot_latest.json"
    projection.write_text(
        json.dumps(
            {
                "snapshot_id": "daily-20260812",
                "data_version": "old-version",
                "as_of": "20260812",
                "rows": [
                    {"code": "600519", "name": "贵州茅台", "factors": {"ret_5": 0.1}},
                    {"code": "000001", "name": "平安银行", "factors": {"ret_5": 0.2}},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(factor_runner, "cache", cache)
    monkeypatch.setattr(factor_runner, "get_expected_date", lambda: "20260813")
    publication_root = tmp_path / "daily"
    publication_root.mkdir()
    (publication_root / "latest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(factor_runner, "RESEARCH_PUBLICATION_ROOT", publication_root)
    monkeypatch.setattr(
        factor_runner,
        "resolve_complete_artifact",
        lambda _root, name: projection if name == "factor_snapshot_latest.json" else None,
        raising=False,
    )
    monkeypatch.setattr(
        factor_runner,
        "read_publication_status",
        lambda _root: {"state": "refreshing", "target_date": "20260813"},
        raising=False,
    )

    result = factor_runner.action_factor_stocks({"factor_name": "ret_5"})

    assert result["success"] is True
    assert [row["code"] for row in result["data"]["top"]] == ["000001", "600519"]
    assert result["data"]["is_current"] is False
    assert result["data"]["research_refresh"]["state"] == "refreshing"
