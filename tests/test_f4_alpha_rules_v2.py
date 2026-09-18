import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from quant.strategy.f4_alpha_rules import (
    DERIVED_FEATURE_NAMES,
    DERIVED_FEATURE_SCHEMA_VERSION,
    derive_rule_features,
    preprocess_cross_section,
)
from quant.strategy.f4_contracts import F4Blocked
from quant.strategy.f4_real_pipeline import (
    ELIGIBLE_FACTORS,
    PANEL_SCHEMA_VERSION,
    F4InputPaths,
    _panel_id,
    build_or_load_factor_panel,
)


def test_price_scale_features_are_dimensionless():
    frame = pd.DataFrame(
        {
            "close": [10.0],
            "ema_12": [8.0],
            "ema_26": [10.0],
            "macd_hist": [0.5],
            "atr_14": [0.2],
            "boll_upper": [12.0],
            "boll_lower": [8.0],
            "boll_mid": [10.0],
        }
    )

    result = derive_rule_features(frame)

    assert result.loc[0, "ema_gap_12"] == pytest.approx(0.25)
    assert result.loc[0, "ema_gap_26"] == pytest.approx(0.0)
    assert result.loc[0, "macd_hist_norm"] == pytest.approx(0.05)
    assert result.loc[0, "atr_14_norm"] == pytest.approx(0.02)
    assert result.loc[0, "boll_width"] == pytest.approx(0.4)


def test_ratio_features_use_safe_positive_denominators():
    frame = pd.DataFrame(
        {
            "ret_20": [0.2, 0.2, np.inf],
            "volatility_20": [0.0, -0.1, 0.1],
            "ret_60": [0.3, 0.3, 0.3],
            "volatility_60": [0.2, np.nan, np.inf],
            "turnover_5": [10.0, 10.0, 10.0],
            "turnover_20": [5.0, 0.0, -1.0],
        }
    )

    result = derive_rule_features(frame)

    assert result.loc[0, "turnover_5_over_20"] == pytest.approx(2.0)
    assert result.loc[0, "ret_60_over_volatility_60"] == pytest.approx(1.5)
    assert result.loc[0, "ret_20_over_volatility_20"] != 0.0
    assert result.loc[:, DERIVED_FEATURE_NAMES].replace([np.inf, -np.inf], np.nan).isna().sum().sum() > 0
    assert np.isnan(result.loc[0, "ret_20_over_volatility_20"])
    assert np.isnan(result.loc[1, "ret_20_over_volatility_20"])
    assert np.isnan(result.loc[2, "ret_20_over_volatility_20"])
    assert np.isnan(result.loc[1, "turnover_5_over_20"])
    assert np.isnan(result.loc[2, "turnover_5_over_20"])


def test_missing_dependencies_produce_missing_derived_values_without_mutating_input():
    frame = pd.DataFrame({"ret_20": [0.2], "volatility_20": [0.1]})

    result = derive_rule_features(frame)

    assert tuple(name for name in DERIVED_FEATURE_NAMES if name in result.columns) == DERIVED_FEATURE_NAMES
    assert result.loc[0, "ret_20_over_volatility_20"] == pytest.approx(2.0)
    assert np.isnan(result.loc[0, "ema_gap_12"])
    assert list(frame.columns) == ["ret_20", "volatility_20"]


def test_preprocessing_clips_at_five_mad_and_ranks_within_industry():
    frame = pd.DataFrame(
        {
            "instrument": [f"S{index}" for index in range(9)],
            "industry": ["I1"] * 5 + ["I2"] * 4,
            "ret_20": [0.0, 1.0, 2.0, 100.0, 200.0, 3.0, 4.0, 5.0, 6.0],
        }
    )

    result = preprocess_cross_section(frame, ("ret_20",))

    assert np.isfinite(result["ret_20"].dropna()).all()
    assert result.groupby("industry")["ret_20"].mean().round(12).eq(0.5).all()
    assert result.loc[3, "ret_20"] == result.loc[4, "ret_20"]
    assert result.loc[0, "ret_20"] == pytest.approx(0.0)
    assert result.loc[5, "ret_20"] == pytest.approx(0.0)


def test_industry_singleton_gets_neutral_rank_and_no_cross_industry_ordering():
    frame = pd.DataFrame(
        {
            "instrument": ["A", "B", "C"],
            "industry": ["I1", "I1", "I2"],
            "ret_20": [1.0, 3.0, 1_000_000.0],
        }
    )

    result = preprocess_cross_section(frame, ("ret_20",))

    assert result.loc[result["instrument"] == "C", "ret_20"].item() == pytest.approx(0.5)
    assert result.loc[result["instrument"] == "A", "ret_20"].item() == pytest.approx(0.0)
    assert result.loc[result["instrument"] == "B", "ret_20"].item() == pytest.approx(1.0)


def test_signed_feature_contract_applies_negation_before_industry_rank():
    frame = pd.DataFrame(
        {
            "instrument": ["A", "B"],
            "industry": ["I1", "I1"],
            "volatility_20": [0.1, 0.2],
        }
    )

    result = preprocess_cross_section(frame, ("-volatility_20",))

    assert result["-volatility_20"].tolist() == pytest.approx([1.0, 0.0])
    assert result["volatility_20"].tolist() == pytest.approx([0.1, 0.2])


