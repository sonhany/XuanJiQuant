from __future__ import annotations

import hashlib

import pytest

from quant.data.cache import MemoryCache


def _bars(end: str, *, count: int = 35, volume: float = 1000.0):
    return [
        {
            "date": f"202607{(index % 28) + 1:02d}" if index < count - 1 else end,
            "open": 10.0,
            "high": 10.5,
            "low": 9.5,
            "close": 10.0,
            "volume": volume,
            "amount": 10000.0,
        }
        for index in range(count)
    ]


def _publish(cache: MemoryCache, codes: list[str], *, as_of: str = "2026-08-13"):
    from quant.data.snapshot import DataSnapshot, publish_snapshot

    universe_version = hashlib.sha256(",".join(codes).encode("utf-8")).hexdigest()
    publish_snapshot(
        cache,
        DataSnapshot(
            snapshot_id="a-share-daily-20260813-test",
            dataset="a_share_daily",
            as_of=as_of,
            published_at="2026-08-14T13:50:58+08:00",
            universe_version=universe_version,
            expected_count=len(codes),
            available_count=len(codes),
            source_chain=("tdx_quant", "tencent_cross_check"),
            content_hash="d" * 64,
            quality_status="passed",
            freshness_status="fresh",
        ),
    )


def test_factor_input_requires_latest_passed_snapshot():
    from quant.factor.input_contract import FactorInputContractError, load_factor_input_snapshot

    cache = MemoryCache()
    cache.set("stock:universe", ["600519"])

    with pytest.raises(FactorInputContractError) as exc:
        load_factor_input_snapshot(cache, expected_date="20260813")

    assert exc.value.reason_code == "factor_snapshot_missing"


def test_factor_input_rejects_stale_snapshot():
    from quant.factor.input_contract import FactorInputContractError, load_factor_input_snapshot

    cache = MemoryCache()
    cache.set("stock:universe", ["600519"])
    cache.set("kline:600519:d", _bars("20260812"))
    _publish(cache, ["600519"], as_of="2026-08-12")

    with pytest.raises(FactorInputContractError) as exc:
        load_factor_input_snapshot(cache, expected_date="20260813")

    assert exc.value.reason_code == "factor_snapshot_stale"


def test_factor_input_rejects_universe_hash_mismatch():
    from quant.factor.input_contract import FactorInputContractError, load_factor_input_snapshot

    cache = MemoryCache()
    cache.set("stock:universe", ["600519", "000001"])
    cache.set("kline:600519:d", _bars("20260813"))
    cache.set("kline:000001:d", _bars("20260813"))
    _publish(cache, ["600519"])

    with pytest.raises(FactorInputContractError) as exc:
        load_factor_input_snapshot(cache, expected_date="20260813")

    assert exc.value.reason_code == "factor_universe_mismatch"


def test_factor_input_builds_data_and_tradeable_universes():
    from quant.factor.input_contract import load_factor_input_snapshot

    codes = ["600519", "000001", "002808", "300001", "300002"]
    cache = MemoryCache()
    cache.set("stock:universe", codes)
    cache.set("stock:name:600519", "贵州茅台")
    cache.set("stock:name:000001", "ST测试")
    cache.set("stock:name:002808", "恒久退")
    cache.set("stock:name:300001", "零成交")
    cache.set("stock:name:300002", "历史不足")
    cache.set("kline:600519:d", _bars("20260813"))
    cache.set("kline:000001:d", _bars("20260813"))
    cache.set("kline:002808:d", _bars("20260813"))
    cache.set("kline:300001:d", _bars("20260813", volume=0))
    cache.set("kline:300002:d", _bars("20260813", count=10))
    _publish(cache, codes)

    result = load_factor_input_snapshot(
        cache,
        expected_date="20260813",
        minimum_data_coverage=0.95,
        minimum_history_bars=30,
    )

    assert result.data_codes == tuple(codes)
    assert result.eligible_codes == ("600519",)
    assert result.excluded_reasons == {
        "special_treatment_or_delisting": 2,
        "zero_volume": 1,
        "insufficient_history": 1,
    }
    assert result.metadata()["data_version"] == "d" * 64
    assert result.metadata()["universe_policy"] == "current_tradeable_v1"
    assert result.metadata()["promotion_state"] == "research_only"
    assert result.metadata()["execution_authority"] is False


def test_factor_input_and_bars_ignore_dates_after_bound_snapshot():
    from quant.factor.input_contract import governed_daily_bars, load_factor_input_snapshot

    cache = MemoryCache()
    cache.set("stock:universe", ["600519"])
    bars = _bars("20260813")
    bars.append({**bars[-1], "date": "20260814", "close": 99.0})
    cache.set("kline:600519:d", bars)
    _publish(cache, ["600519"])

    snapshot = load_factor_input_snapshot(cache, expected_date="20260813")
    governed = governed_daily_bars(cache, "600519", snapshot)

    assert snapshot.eligible_codes == ("600519",)
    assert governed[-1]["date"] == "20260813"
    assert all(bar["date"] <= "20260813" for bar in governed)


def test_factor_input_reuses_version_bound_derived_contract():
    from quant.factor.input_contract import load_factor_input_snapshot

    class CountingCache(MemoryCache):
        def __init__(self):
            super().__init__()
            self.kline_reads = 0

        def get(self, key):
            if str(key).startswith("kline:"):
                self.kline_reads += 1
            return super().get(key)

    cache = CountingCache()
    cache.set("stock:universe", ["600519"])
    cache.set("kline:600519:d", _bars("20260813"))
    _publish(cache, ["600519"])

    first = load_factor_input_snapshot(cache, expected_date="20260813")
    reads_after_first = cache.kline_reads
    second = load_factor_input_snapshot(cache, expected_date="20260813")

    assert first == second
    assert reads_after_first > 0
    assert cache.kline_reads == reads_after_first


def test_factor_input_read_only_mode_does_not_publish_derived_contract():
    from quant.factor.input_contract import load_factor_input_snapshot

    cache = MemoryCache()
    cache.set("stock:universe", ["600519"])
    cache.set("kline:600519:d", _bars("20260813"))
    _publish(cache, ["600519"])

    result = load_factor_input_snapshot(
        cache,
        expected_date="20260813",
        publish_cache=False,
    )

    assert result.eligible_codes == ("600519",)
    assert cache.keys("factor:input_contract:*") == []
