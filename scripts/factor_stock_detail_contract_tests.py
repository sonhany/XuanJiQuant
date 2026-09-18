from __future__ import annotations

import hashlib


def _bars(date: str, close: float):
    return [
        {
            "date": date if index == 34 else f"202606{(index % 28) + 1:02d}",
            "close": close,
            "volume": 1000,
        }
        for index in range(35)
    ]


def _publish_factor_input(
    cache,
    codes: list[str],
    date: str,
    *,
    snapshot_id: str = "daily-current",
    data_version: str = "d" * 64,
) -> str:
    from quant.data.snapshot import DataSnapshot, publish_snapshot

    cache.set("stock:universe", codes)
    version = hashlib.sha256(",".join(codes).encode("utf-8")).hexdigest()
    publish_snapshot(
        cache,
        DataSnapshot(
            snapshot_id=snapshot_id,
            dataset="a_share_daily",
            as_of=f"{date[:4]}-{date[4:6]}-{date[6:8]}",
            published_at="2026-08-14T13:00:00+08:00",
            universe_version=version,
            expected_count=len(codes),
            available_count=len(codes),
            source_chain=("contract_test",),
            content_hash=data_version,
            quality_status="passed",
            freshness_status="fresh",
        ),
    )
    return version


def test_factor_stocks_enriches_names_and_snapshot_metadata(tmp_path, monkeypatch):
    from quant.data.cache import SqliteCache
    import scripts.factor_runner as factor_runner

    cache = SqliteCache(db_path=str(tmp_path / "factor.db"))
    monkeypatch.setattr(factor_runner, "cache", cache)
    monkeypatch.setattr(factor_runner, "get_expected_date", lambda: "20260710")
    cache.set("stock:name:688056", "莱伯泰科")
    cache.set("stock:name:300592", "华凯易佰")
    cache.set("kline:688056:d", _bars("20260710", 11))
    cache.set("kline:300592:d", _bars("20260710", 21))
    universe_version = _publish_factor_input(cache, ["688056", "300592"], "20260710")
    cache.set(
        "factor:snapshot",
        {
            "snapshot_id": "daily-current",
            "data_version": "d" * 64,
            "universe_version": universe_version,
            "rows": [
                {"code": "688056", "name": "688056", "close": 66.8, "change_pct": -14.13, "factors": {"range_pct": 0.253}},
                {"code": "300592", "close": 14.09, "change_pct": 15.87, "factors": {"range_pct": 0.2335}},
            ],
            "n": 2,
            "source": "unit_snapshot",
            "_ts": 1783230122.0,
            "saved_at": 1782358342.0,
        },
    )

    out = factor_runner.action_factor_stocks(
        {"factor_name": "range_pct", "top_n": 2, "bottom_n": 1}
    )
    data = out["data"]

    assert data["sort_basis"] == "latest_cross_section_factor_value"
    assert data["factor_definition"] == "(high - low) / close"
    assert data["snapshot_generated_at"].startswith("2026-07-05")
    assert data["data_latest_date"] == "20260710"
    assert data["expected_latest_date"] == "20260710"
    assert data["is_stale"] is False
    assert data["top"][0]["name"] == "莱伯泰科"
    assert data["top"][1]["name"] == "华凯易佰"
    assert data["promotion_state"] == "research_only"
    assert data["execution_authority"] is False


def test_factor_stocks_rejects_old_cross_section(tmp_path, monkeypatch):
    from quant.data.cache import SqliteCache
    import scripts.factor_runner as factor_runner

    cache = SqliteCache(db_path=str(tmp_path / "factor-stale.db"))
    monkeypatch.setattr(factor_runner, "cache", cache)
    monkeypatch.setattr(factor_runner, "get_expected_date", lambda: "20260806")
    cache.set("stock:name:600519", "贵州茅台")
    cache.set("kline:600519:d", _bars("20260806", 1400))
    _publish_factor_input(cache, ["600519"], "20260806")
    cache.set(
        "factor:snapshot",
        {
            "snapshot_id": "daily-old",
            "data_version": "old",
            "rows": [{"code": "600519", "factors": {"ret_5": 0.1}}],
        },
    )

    result = factor_runner.action_factor_stocks({"factor_name": "ret_5"})

    assert result["success"] is False
    assert result["reason_code"] == "factor_projection_version_mismatch"


def test_lightweight_factor_projection_preserves_snapshot_dates(tmp_path, monkeypatch):
    import json
    import pickle
    import pandas as pd
    from scripts import gpu_worker
    import quant.data.cache as cache_module

    source = tmp_path / "factor_snapshot.pkl"
    output = tmp_path / "factor_snapshot_latest.json"
    frame = pd.DataFrame(
        {"date": ["20260805", "20260806"], "close": [10.0, 11.0], "ret_5": [0.1, 0.2]}
    )
    with source.open("wb") as handle:
        pickle.dump(
            {
                "mf": {"600519": frame},
                "saved_at": 1786036981.0,
                "latest_kline_date": "20260806",
                "snapshot_id": "daily-20260806",
                "data_version": "d" * 64,
                "as_of": "20260806",
                "universe_version": "u" * 64,
                "universe_policy": "current_tradeable_v1",
                "active_count": 1,
                "data_count": 1,
                "eligible_count": 1,
                "data_coverage": 1.0,
                "excluded_reasons": {},
                "promotion_state": "research_only",
                "execution_authority": False,
            },
            handle,
        )

    class Cache:
        def get(self, key):
            return "贵州茅台" if key == "stock:name:600519" else None

        def set(self, key, value, ttl=None):
            self.value = value

    monkeypatch.setattr(gpu_worker, "SNAPSHOT_PKL", source)
    monkeypatch.setattr(gpu_worker, "SNAPSHOT_JSON", output)
    monkeypatch.setattr(cache_module, "create_cache", lambda: Cache())

    result = gpu_worker.build_factor_snapshot_latest()
    snapshot = json.loads(output.read_text(encoding="utf-8"))

    assert result["success"] is True
    assert snapshot["latest_kline_date"] == "20260806"
    assert snapshot["rows"][0]["date"] == "20260806"
    assert snapshot["data_version"] == "d" * 64


def test_factor_snapshot_date_prefers_ranked_rows_klines_over_stale_summary(monkeypatch):
    import scripts.factor_runner as factor_runner

    class Connection:
        def execute(self, *_args):
            return self

        def fetchone(self):
            return ("20260710",)

    class Cache:
        _conn = Connection()

        def get(self, key):
            if key == "kline:600519:d":
                return [{"date": "20260806"}, {"date": "20260807"}]
            return None

    monkeypatch.setattr(factor_runner, "cache", Cache())

    assert factor_runner._latest_data_date([{"code": "600519"}]) == "20260807"


def test_precompute_snapshot_persists_explicit_data_dates_and_governance():
    from pathlib import Path

    source = (Path(__file__).resolve().parent / "precompute_snapshot.py").read_text(
        encoding="utf-8"
    )

    assert "'date': latest_date" in source
    assert "'latest_kline_date': latest_kline_date" in source
    assert "**input_snapshot.metadata()" in source
