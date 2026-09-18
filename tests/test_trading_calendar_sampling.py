from scripts import trading_calendar


class FakeCache:
    def __init__(self, rows):
        self.rows = rows
        self.values = {}

    def keys(self, pattern):
        assert pattern == "kline:*:d"
        return list(self.rows)

    def get(self, key):
        return self.values.get(key, self.rows.get(key))

    def set(self, key, value):
        self.values[key] = value


def test_latest_kline_scan_samples_across_full_key_space(monkeypatch):
    rows = {
        f"kline:{index:06d}:d": [
            {"date": "20260710" if index < 550 else "20260807"}
        ]
        for index in range(600)
    }
    monkeypatch.setattr(trading_calendar, "cache", FakeCache(rows))

    assert trading_calendar._scan_latest_kline_date() == "20260807"


def test_calendar_rebuild_includes_dates_outside_first_500_keys(monkeypatch):
    rows = {
        f"kline:{index:06d}:d": [
            {"date": "20260710" if index < 550 else "20260807"}
        ]
        for index in range(600)
    }
    cache = FakeCache(rows)
    monkeypatch.setattr(trading_calendar, "cache", cache)

    dates = trading_calendar.build_trading_calendar(force=True)

    assert dates[-1] == "20260807"


def test_get_trade_dates_revalidates_a_stale_persisted_calendar(monkeypatch):
    historical = [f"202607{day:02d}" for day in range(1, 12)]
    rows = {
        f"kline:{index:06d}:d": [
            {"date": "20260807" if index % 2 == 0 else "20260710"}
        ]
        for index in range(600)
    }
    cache = FakeCache(rows)
    cache.values[trading_calendar.CALENDAR_KEY] = historical
    monkeypatch.setattr(trading_calendar, "cache", cache)
    monkeypatch.setattr(trading_calendar, "_CALENDAR_CHECKED_AT", 0.0)

    dates = trading_calendar.get_trade_dates()

    assert dates[-1] == "20260807"


def test_calendar_rebuild_never_discards_existing_historical_dates(monkeypatch):
    rows = {
        f"kline:{index:06d}:d": [{"date": "20260807"}]
        for index in range(600)
    }
    cache = FakeCache(rows)
    cache.values[trading_calendar.CALENDAR_KEY] = ["20250102", "20250103"]
    monkeypatch.setattr(trading_calendar, "cache", cache)

    dates = trading_calendar.build_trading_calendar(force=True)

    assert dates[0] == "20250102"
    assert dates[-1] == "20260807"
