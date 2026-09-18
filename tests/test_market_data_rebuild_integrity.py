from quant.data.cache import SqliteCache
from quant.data.daily_summary import ensure_table
from scripts import rebuild_market_data


def make_cache(tmp_path):
    return SqliteCache(db_path=str(tmp_path / "quant-test.db"))


def test_restore_universe_from_daily_summary_recovers_codes_and_names(tmp_path):
    cache = make_cache(tmp_path)
    ensure_table(cache)
    conn = cache._conn
    conn.execute(
        """
        INSERT INTO stock_daily_summary
            (code, name, latest_date, close, prev_close, change_pct, volume, amount, updated_at)
        VALUES
            ('600519', '贵州茅台', '20260708', 1199.3, 1188.8, 0.88, 100, 120000, 'now'),
            ('920001', '无效920', '20260708', 1, 1, 0, 1, 1, 'now'),
            ('000001', '平安银行', '20260708', 10.6, 10.47, 1.24, 100, 1060, 'now')
        """
    )
    conn.commit()

    restored = rebuild_market_data.restore_universe_from_daily_summary(cache)

    assert restored == ["600519", "000001"]
    assert cache.get("stock:universe") == ["600519", "000001"]
    assert cache.get("stock:name:600519") == "贵州茅台"
    assert cache.get("stock:name:000001") == "平安银行"
    assert cache.get("stock:name:920001") is None


def test_cleanup_invalid_market_data_removes_unsupported_and_empty_keys(tmp_path):
    cache = make_cache(tmp_path)
    cache.set("stock:universe", ["600519", "920001", "000001"])
    cache.set("stock:name:600519", "贵州茅台")
    cache.set("stock:name:920001", "无效920")
    cache.set("kline:600519:d", [{"date": "20260708", "close": 1199.3}])
    cache.set("kline:920001:d", [{"date": "20260708", "close": 1}])
    cache.set("kline:000001:d", [])

    result = rebuild_market_data.cleanup_invalid_market_data(cache, ["600519"])

    assert result["removed_keys"] >= 3
    assert cache.get("stock:universe") == ["600519"]
    assert cache.get("stock:name:920001") is None
    assert cache.get("kline:920001:d") is None
    assert cache.get("kline:000001:d") is None
