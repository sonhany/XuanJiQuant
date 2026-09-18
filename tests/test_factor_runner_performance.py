from scripts import factor_runner


def test_factor_data_version_reuses_short_lived_metadata(monkeypatch):
    calls = []

    class FakeCache:
        def get(self, key):
            calls.append(key)
            return [
                {"date": "20260729", "close": 10.0},
                {"date": "20260730", "close": 10.2},
            ]

    monkeypatch.setattr(factor_runner, "cache", FakeCache())
    monkeypatch.setattr(factor_runner, "_FACTOR_DATA_VERSION_CACHE", {}, raising=False)

    first = factor_runner._factor_data_version(["000001"])
    second = factor_runner._factor_data_version(["000001"])

    assert first == second == [["000001", 2, "20260730", "10.2"]]
    assert calls == ["kline:000001:d"]


def test_supplement_codes_skips_market_scan_when_requested_pool_is_valid(monkeypatch):
    class FakeCache:
        def get(self, key):
            return [{"date": "20260730", "close": 10.2}]

        def keys(self, pattern):
            raise AssertionError("full market key scan must not run")

    monkeypatch.setattr(factor_runner, "cache", FakeCache())
    monkeypatch.setattr(factor_runner, "_FACTOR_DATA_VERSION_CACHE", {}, raising=False)

    assert factor_runner._supplement_codes(
        ["000001", "600036", "601318"], min_count=3, max_count=15
    ) == ["000001", "600036", "601318"]
