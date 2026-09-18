import pytest


def test_normalizer_rejects_duplicate_symbol_date():
    from quant.qlib.normalizer import DataQualityError, normalize_daily_bars

    rows = [
        {
            "instrument": "SH600000",
            "datetime": "2026-01-02",
            "open": 10,
            "high": 11,
            "low": 9,
            "close": 10,
            "volume": 1,
            "amount": 10,
        },
        {
            "instrument": "SH600000",
            "datetime": "2026-01-02",
            "open": 10,
            "high": 11,
            "low": 9,
            "close": 10,
            "volume": 1,
            "amount": 10,
        },
    ]

    with pytest.raises(DataQualityError, match="duplicate"):
        normalize_daily_bars(rows)


def test_normalizer_adds_research_metadata():
    from quant.qlib.normalizer import normalize_daily_bars

    frame = normalize_daily_bars(
        [
            {
                "instrument": "SH600000",
                "datetime": "2026-01-02",
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10.5,
                "volume": 100,
                "amount": 1050,
                "source": "unit",
            }
        ],
        data_version="unit-v1",
    )

    assert frame.loc[0, "factor"] == 1.0
    assert frame.loc[0, "data_version"] == "unit-v1"
    assert frame.loc[0, "source"] == "unit"


def test_normalizer_preserves_point_in_time_fields():
    from quant.qlib.normalizer import normalize_daily_bars

    frame = normalize_daily_bars(
        [
            {
                "instrument": "SH600000",
                "datetime": "2026-01-02",
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10,
                "volume": 100,
                "amount": 1000,
                "tradable": True,
                "is_st": False,
                "st_unknown": False,
                "listed": True,
                "delisted": False,
            }
        ]
    )

    assert frame.loc[0, "tradable"] == 1
    assert frame.loc[0, "listed"] == 1
    assert frame.loc[0, "is_st"] == 0
