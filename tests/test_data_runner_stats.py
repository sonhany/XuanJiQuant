from scripts import data_runner


class _StatsCache:
    def get(self, key):
        if key == "stock:universe":
            return ["000001", "000002"]
        return None

    def keys(self, pattern):
        assert pattern == "kline:*:d"
        return [
            "kline:000001:d",
            "kline:000002:d",
            "kline:300029:d",
        ]

    def size(self):
        return 3


def test_stats_separate_current_universe_coverage_from_historical_kline_keys(monkeypatch):
    monkeypatch.setattr(data_runner, "cache", _StatsCache())

    result = data_runner.action_stats()

    assert result["success"] is True
    assert result["data"]["universe_size"] == 2
    assert result["data"]["kline_count"] == 2
    assert result["data"]["kline_total_count"] == 3
    assert result["data"]["kline_extra_count"] == 1
    assert result["data"]["kline_extra_codes"] == ["300029"]
