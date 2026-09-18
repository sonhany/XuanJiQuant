import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant.strategy.f4_contracts import F4Blocked
from quant.strategy.f4_real_pipeline import (
    F4InputPaths,
    WindowFactorFit,
    build_or_load_factor_panel,
    compute_daily_rank_ic,
    fit_window_factors,
    simulate_f4_window,
)
from quant.strategy.portfolio import PortfolioPolicy
from quant.strategy.walk_forward import F4Window


def _window(dates: pd.DatetimeIndex) -> F4Window:
    return F4Window(
        window_id="wf-test",
        train_dates=tuple(dates[:120]),
        valid_dates=tuple(dates[125:145]),
        test_dates=tuple(dates[150:170]),
        purge_bars=5,
        embargo_bars=5,
    )


def _rank_panel(*, predictive_factors: int = 3):
    dates = pd.bdate_range("2024-01-02", periods=180)
    rows = []
    for day_index, day in enumerate(dates):
        for stock_index in range(30):
            signal = (stock_index - 14.5) / 15.0
            close = 10.0 * (1.0 + 0.0005 * day_index + 0.002 * signal)
            row = {
                "date": day,
                "instrument": f"SH{600000 + stock_index:06d}",
                "close": close,
                "forward_return_5d": signal * 0.02,
            }
            for factor_index in range(5):
                row[f"factor_{factor_index}"] = (
                    signal
                    if factor_index < predictive_factors
                    else (
                        ((stock_index * 7 + day_index * 11 + factor_index * 3) % 30)
                        - 14.5
                    )
                    / 15.0
                )
            rows.append(row)
    return pd.DataFrame(rows), dates


def test_rank_ic_fit_uses_train_dates_only_and_freezes_weights():
    panel, dates = _rank_panel()
    window = _window(dates)
    factors = [f"factor_{index}" for index in range(5)]
    daily_ic = compute_daily_rank_ic(panel, factors)

    fit = fit_window_factors(daily_ic, window)
    changed = daily_ic.copy()
    changed.loc[changed["date"].isin(window.test_dates), factors] = -1.0

    assert fit_window_factors(changed, window) == fit
    assert fit.factors == ("factor_0", "factor_1", "factor_2")
    assert fit.fit_end == str(window.train_end.date())
    assert pytest.approx(sum(fit.weights.values())) == 1.0


def test_fit_rejects_fewer_than_three_eligible_factors():
    panel, dates = _rank_panel(predictive_factors=2)
    window = _window(dates)
    factors = [f"factor_{index}" for index in range(5)]
    daily_ic = compute_daily_rank_ic(panel, factors)

    with pytest.raises(F4Blocked, match="train_factor_insufficient"):
        fit_window_factors(daily_ic, window)


def test_simulation_uses_lagged_signal_and_reports_cost_stress():
    panel, dates = _rank_panel()
    window = _window(dates)
    factors = ("factor_0", "factor_1", "factor_2")
    for name in factors:
        panel[name] = panel[name].astype(float)
    panel["open"] = panel["close"]
    panel["volume"] = 10_000_000.0
    panel["amount"] = panel["close"] * panel["volume"]
    panel["adv20_shares"] = 10_000_000.0
    panel["pit_tradable"] = True
    panel["limit_up"] = False
    panel["limit_down"] = False
    panel["industry"] = [f"I{index % 5}" for _day in dates for index in range(30)]
    benchmark = pd.DataFrame(
        {"date": dates, "close": 1000.0 * (1.0 + np.arange(len(dates)) * 0.0002)}
    )
    fit = WindowFactorFit(
        window_id=window.window_id,
        factors=factors,
        directions={name: 1 for name in factors},
        weights={name: 1 / 3 for name in factors},
        median_rank_ic={name: 0.05 for name in factors},
        direction_consistency={name: 1.0 for name in factors},
        fit_end=str(window.train_end.date()),
    )

    base = simulate_f4_window(panel, benchmark, window, fit, cost_multiplier=1.0)
    double = simulate_f4_window(panel, benchmark, window, fit, cost_multiplier=2.0)

    assert base["signal_lag_bars"] == 1
    assert base["rebalance_bars"] == 5
    assert base["future_data_violation_count"] == 0
    assert base["max_name_weight"] <= 0.10 + 1e-12
    assert base["max_industry_weight"] <= 0.25 + 1e-12
    assert 0 < base["max_realized_name_weight"] <= 1
    assert 0 < base["max_realized_industry_weight"] <= 1
    assert base["trade_count"] > 0
    assert double["total_cost"] >= base["total_cost"]

    candidate_policy = PortfolioPolicy(
        top_k=10,
        rebalance_bars=10,
        max_name_weight=0.095,
        target_gross_exposure=0.95,
    )
    candidate = simulate_f4_window(
        panel,
        benchmark,
        window,
        fit,
        cost_multiplier=1.0,
        policy=candidate_policy,
    )
    assert candidate["rebalance_bars"] == 10
    assert candidate["max_name_weight"] <= 0.095 + 1e-12