def test_preprocessing_preserves_missing_and_rejects_missing_industry():
    frame = pd.DataFrame(
        {
            "instrument": ["A", "B", "C"],
            "industry": ["I1", "I1", "I1"],
            "ret_20": [1.0, np.inf, np.nan],
        }
    )

    result = preprocess_cross_section(frame, ("ret_20",))

    assert result.loc[0, "ret_20"] == pytest.approx(0.5)
    assert result.loc[1:, "ret_20"].isna().all()
    with pytest.raises(ValueError, match="industry_column_missing"):
        preprocess_cross_section(frame.drop(columns="industry"), ("ret_20",))


def test_multi_date_preprocessing_matches_reference_without_per_date_callbacks(
    monkeypatch,
):
    import quant.strategy.f4_alpha_rules as rules

    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2026-01-05"] * 6 + ["2026-01-06"] * 6
            ),
            "industry": ["A", "A", "A", "B", "B", "C"] * 2,
            "ret_20": [1.0, 1.0, 4.0, 2.0, np.nan, 9.0, 3.0, 5.0, 5.0, 8.0, 7.0, 11.0],
            "volatility_20": [2.0, 3.0, 7.0, 5.0, 4.0, 1.0, 8.0, 6.0, 6.0, 2.0, np.nan, 9.0],
        }
    )
    features = ("ret_20", "-volatility_20")
    expected = pd.concat(
        [
            preprocess_cross_section(group, features)
            for _date, group in frame.groupby("date", sort=True, dropna=False)
        ]
    ).sort_index()

    monkeypatch.setattr(
        rules,
        "preprocess_cross_section",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("multi-date path called the per-date Python callback")
        ),
    )

    actual = rules._preprocess_by_date(frame, features)

    pd.testing.assert_frame_equal(actual, expected)


def test_v2_panel_cache_identity_rejects_metadata_without_derived_schema(tmp_path):
    paths = F4InputPaths(
        dataset_root=tmp_path,
        adjusted_root=tmp_path / "adjusted",
        industry_path=tmp_path / "industry.json",
        benchmark_path=tmp_path / "benchmark.json",
        cache_root=tmp_path / "cache",
        dataset_version="pit-v2",
        manifest_hash="manifest-v2",
        end_date="2026-08-20",
        industry_version="industry-v2",
        industry_hash="industry-hash-v2",
        eligible_instruments=("SH600000",),
    )
    panel_id = _panel_id(paths)
    cache_dir = paths.cache_root / panel_id
    cache_dir.mkdir(parents=True)
    (cache_dir / "factor_panel.parquet").write_bytes(b"old-v1-cache")
    (cache_dir / "metadata.json").write_text(
        json.dumps(
            {
                "panel_id": panel_id,
                "dataset_version": paths.dataset_version,
                "manifest_hash": paths.manifest_hash,
                "industry_version": paths.industry_version,
                "industry_hash": paths.industry_hash,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(F4Blocked, match="factor_panel_cache_identity_mismatch"):
        build_or_load_factor_panel(paths)


def test_panel_id_explicitly_binds_derived_feature_contract(tmp_path):
    paths = F4InputPaths(
        dataset_root=tmp_path,
        adjusted_root=tmp_path / "adjusted",
        industry_path=tmp_path / "industry.json",
        benchmark_path=tmp_path / "benchmark.json",
        cache_root=tmp_path / "cache",
        dataset_version="pit-v2",
        manifest_hash="manifest-v2",
        end_date="2026-08-20",
        industry_version="industry-v2",
        industry_hash="industry-hash-v2",
        eligible_instruments=("SH600000",),
    )
    v2_payload = {
        "schema": PANEL_SCHEMA_VERSION,
        "dataset_version": paths.dataset_version,
        "manifest_hash": paths.manifest_hash,
        "industry_version": paths.industry_version,
        "industry_hash": paths.industry_hash,
        "end_date": paths.end_date,
        "factor_names": ELIGIBLE_FACTORS,
        "derived_feature_schema_version": DERIVED_FEATURE_SCHEMA_VERSION,
        "derived_feature_names": DERIVED_FEATURE_NAMES,
        "eligible_instruments": paths.eligible_instruments,
    }
    expected_v2_id = hashlib.sha256(
        json.dumps(v2_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    cache_identity_without_derived_contract = dict(v2_payload)
    cache_identity_without_derived_contract.pop("derived_feature_schema_version")
    cache_identity_without_derived_contract.pop("derived_feature_names")
    incomplete_id = hashlib.sha256(
        json.dumps(
            cache_identity_without_derived_contract,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    assert DERIVED_FEATURE_SCHEMA_VERSION == "f4-rule-derived-features-v2"
    assert len(DERIVED_FEATURE_NAMES) == 8
    assert _panel_id(paths) == expected_v2_id
    assert _panel_id(paths) != incomplete_id
