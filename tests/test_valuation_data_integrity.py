from quant.data.cache import MemoryCache
from quant.valuation.data import ValuationDataProvider


class _TdxSource:
    @staticmethod
    def fetch_klines(code, *, count, period):
        assert code == "600519"
        assert period == "1d"
        return [
            {"date": "20260102", "close": 10.0},
            {"date": "20260105", "close": 11.0},
            {"date": "20260106", "close": 12.0},
            {"date": "20260107", "close": 13.0},
        ]


def test_valuation_history_persists_merged_daily_bars_in_date_order():
    cache = MemoryCache()
    cache.set(
        "kline:600519:d",
        [
            {"date": "20260106", "close": 12.0},
            {"date": "20260107", "close": 13.0},
        ],
    )
    provider = ValuationDataProvider(cache=cache, tdx_source=_TdxSource())
    try:
        provider.get_daily_history("600519", count=4, min_samples=1)
    finally:
        provider.close()

    stored = cache.get("kline:600519:d")
    assert [row["date"] for row in stored] == [
        "20260102",
        "20260105",
        "20260106",
        "20260107",
    ]
