import pandas as pd
import pytest

from quant.factor.dsl import compute_factor


def _frame():
    return pd.DataFrame(
        {
            "open": [10.0, 11.0, 12.0],
            "high": [11.0, 12.0, 13.0],
            "low": [9.0, 10.0, 11.0],
            "close": [10.0, 12.0, 15.0],
            "volume": [100.0, 120.0, 150.0],
            "amount": [1000.0, 1440.0, 2250.0],
        }
    )


def test_factor_dsl_computes_deterministic_expression_without_agent():
    dsl = {
        "type": "op",
        "operator": "/",
        "left": {"type": "column", "name": "close"},
        "right": {
            "type": "func",
            "name": "rolling_mean",
            "args": [{"type": "column", "name": "close"}],
            "window": 2,
        },
    }

    result = compute_factor(_frame(), dsl)

    assert result.round(6).tolist() == [1.0, 1.090909, 1.111111]


def test_factor_dsl_rejects_unapproved_function():
    with pytest.raises(ValueError, match="不允许的函数"):
        compute_factor(
            _frame(),
            {
                "type": "func",
                "name": "eval",
                "args": [{"type": "column", "name": "close"}],
            },
        )