def test_simulation_flags_factor_fit_from_test_period_as_future_data():
    panel, dates = _rank_panel()
    window = _window(dates)
    panel["open"] = panel["close"]
    panel["adv20_shares"] = 10_000_000.0
    panel["pit_tradable"] = True
    panel["limit_up"] = False
    panel["limit_down"] = False
    panel["industry"] = [f"I{index % 5}" for _day in dates for index in range(30)]
    factors = ("factor_0", "factor_1", "factor_2")
    leaked = WindowFactorFit(
        window_id=window.window_id,
        factors=factors,
        directions={name: 1 for name in factors},
        weights={name: 1 / 3 for name in factors},
        median_rank_ic={name: 0.05 for name in factors},
        direction_consistency={name: 1.0 for name in factors},
        fit_end=str(window.test_start.date()),
    )
    benchmark = pd.DataFrame({"date": dates, "close": np.arange(len(dates)) + 1000.0})

    result = simulate_f4_window(panel, benchmark, window, leaked, cost_multiplier=1.0)

    assert result["future_data_violation_count"] == 1


def test_v2_simulation_uses_candidate_score_loader_contract():
    panel, dates = _rank_panel()
    window = _window(dates)
    panel["open"] = panel["close"]
    panel["adv20_shares"] = 10_000_000.0
    panel["pit_tradable"] = True
    panel["limit_up"] = False
    panel["limit_down"] = False
    panel["industry"] = [f"I{index % 5}" for _day in dates for index in range(30)]
    benchmark = pd.DataFrame({"date": dates, "close": np.arange(len(dates)) + 1000.0})
    calls = []

    def score_loader(signal_date):
        calls.append(pd.Timestamp(signal_date).normalize())
        signal = panel.loc[panel["date"].eq(signal_date)]
        return pd.DataFrame(
            {
                "code": signal["instrument"].astype(str).to_numpy(),
                "industry": signal["industry"].astype(str).to_numpy(),
                "score": np.arange(len(signal), dtype=float),
            }
        )

    result = simulate_f4_window(
        panel,
        benchmark,
        window,
        None,
        cost_multiplier=1.0,
        score_loader=score_loader,
    )

    assert calls
    assert all(signal_date < window.test_end for signal_date in calls)
    assert result["future_data_violation_count"] == 0
    assert result["trade_count"] > 0


def test_v2_simulation_rejects_score_loader_with_extra_columns():
    panel, dates = _rank_panel()
    window = _window(dates)
    panel["open"] = panel["close"]
    panel["adv20_shares"] = 10_000_000.0
    panel["pit_tradable"] = True
    panel["limit_up"] = False
    panel["limit_down"] = False
    panel["industry"] = "I1"
    benchmark = pd.DataFrame({"date": dates, "close": np.arange(len(dates)) + 1000.0})

    with pytest.raises(F4Blocked, match="candidate_score_contract_invalid"):
        simulate_f4_window(
            panel,
            benchmark,
            window,
            None,
            cost_multiplier=1.0,
            score_loader=lambda _date: pd.DataFrame(
                {
                    "code": ["SH600000"],
                    "industry": ["I1"],
                    "score": [1.0],
                    "unexpected": [True],
                }
            ),
        )


