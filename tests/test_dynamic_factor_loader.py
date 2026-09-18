from copy import deepcopy

import pandas as pd

from quant.factor.dynamic_factor_loader import compute_dynamic_factors, get_approved_factors


class FakeCache:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key):
        return self.values.get(key)


def test_dynamic_factor_loader_reads_only_new_research_namespace():
    fake = FakeCache({
        "research:factor:approved": [
            {"name": "shadow", "promotion_state": "shadow", "dsl": {"type": "column", "name": "close"}},
            {"name": "approved", "promotion_state": "approved", "dsl": {"type": "column", "name": "close"}},
        ],
        "ai:factor:approved": [
            {"name": "legacy", "promotion_state": "approved", "dsl": {"type": "column", "name": "close"}},
        ],
    })
    assert [row["name"] for row in get_approved_factors(fake)] == ["approved"]


def test_dynamic_factor_loader_preserves_existing_columns():
    row = {"name": "close", "promotion_state": "approved", "dsl": {"type": "column", "name": "volume"}}
    fake = FakeCache({"research:factor:approved": [row]})
    before = deepcopy(row)
    frame = pd.DataFrame({"close": [10.0, 11.0], "volume": [100.0, 120.0]})
    output = compute_dynamic_factors(frame, fake)
    assert output["close"].tolist() == [10.0, 11.0]
    assert row == before
