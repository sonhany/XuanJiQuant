import json
import pickle

import pandas as pd
import pytest

from scripts.evaluate_factors import (
    build_factor_engine,
    row_snapshot_fundamental_coverage,
    snapshot_matches_input,
    snapshot_has_usable_fundamentals,
)
from scripts.gpu_worker import governance_metadata
from scripts import gpu_worker


def test_full_market_factor_engine_always_keeps_financial_cache():
    cache = object()

    engine = build_factor_engine(cache)

    assert engine._cache is cache


def test_pickle_snapshot_requires_at_least_one_usable_fundamental_value():
    incomplete = {
        "mf": {
            "600519": pd.DataFrame({"date": ["20260807"], "roe": [float("nan")]})
        }
    }
    complete = {
        "mf": {
            "600519": pd.DataFrame({"date": ["20260807"], "roe": [31.2]})
        }
    }

    assert snapshot_has_usable_fundamentals(incomplete) is False
    assert snapshot_has_usable_fundamentals(complete) is True


def test_lightweight_snapshot_reports_real_fundamental_coverage():
    snapshot = {
        "rows": [
            {"code": "600519", "factors": {"roe": 31.2, "roa": 18.1}},
            {"code": "000001", "factors": {"roe": 9.5}},
            {"code": "000002", "factors": {}},
        ]
    }

    coverage = row_snapshot_fundamental_coverage(snapshot)

    assert coverage["roe"] == 2
    assert coverage["roa"] == 1


def test_cached_factor_snapshot_must_match_governed_input_version():
    contract = type(
        "Contract",
        (),
        {
            "snapshot_id": "daily-20260813",
            "data_version": "v2",
            "universe_version": "u2",
        },
    )()

    assert snapshot_matches_input(
        {
            "snapshot_id": "daily-20260813",
            "data_version": "v2",
            "universe_version": "u2",
        },
        contract,
    ) is True
    assert snapshot_matches_input(
        {
            "snapshot_id": "daily-old",
            "data_version": "v1",
            "universe_version": "u2",
        },
        contract,
    ) is False


def test_lightweight_projection_requires_and_preserves_governance_metadata():
    source = {
        "snapshot_id": "daily-20260813",
        "data_version": "d" * 64,
        "as_of": "20260813",
        "universe_version": "u" * 64,
        "universe_policy": "current_tradeable_v1",
        "active_count": 5203,
        "data_count": 5201,
        "eligible_count": 5160,
        "data_coverage": 0.9996,
        "excluded_reasons": {"special_treatment_or_delisting": 30},
        "promotion_state": "research_only",
        "execution_authority": False,
    }

    assert governance_metadata(source) == source
    with pytest.raises(ValueError, match="data_version"):
        governance_metadata({"snapshot_id": "daily-20260813"})


def test_staging_projection_uses_explicit_paths_without_publishing_global_cache(
    tmp_path, monkeypatch
):
    source = tmp_path / "generation" / "factor_snapshot.pkl"
    output = tmp_path / "generation" / "factor_snapshot_latest.json"
    global_projection = tmp_path / "global" / "factor_snapshot_latest.json"
    cache_sets = []

    source.parent.mkdir(parents=True)
    with source.open("wb") as handle:
        pickle.dump(
            {
                "mf": {
                    "000001": pd.DataFrame(
                        {
                            "date": ["20260819"],
                            "close": [10.0],
                            "range_pct": [1.25],
                        }
                    )
                },
                "saved_at": 1.0,
                "latest_kline_date": "20260819",
                "snapshot_id": "daily-20260819",
                "data_version": "data-v19",
                "as_of": "20260819",
                "universe_version": "universe-v19",
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
            return "股票一" if key == "stock:name:000001" else None

        def set(self, *args, **kwargs):
            cache_sets.append((args, kwargs))

    monkeypatch.setattr("quant.data.cache.create_cache", lambda: Cache())
    monkeypatch.setattr(gpu_worker, "SNAPSHOT_JSON", global_projection)

    result = gpu_worker.build_factor_snapshot_latest(
        source_path=source,
        output_path=output,
    )

    assert result["success"] is True
    assert json.loads(output.read_text(encoding="utf-8"))["data_version"] == "data-v19"
    assert global_projection.exists() is False
    assert cache_sets == []