def test_v2_simulation_skips_initial_rebalance_when_lagged_score_is_outside_segment():
    panel, dates = _rank_panel()
    window = _window(dates)
    panel["open"] = panel["close"]
    panel["adv20_shares"] = 10_000_000.0
    panel["pit_tradable"] = True
    panel["limit_up"] = False
    panel["limit_down"] = False
    panel["industry"] = [f"I{index % 5}" for _day in dates for index in range(30)]
    benchmark = pd.DataFrame({"date": dates, "close": np.arange(len(dates)) + 1000.0})
    calls = []

    def score_loader(signal_date):
        calls.append(pd.Timestamp(signal_date).normalize())
        if len(calls) == 1:
            return pd.DataFrame(columns=["code", "industry", "score"])
        signal = panel.loc[panel["date"].eq(signal_date)]
        return pd.DataFrame(
            {
                "code": signal["instrument"].astype(str).to_numpy(),
                "industry": signal["industry"].astype(str).to_numpy(),
                "score": np.arange(len(signal), dtype=float),
            }
        )

    result = simulate_f4_window(
        panel,
        benchmark,
        window,
        None,
        cost_multiplier=1.0,
        score_loader=score_loader,
    )

    assert len(calls) >= 2
    assert calls[0] < window.test_start
    assert all(call >= window.test_start for call in calls[1:])
    assert result["trade_count"] > 0
    assert result["future_data_violation_count"] == 0


def test_panel_cache_binds_dataset_identity_and_effective_industry(tmp_path):
    adjusted = tmp_path / "adjusted"
    adjusted.mkdir()
    dates = pd.bdate_range("2022-12-01", periods=80)
    for stock_index in range(3):
        instrument = f"SH{600000 + stock_index:06d}"
        records = []
        for day_index, day in enumerate(dates):
            close = 10 + stock_index + day_index * 0.01
            records.append(
                {
                    "instrument": instrument,
                    "datetime": str(day.date()),
                    "open": close,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "volume": 1_000_000,
                    "amount": close * 1_000_000,
                    "data_version": "pit-test",
                    "tradable": 1,
                    "limit_up": 0,
                    "limit_down": 0,
                }
            )
        (adjusted / f"{instrument}.json").write_text(json.dumps(records), encoding="utf-8")
    # A delisted artifact can remain on disk for audit after it leaves the
    # rolling six-year manifest. It must not enter the active F4 panel.
    legacy = [
        {
            "instrument": "SZ300028",
            "datetime": "2020-08-03",
            "open": 1,
            "high": 1,
            "low": 1,
            "close": 1,
            "volume": 1,
            "amount": 1,
            "data_version": "older-pit-version",
        }
    ]
    (adjusted / "SZ300028.json").write_text(json.dumps(legacy), encoding="utf-8")
    industry_path = tmp_path / "industry.json"
    industry_path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "instrument": f"SH{600000 + stock_index:06d}",
                        "effective_from": "2020-01-01",
                        "industry_code": "old",
                    }
                    for stock_index in range(3)
                ]
                + [
                    {
                        "instrument": f"SH{600000 + stock_index:06d}",
                        "effective_from": "2023-01-01",
                        "industry_code": "new",
                    }
                    for stock_index in range(3)
                ]
            }
        ),
        encoding="utf-8",
    )
    paths = F4InputPaths(
        dataset_root=tmp_path,
        adjusted_root=adjusted,
        industry_path=industry_path,
        benchmark_path=tmp_path / "benchmark.json",
        cache_root=tmp_path / "cache",
        dataset_version="pit-test",
        manifest_hash="manifest-test",
        end_date=str(dates[-1].date()),
        industry_version="industry-v1",
        industry_hash="industry-hash-v1",
        eligible_instruments=tuple(f"SH{600000 + index:06d}" for index in range(3)),
    )

    first = build_or_load_factor_panel(paths, force=True)
    second = build_or_load_factor_panel(paths, force=False)

    assert first.attrs["panel_id"] == second.attrs["panel_id"]
    assert first.attrs["dataset_version"] == "pit-test"
    assert first.attrs["industry_version"] == "industry-v1"
    assert first.attrs["industry_hash"] == "industry-hash-v1"
    assert first["instrument"].nunique() == 3
    assert "SZ300028" not in set(first["instrument"])
    assert first.loc[first["date"] < pd.Timestamp("2023-01-01"), "industry"].eq("old").all()
    assert first.loc[first["date"] >= pd.Timestamp("2023-01-01"), "industry"].eq("new").all()
