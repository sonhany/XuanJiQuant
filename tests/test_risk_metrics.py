import pytest

from quant.risk.engine import RiskEngine
from scripts import risk_runner


class _RiskCache:
    def __init__(self, values):
        self.values = values

    def get(self, key):
        return self.values.get(key)


def test_portfolio_risk_uses_percent_units_and_comparable_risk_budget():
    engine = RiskEngine()
    engine._estimate_returns = lambda _codes: [
        -0.10, -0.08, -0.06, -0.04, -0.03, -0.02, -0.01,
        0.00, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06,
        0.07, 0.08, 0.09, 0.10, 0.02, -0.02, 0.01,
    ]
    state = {
        "cash": 1000,
        "initial_capital": 2000,
        "positions": {
            "000001": {"quantity": 10, "avg_price": 50, "current_price": 50},
            "000002": {"quantity": 10, "avg_price": 50, "current_price": 50},
        },
    }

    result = engine.portfolio_risk(
        state,
        risk_limits={"max_position_pct": 0.2, "max_gross_exposure_pct": 95},
    )

    assert result["var_95"] == pytest.approx(-8.0, abs=0.01)
    assert result["expected_shortfall_pct"] == pytest.approx(-9.0, abs=0.01)
    assert result["concentration_pct"] == 50.0
    assert result["max_position_equity_pct"] == 25.0
    assert result["gross_exposure_pct"] == 50.0
    assert result["risk_budget_usage_pct"] == 125.0
    assert result["stress_loss_pct"] == -2.5
    assert result["stress_scenario"]


def test_risk_snapshot_uses_current_sync_quotes(monkeypatch):
    projection = {
        "ledger_authority": "f5",
        "account": {"cash": 1_000, "initial_capital": 2_000},
        "positions": [{
            "code": "000507",
            "quantity": 100,
            "avg_price": 4.50,
            "current_price": 4.98,
        }],
    }
    monkeypatch.setattr(
        risk_runner,
        "load_active_account_projection",
        lambda *_args, **_kwargs: projection,
        raising=False,
    )
    result = risk_runner.action_portfolio_risk()

    assert result["data"]["total_equity"] == 1_498
    assert result["data"]["ledger_authority"] == "f5"
