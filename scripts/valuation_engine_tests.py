from __future__ import annotations

import json
import math
import re
import sqlite3
import threading
import time
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest


@pytest.fixture
def temp_cache(tmp_path):
    from quant.data.cache import SqliteCache

    db_path = tmp_path / "valuation.db"
    cache = SqliteCache(db_path=str(db_path))
    assert cache._db_path == str(db_path)
    yield cache
    cache._conn.close()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("600519", "600519"),
        ("SH600519", "600519"),
        ("600519.SH", "600519"),
        ("sz000001", "000001"),
        ("000001.sz", "000001"),
        ("300442.SZ", "300442"),
        ("SZ301308", "301308"),
        ("688981.SH", "688981"),
        ("SH689009", "689009"),
    ],
)
def test_normalize_code_accepts_matching_main_chinext_and_star_formats(
    raw, expected
):
    from quant.valuation.contracts import normalize_code

    assert normalize_code(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "SH000001",
        "000001.SH",
        "SZ600519",
        "600519.SZ",
        "SH300442",
        "300442.SH",
        "SZ688981",
        "688981.SZ",
    ],
)
def test_normalize_code_rejects_exchange_mismatch(raw):
    from quant.valuation.contracts import normalize_code

    assert normalize_code(raw) == ""


@pytest.mark.parametrize(
    "raw",
    [
        "920001",
        "BJ920001",
        "920001.BJ",
        "BJ600519",
        "600519.BJ",
        "430001",
        "830001",
        "123456",
        "600519<script>",
        "<script>",
        "600519&x=1",
        "60051",
        "6005190",
        "",
        None,
    ],
)
def test_normalize_code_rejects_bj_920_html_and_illegal_codes(raw):
    from quant.valuation.contracts import normalize_code

    assert normalize_code(raw) == ""


@pytest.mark.parametrize("status", ["success", "partial", "unavailable", "error"])
def test_model_result_preserves_supported_status_and_missing_values(status):
    from quant.valuation.contracts import model_result

    result = model_result("absolute", status, error="缺少现金流")

    assert result["type"] == "absolute"
    assert result["status"] == status
    assert result["low"] is None
    assert result["mid"] is None
    assert result["high"] is None
    assert result["confidence"] is None
    assert result["error"] == "缺少现金流"


def test_model_result_rejects_unknown_status():
    from quant.valuation.contracts import model_result

    with pytest.raises(ValueError, match="invalid valuation status"):
        model_result("absolute", "ready")


def test_schema_requires_cache_connection_and_lock():
    from quant.valuation.store import ensure_valuation_schema

    class MissingLockCache:
        _conn = sqlite3.connect(":memory:")

    class MissingConnectionCache:
        _lock = threading.RLock()

    try:
        with pytest.raises(TypeError, match="_conn.*_lock"):
            ensure_valuation_schema(MissingLockCache())
        with pytest.raises(TypeError, match="_conn.*_lock"):
            ensure_valuation_schema(MissingConnectionCache())
    finally:
        MissingLockCache._conn.close()


def test_stock_valuation_schema_uses_cache_connection_and_has_unique_key(
    temp_cache,
):
    from quant.valuation.store import ensure_valuation_schema

    original_connection = temp_cache._conn
    assert ensure_valuation_schema(temp_cache) is True
    assert temp_cache._conn is original_connection

    columns = {
        row[1]
        for row in temp_cache._conn.execute(
            "PRAGMA table_info(stock_valuations)"
        ).fetchall()
    }
    assert {
        "valuation_id",
        "code",
        "name",
        "valuation_type",
        "status",
        "data_date",
        "report_period",
        "formula_version",
        "model_version",
        "prompt_version",
        "input_payload",
        "output_payload",
        "created_at",
    }.issubset(columns)

    index_rows = temp_cache._conn.execute(
        "PRAGMA index_list(stock_valuations)"
    ).fetchall()
    indexes = {row[1] for row in index_rows}
    assert "idx_stock_valuations_code_type_created" in indexes
    assert "uq_stock_valuations_id_type" in indexes
    unique_row = next(
        row for row in index_rows if row[1] == "uq_stock_valuations_id_type"
    )
    assert unique_row[2] == 1
    unique_columns = [
        row[2]
        for row in temp_cache._conn.execute(
            "PRAGMA index_info(uq_stock_valuations_id_type)"
        ).fetchall()
    ]
    assert unique_columns == ["valuation_id", "valuation_type"]


def test_stock_valuation_round_trip_preserves_real_chinese_json(temp_cache):
    from quant.valuation.store import latest_valuation, save_valuation

    valuation_id = save_valuation(
        temp_cache,
        {
            "code": "300442.SZ",
            "name": "润泽科技",
            "valuation_type": "absolute",
            "status": "success",
            "data_date": "20260710",
            "report_period": "20260331",
            "formula_version": "absolute-v1",
            "model_version": "",
            "prompt_version": "",
            "input": {"price": 82.25, "说明": "最新价格"},
            "output": {"low": 75.0, "mid": 88.0, "high": 102.0},
        },
    )

    raw = temp_cache._conn.execute(
        """
        SELECT input_payload
        FROM stock_valuations
        WHERE valuation_id = ?
        """,
        (valuation_id,),
    ).fetchone()[0]
    assert "说明" in raw
    assert "最新价格" in raw
    assert "\\u8bf4\\u660e" not in raw.lower()
    assert "\ufffd" not in raw
    assert json.loads(raw)["说明"] == "最新价格"

    latest = latest_valuation(temp_cache, "SZ300442", "absolute")
    assert latest["valuation_id"] == valuation_id
    assert latest["code"] == "300442"
    assert latest["name"] == "润泽科技"
    assert latest["input"]["price"] == 82.25
    assert latest["output"]["mid"] == 88.0


def test_json_normalizes_decimal_and_dates_explicitly(temp_cache):
    from quant.valuation.store import latest_valuation, save_valuation

    save_valuation(
        temp_cache,
        {
            "code": "600519",
            "valuation_id": "typed-json",
            "valuation_type": "market",
            "status": "success",
            "input": {
                "amount": Decimal("123.45"),
                "trade_date": date(2026, 7, 10),
                "calculated_at": datetime(
                    2026, 7, 12, 10, 30, tzinfo=timezone.utc
                ),
            },
            "output": {"mid": Decimal("1500.50")},
        },
    )

    latest = latest_valuation(temp_cache, "600519", "market")
    assert latest["input"]["amount"] == 123.45
    assert latest["input"]["trade_date"] == "2026-07-10"
    assert latest["input"]["calculated_at"] == "2026-07-12T10:30:00+00:00"
    assert latest["output"]["mid"] == 1500.5


def test_json_rejects_unknown_object_instead_of_stringifying(temp_cache):
    from quant.valuation.store import save_valuation

    with pytest.raises(TypeError, match="unsupported JSON value"):
        save_valuation(
            temp_cache,
            {
                "code": "600519",
                "valuation_type": "market",
                "status": "success",
                "input": {"bad": object()},
                "output": {},
            },
        )


def test_created_at_is_generated_by_store_and_latest_uses_id_order(temp_cache):
    from quant.valuation.store import latest_valuation, save_valuation

    first_id = save_valuation(
        temp_cache,
        {
            "code": "600519",
            "valuation_type": "relative",
            "status": "partial",
            "created_at": "2999-12-31T23:59:59+00:00",
            "input": {},
            "output": {"mid": None},
        },
    )
    second_id = save_valuation(
        temp_cache,
        {
            "code": "600519",
            "valuation_type": "relative",
            "status": "success",
            "created_at": "not-a-date",
            "input": {},
            "output": {"mid": 1600.0},
        },
    )

    stored = temp_cache._conn.execute(
        """
        SELECT valuation_id, created_at
        FROM stock_valuations
        ORDER BY id ASC
        """
    ).fetchall()
    assert stored[0][0] == first_id
    assert stored[1][0] == second_id
    assert all(value not in {"2999-12-31T23:59:59+00:00", "not-a-date"} for _, value in stored)
    assert all(
        re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00",
            value,
        )
        for _, value in stored
    )

    temp_cache._conn.execute(
        """
        UPDATE stock_valuations
        SET created_at = '9999-12-31T23:59:59.999999+00:00'
        WHERE valuation_id = ?
        """,
        (first_id,),
    )
    temp_cache._conn.commit()
    latest = latest_valuation(temp_cache, "600519", "relative")
    assert latest["valuation_id"] == second_id
    assert latest["output"]["mid"] == 1600.0


def test_idempotent_retry_preserves_first_created_at_and_latest_id_order(
    temp_cache, monkeypatch
):
    import quant.valuation.store as valuation_store

    generated_times = iter(
        [
            "2026-07-12T10:00:00.000000+00:00",
            "2026-07-12T10:01:00.000000+00:00",
            "2026-07-12T10:02:00.000000+00:00",
        ]
    )
    monkeypatch.setattr(valuation_store, "_now", lambda: next(generated_times))

    base = {
        "code": "600519",
        "valuation_type": "relative",
        "status": "success",
        "input": {},
    }
    valuation_store.save_valuation(
        temp_cache,
        {
            **base,
            "valuation_id": "task-a",
            "output": {"mid": 1500.0},
        },
    )
    valuation_store.save_valuation(
        temp_cache,
        {
            **base,
            "valuation_id": "task-b",
            "output": {"mid": 1600.0},
        },
    )
    valuation_store.save_valuation(
        temp_cache,
        {
            **base,
            "valuation_id": "task-a",
            "output": {"mid": 1550.0},
        },
    )

    rows = {
        row[0]: row[1]
        for row in temp_cache._conn.execute(
            """
            SELECT valuation_id, created_at
            FROM stock_valuations
            WHERE valuation_type = 'relative'
            """
        ).fetchall()
    }
    assert rows["task-a"] == "2026-07-12T10:00:00.000000+00:00"
    assert rows["task-b"] == "2026-07-12T10:01:00.000000+00:00"

    latest = valuation_store.latest_valuation(
        temp_cache, "600519", "relative"
    )
    assert latest["valuation_id"] == "task-b"
    assert latest["output"]["mid"] == 1600.0


def test_latest_valuation_raises_on_corrupt_json(temp_cache):
    from quant.valuation.store import (
        ValuationDataIntegrityError,
        latest_valuation,
        save_valuation,
    )

    valuation_id = save_valuation(
        temp_cache,
        {
            "code": "600519",
            "valuation_type": "absolute",
            "status": "success",
            "input": {},
            "output": {"mid": 1500.0},
        },
    )
    temp_cache._conn.execute(
        """
        UPDATE stock_valuations
        SET output_payload = '{broken'
        WHERE valuation_id = ?
        """,
        (valuation_id,),
    )
    temp_cache._conn.commit()

    with pytest.raises(
        ValuationDataIntegrityError,
        match=r"output_payload.*valuation_id",
    ):
        latest_valuation(temp_cache, "600519", "absolute")


def test_save_valuation_is_idempotent_for_same_id_and_type(temp_cache):
    from quant.valuation.store import latest_valuation, save_valuation

    request = {
        "valuation_id": "retry-valuation-1",
        "code": "600519",
        "name": "贵州茅台",
        "valuation_type": "relative",
        "status": "partial",
        "input": {"attempt": 1},
        "output": {"mid": None},
    }
    first_id = save_valuation(temp_cache, request)
    second_id = save_valuation(
        temp_cache,
        {
            **request,
            "status": "success",
            "input": {"attempt": 2},
            "output": {"mid": 1600.0},
        },
    )

    assert first_id == second_id == "retry-valuation-1"
    count = temp_cache._conn.execute(
        """
        SELECT COUNT(*)
        FROM stock_valuations
        WHERE valuation_id = ? AND valuation_type = ?
        """,
        ("retry-valuation-1", "relative"),
    ).fetchone()[0]
    assert count == 1
    latest = latest_valuation(temp_cache, "600519", "relative")
    assert latest["status"] == "success"
    assert latest["input"]["attempt"] == 2
    assert latest["output"]["mid"] == 1600.0


def test_concurrent_idempotent_retries_keep_single_row(temp_cache):
    from quant.valuation.store import save_valuation

    worker_count = 8
    barrier = threading.Barrier(worker_count)
    errors = []

    def worker(attempt):
        try:
            barrier.wait(timeout=5)
            save_valuation(
                temp_cache,
                {
                    "valuation_id": "concurrent-retry",
                    "code": "300442",
                    "name": "润泽科技",
                    "valuation_type": "market",
                    "status": "success",
                    "input": {"attempt": attempt},
                    "output": {"mid": 80.0 + attempt},
                },
            )
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(attempt,))
        for attempt in range(worker_count)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors
    assert all(not thread.is_alive() for thread in threads)
    count = temp_cache._conn.execute(
        """
        SELECT COUNT(*)
        FROM stock_valuations
        WHERE valuation_id = ? AND valuation_type = ?
        """,
        ("concurrent-retry", "market"),
    ).fetchone()[0]
    assert count == 1


class FakeValuationCache:
    def __init__(self, values=None, *, now=1_000_000.0):
        self.values = dict(values or {})
        self.expiries = {}
        self.set_calls = []
        self.keys_calls = 0
        self._now = float(now)
        self._lock = threading.RLock()

    def advance(self, seconds):
        with self._lock:
            self._now += float(seconds)

    def _purge(self, key):
        expiry = self.expiries.get(key)
        if expiry is not None and self._now >= expiry:
            self.values.pop(key, None)
            self.expiries.pop(key, None)

    def get(self, key):
        with self._lock:
            self._purge(key)
            return self.values.get(key)

    def set(self, key, value, ttl=None):
        with self._lock:
            self.values[key] = value
            self.expiries[key] = (
                self._now + float(ttl) if ttl is not None else None
            )
            self.set_calls.append((key, value, ttl))

    def keys(self, pattern=""):
        import fnmatch

        with self._lock:
            self.keys_calls += 1
            for key in list(self.values):
                self._purge(key)
            return [
                key for key in self.values if fnmatch.fnmatch(key, pattern)
            ]


class FakeValuationSource:
    def __init__(
        self,
        *,
        stock_info=None,
        snapshots=None,
        klines=None,
        allow_klines=None,
        snapshot_error=None,
        delay=0.0,
        snapshot_delay=0.0,
        kline_delay=0.0,
    ):
        self.stock_info = dict(stock_info or {})
        self.snapshots = dict(snapshots or {})
        self.klines = dict(klines or {})
        self.allow_klines = dict(allow_klines or {})
        self.snapshot_error = snapshot_error
        self.delay = delay
        self.snapshot_delay = snapshot_delay
        self.kline_delay = kline_delay
        self.info_calls = []
        self.snapshot_calls = []
        self.kline_calls = []
        self.timeouts = []
        self._active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def _enter(self):
        with self._lock:
            self._active += 1
            self.max_active = max(self.max_active, self._active)

    def _leave(self):
        with self._lock:
            self._active -= 1

    def fetch_stock_info(self, code, field_list=None, timeout=None):
        self._enter()
        try:
            if self.delay:
                time.sleep(self.delay)
            self.info_calls.append(code)
            self.timeouts.append(("stock_info", timeout))
            value = self.stock_info.get(code)
            if isinstance(value, Exception):
                raise value
            return dict(value or {})
        finally:
            self._leave()

    def fetch_snapshot(self, code, timeout=None):
        self._enter()
        try:
            if self.snapshot_delay:
                time.sleep(self.snapshot_delay)
            self.snapshot_calls.append(code)
            self.timeouts.append(("snapshot", timeout))
            if self.snapshot_error:
                raise self.snapshot_error
            value = self.snapshots.get(code)
            if isinstance(value, Exception):
                raise value
            return dict(value or {})
        finally:
            self._leave()

    def fetch_klines(self, code, count=300, period="1d", timeout=None):
        self._enter()
        try:
            if self.kline_delay:
                time.sleep(self.kline_delay)
            self.kline_calls.append((code, count, period))
            self.timeouts.append(("kline", timeout))
            value = self.klines.get(code)
            if isinstance(value, Exception):
                raise value
            return [dict(row) for row in (value or [])]
        finally:
            self._leave()

    def fetch_klines_allow_price_jumps(
        self, code, count=300, period="1d", timeout=None
    ):
        self._enter()
        try:
            self.kline_calls.append((code, count, f"{period}:allow_price_jumps"))
            self.timeouts.append(("kline_allow_price_jumps", timeout))
            value = self.allow_klines.get(code)
            if isinstance(value, Exception):
                raise value
            return [dict(row) for row in (value or [])]
        finally:
            self._leave()


def _tdx_info(
    code,
    *,
    name=None,
    eps="1.20",
    bvps="5.00",
    revenue="1000",
    shares="10000",
    is_st="0",
):
    return {
        "Name": name or f"样本{code}",
        "J_mgsy": eps,
        "J_mgjzc": bvps,
        "J_yysy": revenue,
        "J_jly": "200",
        "J_jyxjl": "300",
        "J_zgb": shares,
        "J_zzc": "5000",
        "J_cqfz": "400",
        "rs_hycode_sim": "C39",
        "IsSTGP": is_st,
        "J_bgrq": "20260331",
        "UpdateTime": "20260710",
    }


def test_normalize_tdx_fundamentals_maps_declared_10k_units_and_missing_fields():
    from quant.valuation.data import normalize_tdx_fundamentals

    raw = {
        "Name": "润泽科技",
        "J_mgsy": "1.42",
        "J_mgjzc": "8.74",
        "J_yysy": "183957.77",
        "J_jly": "58222.96",
        "J_jyxjl": "131585.34",
        "J_zgb": "164104.20",
        "J_zzc": "4709551.50",
        "J_cqfz": "221075.45",
        "rs_hycode_sim": "X4203",
        "J_bgrq": "20260331",
        "UpdateTime": "20260710",
    }

    out = normalize_tdx_fundamentals("300442", raw)

    assert out["eps"] == 1.42
    assert out["bvps"] == 8.74
    assert out["total_shares"] == 1_641_042_000
    assert out["revenue"] == 1_839_577_700
    assert out["net_profit"] == 582_229_600
    assert out["operating_cash_flow"] == 1_315_853_400
    assert out["industry_code"] == "X4203"
    assert out["report_period"] == "20260331"
    assert out["data_date"] == "20260710"
    assert out["units"]["J_zgb"] == {"input": "10k_shares", "scale": 10000.0}
    assert out["units"]["J_yysy"] == {"input": "10k_cny", "scale": 10000.0}
    assert out["source"] == "tdx_quant_stock_info"
    assert out["status"] == "success"

    missing = normalize_tdx_fundamentals("300442", {"Name": "润泽科技"})
    assert missing["total_shares"] is None
    assert missing["revenue"] is None
    assert missing["status"] == "partial"
    assert any("J_zgb" in warning for warning in missing["warnings"])
    assert any("J_yysy" in warning for warning in missing["warnings"])


def test_quote_prefers_tdx_snapshot_and_explicitly_falls_back_to_daily_summary():
    from quant.valuation.data import ValuationDataProvider

    source = FakeValuationSource(
        snapshots={
            "300442": {
                "price": 82.25,
                "open": 80.0,
                "high": 83.0,
                "low": 79.5,
                "prev_close": 80.5,
                "volume": 1234,
                "amount": 998877.0,
                "source": "tdx_quant",
                "timestamp": "20260712103000",
            }
        }
    )
    provider = ValuationDataProvider(
        cache=FakeValuationCache({"stock:name:300442": "润泽科技"}),
        tdx_source=source,
        now_fn=lambda: datetime(2026, 7, 12, 10, 31),
    )

    live = provider.get_quote("300442")

    assert live["price"] == 82.25
    assert live["source"] == "tdx_quant"
    assert live["as_of"] == "20260712103000"
    assert live["freshness"] == "live"
    assert live["status"] == "success"

    fallback_cache = FakeValuationCache(
        {
            "stock:name:300442": "润泽科技",
            "valuation:daily_summary:300442": {
                "code": "300442",
                "name": "润泽科技",
                "latest_date": "20260711",
                "close": 80.5,
                "prev_close": 79.0,
                "change_pct": 1.9,
                "volume": 1000,
                "amount": 80000.0,
            },
        }
    )
    fallback_provider = ValuationDataProvider(
        cache=fallback_cache,
        tdx_source=FakeValuationSource(
            snapshot_error=TimeoutError("tdx snapshot timeout")
        ),
    )

    fallback = fallback_provider.get_quote("300442")

    assert fallback["price"] == 80.5
    assert fallback["source"] == "stock_daily_summary"
    assert fallback["as_of"] == "20260711"
    assert fallback["freshness"] == "previous_close"
    assert fallback["status"] == "partial"
    assert any("tdx" in warning.lower() for warning in fallback["warnings"])


def test_intraday_tdx_snapshot_without_timestamp_is_live_when_trading_is_active():
    from quant.valuation.data import ValuationDataProvider

    provider = ValuationDataProvider(
        cache=FakeValuationCache(),
        tdx_source=FakeValuationSource(
            snapshots={
                "300442": {
                    "price": 80.35,
                    "prev_close": 79.90,
                    "volume": 1_000_000,
                    "amount": 80_000_000,
                    "source": "tdx_quant",
                }
            }
        ),
        now_fn=lambda: datetime(2026, 7, 13, 10, 26, 33),
    )

    quote = provider.get_quote("300442")

    assert quote["freshness"] == "live"
    assert quote["status"] == "success"
    assert quote["as_of"] == "20260713102633"


def test_financial_history_sanitizes_non_finite_values_and_exposes_dates():
    from quant.valuation.data import ValuationDataProvider

    cache = FakeValuationCache(
        {
            "fin:abstract:300442": [
                {
                    "report_date": "20251231",
                    "ann_date": "20260320",
                    "roe": float("nan"),
                    "revenue_growth": float("inf"),
                    "nested": {"bad": -float("inf"), "ok": 3.2},
                },
                {
                    "report_date": "20260331",
                    "ann_date": "20260428",
                    "roe": 12.5,
                },
            ]
        }
    )
    provider = ValuationDataProvider(
        cache=cache, tdx_source=FakeValuationSource()
    )

    out = provider.get_financial_history("300442")

    assert out["status"] == "success"
    assert out["report_period"] == "20260331"
    assert out["data_date"] == "20260428"
    assert out["records"][0]["roe"] is None
    assert out["records"][0]["revenue_growth"] is None
    assert out["records"][0]["nested"]["bad"] is None
    assert out["records"][0]["nested"]["ok"] == 3.2
    assert not any(
        isinstance(value, float) and not math.isfinite(value)
        for record in out["records"]
        for value in record.values()
    )


def test_financial_history_enriches_cached_ratios_with_disclosed_cash_flow_fields():
    from quant.valuation.data import ValuationDataProvider

    cache = FakeValuationCache(
        {
            "fin:abstract:300442": [
                {
                    "report_date": "20251231",
                    "revenue_growth": 29.98,
                    "roe": 16.2,
                }
            ]
        }
    )

    def fetch_financials(_code, include_tushare=False):
        assert include_tushare is False
        return {
            "akshare_records": [
                {
                    "report_date": "20251231",
                    "revenue": 5_673_679_684,
                    "net_profit": 5_049_938_664,
                    "operating_cash_flow": 3_291_906_916,
                    "shareholder_fcf_per_share": 3.05939,
                }
            ],
            "warnings": [],
        }

    provider = ValuationDataProvider(
        cache=cache,
        tdx_source=FakeValuationSource(),
        financial_fetcher=fetch_financials,
        now_fn=lambda: datetime(2026, 7, 13, 10, 30),
    )

    out = provider.get_financial_history("300442")

    assert out["status"] == "success"
    assert out["data_date"] is None
    assert out["date_basis"] == "report_period"
    assert out["retrieved_at"] == "20260713103000"
    assert out["records"][0]["revenue_growth"] == 29.98
    assert out["records"][0]["shareholder_fcf_per_share"] == 3.05939
    assert not any("lacks data date" in warning for warning in out["warnings"])
    assert cache.get("fin:abstract:300442")[0]["revenue"] == 5_673_679_684


def test_service_auto_enriches_legacy_financial_cache_for_new_stock(monkeypatch):
    from quant.data import financial_reconciler
    from quant.valuation.service import ValuationService

    cache = FakeValuationCache(
        {
            "fin:abstract:600519": [
                {
                    "report_date": "20251231",
                    "revenue_growth": 8.5,
                    "roe": 31.0,
                }
            ],
            "valuation:financial_history:600519": {
                "code": "600519",
                "records": [
                    {
                        "report_date": "20251231",
                        "revenue_growth": 8.5,
                        "roe": 31.0,
                    }
                ],
                "sample_length": 1,
                "report_period": "20251231",
                "data_date": None,
                "source": "fin_abstract_cache",
                "status": "partial",
                "warnings": ["financial history lacks data date"],
            },
        }
    )
    fetch_calls = []

    def fetch_financials(code, include_tushare=False):
        fetch_calls.append(code)
        return {
            "akshare_records": [
                {
                    "report_date": "20251231",
                    "revenue": 180_000_000_000,
                    "net_profit": 90_000_000_000,
                    "operating_cash_flow": 100_000_000_000,
                    "shareholder_fcf_per_share": 45.0,
                }
            ],
            "warnings": [],
        }

    monkeypatch.setattr(
        financial_reconciler, "fetch_financial_crosscheck", fetch_financials
    )
    service = ValuationService(cache=cache)

    out = service.data_provider.get_financial_history("600519")

    assert fetch_calls == ["600519"]
    assert out["status"] == "success"
    assert out["date_basis"] == "report_period"
    assert out["records"][0]["shareholder_fcf_per_share"] == 45.0
    assert cache.get("fin:abstract:600519")[0]["revenue"] == 180_000_000_000


def test_industry_cache_miss_refreshes_once_and_timeout_degrades():
    from quant.valuation.data import ValuationDataProvider

    cache = FakeValuationCache()
    refresh_calls = []

    def refresh_industry(target_cache):
        refresh_calls.append(True)
        target_cache.set("stock:industry:300442", "C|软件和信息技术服务业")
        return 1

    provider = ValuationDataProvider(
        cache=cache,
        tdx_source=FakeValuationSource(),
        industry_loader=refresh_industry,
        industry_timeout=0.1,
    )
    first = provider.get_industry("300442")
    second = provider.get_industry("300442")

    assert first["industry"] == "C|软件和信息技术服务业"
    assert first["source"] == "baostock_refresh"
    assert second["source"] == "baostock_cache"
    assert len(refresh_calls) == 1

    slow_cache = FakeValuationCache()

    def slow_refresh(_cache):
        time.sleep(0.08)
        return 0

    slow_provider = ValuationDataProvider(
        cache=slow_cache,
        tdx_source=FakeValuationSource(),
        industry_loader=slow_refresh,
        industry_timeout=0.005,
    )
    degraded = slow_provider.get_industry("300442")

    assert degraded["industry"] is None
    assert degraded["status"] == "partial"
    assert any("timeout" in warning.lower() for warning in degraded["warnings"])


def test_daily_history_reports_actual_coverage_and_latest_date():
    from quant.valuation.data import ValuationDataProvider

    bars = [
        {"date": "20260708", "close": 78.0, "volume": 10, "amount": 780.0},
        {"date": "20260709", "close": 79.0, "volume": 20, "amount": 1580.0},
        {"date": "20260710", "close": 80.0, "volume": 30, "amount": 2400.0},
    ]
    cache = FakeValuationCache({"kline:300442:d": bars})
    provider = ValuationDataProvider(
        cache=cache, tdx_source=FakeValuationSource()
    )

    out = provider.get_daily_history("300442", min_samples=5)

    assert out["bars"] == bars
    assert out["sample_length"] == 3
    assert out["start_date"] == "20260708"
    assert out["latest_date"] == "20260710"
    assert out["coverage"]["required_samples"] == 5
    assert out["coverage"]["actual_samples"] == 3
    assert out["coverage"]["complete"] is False
    assert out["status"] == "partial"


def test_daily_history_backfills_short_cache_and_preserves_adjusted_close():
    from quant.valuation.data import ValuationDataProvider

    cached = [
        {"date": f"2025{i // 28 + 1:02d}{i % 28 + 1:02d}", "close": 30.0}
        for i in range(300)
    ]
    fetched = [
        {
            "date": f"{20220001 + i:08d}",
            "close": 20.0 + i / 100,
            "factor": 0.5 if i < 400 else 1.0,
        }
        for i in range(900)
    ]
    source = FakeValuationSource(klines={"300442": fetched})
    cache = FakeValuationCache({"kline:300442:d": cached})
    provider = ValuationDataProvider(cache=cache, tdx_source=source)

    out = provider.get_daily_history("300442", count=900, min_samples=720)

    assert out["sample_length"] >= 720
    assert out["coverage"]["complete"] is True
    assert out["source"] == "kline_cache+tdx_quant"
    assert any(row.get("adjusted_close") is not None for row in out["bars"])
    assert source.kline_calls[0] == ("300442", 900, "1d")
    assert len(cache.get("kline:300442:d")) >= 720


def test_peer_collection_is_bounded_concurrent_filtered_and_cached():
    from quant.valuation.data import ValuationDataProvider

    target = "300442"
    candidate_codes = [f"60{i:04d}" for i in range(30)]
    values = {
        f"stock:industry:{target}": "C|计算机制造业",
        f"stock:name:{target}": "润泽科技",
    }
    stock_info = {target: _tdx_info(target, name="润泽科技")}
    snapshots = {}
    for rank, code in enumerate(candidate_codes):
        values[f"stock:industry:{code}"] = "C|计算机制造业"
        values[f"valuation:daily_summary:{code}"] = {
            "code": code,
            "name": f"样本{code}",
            "latest_date": "20260711",
            "close": 10.0 + rank,
            "amount": float(1_000_000 - rank),
        }
        stock_info[code] = _tdx_info(code)
        snapshots[code] = {
            "price": 10.0 + rank,
            "source": "tdx_quant",
            "timestamp": "20260712103000",
        }

    stock_info[candidate_codes[0]] = _tdx_info(
        candidate_codes[0], name="ST风险股", is_st="1"
    )
    stock_info[candidate_codes[1]] = _tdx_info(
        candidate_codes[1], eps="", bvps="", revenue=""
    )
    snapshots[candidate_codes[2]] = {"price": 0, "source": "tdx_quant"}
    values[f"valuation:daily_summary:{candidate_codes[2]}"]["close"] = 0

    cache = FakeValuationCache(values)
    source = FakeValuationSource(
        stock_info=stock_info,
        snapshots=snapshots,
        delay=0.01,
    )
    provider = ValuationDataProvider(
        cache=cache,
        tdx_source=source,
        quote_fallback=lambda _codes: {},
        max_workers=4,
    )

    first = provider.get_peers(target, limit=24)

    assert len(source.info_calls) <= 32
    assert source.max_active > 1
    assert source.max_active <= 4
    assert len(first["peers"]) <= 24
    assert all(peer["code"] != target for peer in first["peers"])
    assert all(not peer["code"].startswith("920") for peer in first["peers"])
    assert candidate_codes[0] not in {peer["code"] for peer in first["peers"]}
    assert candidate_codes[1] not in {peer["code"] for peer in first["peers"]}
    assert candidate_codes[2] not in {peer["code"] for peer in first["peers"]}
    assert 24 < first["candidate_fetch_count"] <= 32
    assert first["source"] == "tdx_industry+bounded_peers"

    keys_calls = cache.keys_calls
    info_calls = len(source.info_calls)
    second = provider.get_peers(target, limit=24)

    assert second == first
    assert cache.keys_calls == keys_calls
    assert len(source.info_calls) == info_calls


def test_fundamental_cache_uses_24_hour_ttl_and_skips_source_on_hit():
    from quant.valuation.data import ValuationDataProvider

    source = FakeValuationSource(
        stock_info={"300442": _tdx_info("300442", name="润泽科技")}
    )
    cache = FakeValuationCache()
    provider = ValuationDataProvider(cache=cache, tdx_source=source)

    first = provider.get_fundamentals("300442")
    second = provider.get_fundamentals("300442")

    assert first == second
    assert source.info_calls == ["300442"]
    fundamental_sets = [
        call for call in cache.set_calls
        if call[0] == "valuation:fundamental:300442"
    ]
    assert len(fundamental_sets) == 1
    assert fundamental_sets[0][2] == 24 * 60 * 60


def test_market_inputs_return_partial_without_fabricating_missing_dimensions():
    from quant.valuation.data import ValuationDataProvider

    cache = FakeValuationCache(
        {
            "valuation:market_summaries": [
                {
                    "code": "600001",
                    "latest_date": "20260711",
                    "change_pct": 2.0,
                    "amount": 100.0,
                },
                {
                    "code": "600002",
                    "latest_date": "20260711",
                    "change_pct": -1.0,
                    "amount": 50.0,
                },
            ]
        }
    )
    source = FakeValuationSource(
        klines={"SH000300": RuntimeError("index history unavailable")}
    )
    provider = ValuationDataProvider(cache=cache, tdx_source=source)

    out = provider.get_market_inputs()

    assert out["status"] == "partial"
    assert out["breadth"]["advance_ratio"] == 0.5
    assert out["liquidity"]["total_amount"] == 150.0
    assert out["liquidity"]["active_count"] == 2
    assert out["index"]["code"] == "SH000300"
    assert out["index"]["latest_date"] is None
    assert out["index"]["bars"] == []
    assert any("index" in warning.lower() for warning in out["warnings"])


def test_market_inputs_derives_index_percentile_and_regime_from_tdx_bars():
    from quant.valuation.data import ValuationDataProvider

    bars = [
        {
            "date": f"2026{i // 28 + 1:02d}{i % 28 + 1:02d}",
            "close": 3000.0 + i,
            "factor": 1.0,
        }
        for i in range(120)
    ]
    provider = ValuationDataProvider(
        cache=FakeValuationCache(
            {
                "valuation:market_summaries": [
                    {
                        "code": "600001",
                        "latest_date": "20260713",
                        "change_pct": 1.0,
                        "amount": 100.0,
                    }
                ]
            }
        ),
        tdx_source=FakeValuationSource(klines={"SH000300": bars}),
    )

    out = provider.get_market_inputs()

    assert out["index"]["percentile"] is not None
    assert out["index"]["percentile"] > 0.95
    assert out["index"]["regime"] == "bull"
    assert out["index"]["status"] == "success"


def test_valuation_input_bundle_has_stable_partial_contract():
    from quant.valuation.data import ValuationDataProvider

    cache = FakeValuationCache(
        {
            "stock:name:300442": "润泽科技",
            "stock:industry:300442": "C|软件和信息技术服务业",
            "kline:300442:d": [
                {"date": "20260711", "close": 80.5, "volume": 10, "amount": 805}
            ],
            "fin:abstract:300442": [
                {"report_date": "20260331", "ann_date": "20260428", "roe": 12.0}
            ],
            "valuation:daily_summary:300442": {
                "code": "300442",
                "name": "润泽科技",
                "latest_date": "20260711",
                "close": 80.5,
                "amount": 805.0,
            },
        }
    )
    source = FakeValuationSource(
        stock_info={"300442": _tdx_info("300442", name="润泽科技")},
        snapshot_error=TimeoutError("closed"),
    )
    provider = ValuationDataProvider(cache=cache, tdx_source=source)

    out = provider.get_valuation_inputs("300442", include_peers=False)

    assert out["code"] == "300442"
    assert out["name"] == "润泽科技"
    assert set(out) >= {
        "code",
        "name",
        "status",
        "quote",
        "fundamentals",
        "financial_history",
        "industry",
        "daily_history",
        "peers",
        "market",
        "data_date",
        "report_period",
        "sources",
        "warnings",
    }
    assert out["quote"]["source"] == "stock_daily_summary"
    assert out["peers"]["status"] == "unavailable"
    assert out["report_period"] == "20260331"


def test_tdx_industry_is_primary_and_matches_peers_by_tdx_code():
    from quant.valuation.data import ValuationDataProvider

    cache = FakeValuationCache(
        {
            "stock:universe": ["300442", "600001", "600002"],
            "stock:industry:300442": "Z|Baostock旧分类",
            "stock:industry:600001": "A|Baostock不同分类",
            "stock:industry:600002": "C|Baostock另一分类",
            "valuation:daily_summary:600001": {
                "code": "600001",
                "name": "同行甲",
                "latest_date": "20260711",
                "close": 12.0,
                "amount": 900_000.0,
            },
            "valuation:daily_summary:600002": {
                "code": "600002",
                "name": "非同行",
                "latest_date": "20260711",
                "close": 9.0,
                "amount": 800_000.0,
            },
        }
    )
    target = _tdx_info("300442", name="润泽科技")
    target["rs_hycode_sim"] = "C39"
    target["rs_hyname_sim"] = "计算机、通信和其他电子设备制造业"
    peer = _tdx_info("600001", name="同行甲")
    peer["rs_hycode_sim"] = "C39"
    outsider = _tdx_info("600002", name="非同行")
    outsider["rs_hycode_sim"] = "D44"
    source = FakeValuationSource(
        stock_info={
            "300442": target,
            "600001": peer,
            "600002": outsider,
        },
        snapshots={
            "600001": {
                "price": 12.0,
                "prev_close": 11.8,
                "volume": 100,
                "amount": 900_000.0,
                "timestamp": "20260712103000",
            },
            "600002": {
                "price": 9.0,
                "prev_close": 9.1,
                "volume": 100,
                "amount": 800_000.0,
                "timestamp": "20260712103000",
            },
        },
    )
    provider = ValuationDataProvider(cache=cache, tdx_source=source)

    fundamentals = provider.get_fundamentals("300442")
    industry = provider.get_industry("300442")
    peers = provider.get_peers("300442", limit=5)

    assert fundamentals["industry_code"] == "C39"
    assert fundamentals["industry_name"] == "计算机、通信和其他电子设备制造业"
    assert industry["industry_code"] == "C39"
    assert industry["industry_name"] == "计算机、通信和其他电子设备制造业"
    assert industry["source"] == "tdx_quant_stock_info"
    assert [row["code"] for row in peers["peers"]] == ["600001"]


def test_tdx_code_uses_baostock_label_only_to_prefilter_peer_candidates():
    from quant.valuation.data import ValuationDataProvider

    values = {
        "stock:universe": ["300442", "600001", "600002", "600003"],
        "stock:industry:300442": "C|计算机通信制造",
        "stock:industry:600001": "C|计算机通信制造",
        "stock:industry:600002": "J|金融",
        "stock:industry:600003": "C|计算机通信制造",
    }
    for code, amount in (("600001", 900_000), ("600002", 950_000), ("600003", 800_000)):
        values[f"valuation:daily_summary:{code}"] = {
            "code": code,
            "name": code,
            "latest_date": "20260711",
            "close": 10.0,
            "amount": amount,
        }
    target = _tdx_info("300442")
    target["rs_hycode_sim"] = "X4203"
    target.pop("rs_hyname_sim", None)
    peer = _tdx_info("600001")
    peer["rs_hycode_sim"] = "X4203"
    other_sector = _tdx_info("600002")
    other_sector["rs_hycode_sim"] = "J66"
    peer_two = _tdx_info("600003")
    peer_two["rs_hycode_sim"] = "X4203"
    source = FakeValuationSource(
        stock_info={
            "300442": target,
            "600001": peer,
            "600002": other_sector,
            "600003": peer_two,
        },
        snapshots={
            "600001": {"price": 10.0, "prev_close": 9.9, "volume": 1, "amount": 10, "timestamp": "20260712103000"},
            "600003": {"price": 11.0, "prev_close": 10.9, "volume": 1, "amount": 11, "timestamp": "20260712103000"},
        },
    )
    provider = ValuationDataProvider(
        cache=FakeValuationCache(values),
        tdx_source=source,
        max_peer_scan=2,
    )

    industry = provider.get_industry("300442")
    peers = provider.get_peers("300442", limit=2)

    assert industry["industry_code"] == "X4203"
    assert industry["peer_filter_label"] == "C|计算机通信制造"
    assert industry["source"] == "tdx_quant_stock_info+baostock_peer_filter"
    assert [row["code"] for row in peers["peers"]] == ["600001", "600003"]
    assert "600002" not in source.info_calls


def test_fundamentals_fill_missing_fields_per_field_without_overwriting_tdx():
    from quant.valuation.data import ValuationDataProvider

    tdx = _tdx_info(
        "300442",
        name="润泽科技",
        eps="1.42",
        bvps="",
        revenue="",
        shares="164104.20",
    )
    tdx["J_jly"] = ""
    tdx["J_jyxjl"] = ""
    cache = FakeValuationCache(
        {
            "fin:abstract:300442": [
                {
                    "report_date": "20260331",
                    "ann_date": "20260428",
                    "eps": 99.0,
                    "bvps": 8.74,
                    "revenue": 1_839_577_700.0,
                    "net_profit": 582_229_600.0,
                }
            ]
        }
    )
    fetch_calls = []

    def financial_fetcher(code, include_tushare=False):
        fetch_calls.append(code)
        return {
            "akshare_records": [
                {
                    "report_date": "20260331",
                    "ann_date": "20260429",
                    "eps": 88.0,
                    "operating_cash_flow": 1_315_853_400.0,
                    "total_assets": 47_095_515_000.0,
                }
            ],
            "warnings": [],
        }

    provider = ValuationDataProvider(
        cache=cache,
        tdx_source=FakeValuationSource(stock_info={"300442": tdx}),
        financial_fetcher=financial_fetcher,
    )

    out = provider.get_fundamentals("300442")

    assert out["eps"] == 1.42
    assert out["bvps"] == 8.74
    assert out["revenue"] == 1_839_577_700.0
    assert out["net_profit"] == 582_229_600.0
    assert out["operating_cash_flow"] == 1_315_853_400.0
    assert out["total_assets"] == 50_000_000.0
    assert out["field_sources"]["eps"] == "tdx_quant_stock_info"
    assert out["field_sources"]["bvps"] == "fin_abstract_cache"
    assert out["field_sources"]["operating_cash_flow"] == "akshare_selected_stock"
    assert out["field_sources"]["total_assets"] == "tdx_quant_stock_info"
    assert fetch_calls == ["300442"]
    assert any("filled" in warning.lower() for warning in out["warnings"])


def test_external_financial_and_kline_results_are_cached_between_calls():
    from quant.valuation.data import ValuationDataProvider

    cache = FakeValuationCache()
    fetch_calls = []

    def financial_fetcher(code, include_tushare=False):
        fetch_calls.append(code)
        return {
            "akshare_records": [
                {
                    "report_date": "20260331",
                    "ann_date": "20260428",
                    "roe": 12.5,
                }
            ],
            "warnings": [],
        }

    source = FakeValuationSource(
        klines={
            "300442": [
                {"date": "20260711", "close": 80.5, "volume": 10, "amount": 805}
            ]
        }
    )
    provider = ValuationDataProvider(
        cache=cache,
        tdx_source=source,
        financial_fetcher=financial_fetcher,
    )

    assert provider.get_financial_history("300442")["sample_length"] == 1
    assert provider.get_financial_history("300442")["sample_length"] == 1
    assert provider.get_daily_history("300442")["sample_length"] == 1
    assert provider.get_daily_history("300442")["sample_length"] == 1

    assert fetch_calls == ["300442"]
    assert source.kline_calls == [("300442", 900, "1d")]
    assert cache.get("valuation:financial_history:300442") is not None
    assert cache.get("valuation:kline:300442:900") is not None


def test_status_ttl_and_negative_cache_expiry_allow_recovery():
    from quant.valuation.data import ValuationDataProvider

    cache = FakeValuationCache()
    source = FakeValuationSource(stock_info={"300442": {}})
    provider = ValuationDataProvider(
        cache=cache,
        tdx_source=source,
        financial_fetcher=lambda *_args, **_kwargs: {
            "akshare_records": [],
            "warnings": [],
        },
    )

    unavailable = provider.get_fundamentals("300442")
    unavailable_set = next(
        row for row in reversed(cache.set_calls)
        if row[0] == "valuation:fundamental:300442"
    )
    assert unavailable["status"] == "unavailable"
    assert 30 <= unavailable_set[2] <= 120

    source.stock_info["300442"] = _tdx_info("300442", name="润泽科技")
    cache.advance(unavailable_set[2] + 1)
    recovered = provider.get_fundamentals("300442")
    recovered_set = next(
        row for row in reversed(cache.set_calls)
        if row[0] == "valuation:fundamental:300442"
    )
    assert recovered["status"] == "success"
    assert recovered_set[2] == 24 * 60 * 60
    assert source.info_calls == ["300442", "300442"]

    partial_cache = FakeValuationCache()
    partial_provider = ValuationDataProvider(
        cache=partial_cache,
        tdx_source=FakeValuationSource(
            stock_info={"300442": {"Name": "润泽科技", "J_mgsy": "1.0"}}
        ),
        financial_fetcher=lambda *_args, **_kwargs: {
            "akshare_records": [],
            "warnings": [],
        },
    )
    assert partial_provider.get_fundamentals("300442")["status"] == "partial"
    partial_set = next(
        row for row in reversed(partial_cache.set_calls)
        if row[0] == "valuation:fundamental:300442"
    )
    assert 5 * 60 <= partial_set[2] <= 30 * 60


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0", False),
        ("false", False),
        (0, False),
        ("", False),
        ("1", True),
        (1, True),
        ("true", True),
        ("yes", True),
        ("ST", True),
        ("*ST", True),
    ],
)
def test_tdx_is_st_uses_explicit_boolean_parsing(raw, expected):
    from quant.valuation.data import normalize_tdx_fundamentals

    payload = _tdx_info("300442")
    payload["IsSTGP"] = raw

    assert normalize_tdx_fundamentals("300442", payload)["is_st"] is expected


def test_market_inputs_all_missing_do_not_report_zero_liquidity():
    from quant.valuation.data import ValuationDataProvider

    provider = ValuationDataProvider(
        cache=FakeValuationCache(),
        tdx_source=FakeValuationSource(
            klines={"SH000300": RuntimeError("offline")}
        ),
    )

    out = provider.get_market_inputs()

    assert out["status"] == "partial"
    assert out["liquidity"]["total_amount"] is None
    assert out["liquidity"]["active_count"] == 0
    assert out["breadth"]["advance_ratio"] is None
    assert len(out["warnings"]) >= 2


def test_quote_does_not_mark_previous_close_without_evidence_as_live():
    from quant.valuation.data import ValuationDataProvider

    source = FakeValuationSource(
        snapshots={
            "300442": {
                "price": 80.5,
                "prev_close": 80.5,
                "volume": 0,
                "amount": 0,
                "source": "tdx_quant",
                "raw": {"Now": 0, "LastClose": 80.5},
            }
        }
    )
    provider = ValuationDataProvider(
        cache=FakeValuationCache(),
        tdx_source=source,
        quote_fallback=lambda _codes: {},
    )

    out = provider.get_quote("300442")

    assert out["freshness"] == "preopen"
    assert out["status"] == "partial"
    assert out["as_of"] is None
    assert out["price"] == 80.5


def test_quote_distinguishes_suspended_and_stale_from_live():
    from quant.valuation.data import ValuationDataProvider

    suspended = ValuationDataProvider(
        cache=FakeValuationCache(),
        tdx_source=FakeValuationSource(
            snapshots={
                "300442": {
                    "price": 80.5,
                    "prev_close": 80.5,
                    "volume": 0,
                    "amount": 0,
                    "timestamp": "20260712103000",
                    "raw": {"Now": 80.5, "LastClose": 80.5},
                }
            }
        ),
        now_fn=lambda: datetime(2026, 7, 12, 10, 31),
    ).get_quote("300442")
    stale = ValuationDataProvider(
        cache=FakeValuationCache(),
        tdx_source=FakeValuationSource(
            snapshots={
                "300442": {
                    "price": 80.5,
                    "prev_close": 80.0,
                    "volume": 100,
                    "amount": 8050,
                    "timestamp": "20260710150000",
                    "raw": {"Now": 80.5, "LastClose": 80.0},
                }
            }
        ),
        now_fn=lambda: datetime(2026, 7, 12, 10, 31),
    ).get_quote("300442")

    assert suspended["freshness"] == "suspended"
    assert suspended["status"] == "partial"
    assert stale["freshness"] == "stale"
    assert stale["status"] == "partial"


def test_peer_selection_backfills_after_invalid_high_amount_candidates():
    from quant.valuation.data import ValuationDataProvider

    target = "300442"
    candidates = [f"60{i:04d}" for i in range(30)]
    values = {
        "stock:universe": [target, *candidates],
        f"stock:industry:{target}": "C|计算机",
    }
    stock_info = {target: _tdx_info(target)}
    snapshots = {}
    for index, code in enumerate(candidates):
        values[f"stock:industry:{code}"] = "C|计算机"
        values[f"valuation:daily_summary:{code}"] = {
            "code": code,
            "name": code,
            "latest_date": "20260711",
            "close": 10.0,
            "amount": 1_000_000.0 - index,
        }
        stock_info[code] = _tdx_info(
            code,
            eps="" if index < 10 else "1.0",
            bvps="" if index < 10 else "5.0",
            revenue="" if index < 10 else "1000",
        )
        snapshots[code] = {
            "price": 10.0,
            "prev_close": 9.9,
            "volume": 100,
            "amount": 1000,
            "timestamp": "20260712103000",
        }
    source = FakeValuationSource(stock_info=stock_info, snapshots=snapshots)
    provider = ValuationDataProvider(
        cache=FakeValuationCache(values),
        tdx_source=source,
        max_workers=4,
        max_peer_scan=20,
    )

    out = provider.get_peers(target, limit=5)

    assert len(out["peers"]) == 5
    assert out["candidate_fetch_count"] > 5
    assert out["candidate_fetch_count"] <= 20
    assert {row["code"] for row in out["peers"]} == set(candidates[10:15])


def test_peer_member_cache_survives_short_price_cache_and_refreshes_multiples():
    from quant.valuation.data import ValuationDataProvider

    cache = FakeValuationCache(
        {
            "stock:universe": ["300442", "600001"],
            "stock:industry:300442": "C|计算机",
            "stock:industry:600001": "C|计算机",
            "valuation:daily_summary:600001": {
                "code": "600001",
                "name": "同行甲",
                "latest_date": "20260711",
                "close": 10.0,
                "amount": 1000.0,
            },
        }
    )
    source = FakeValuationSource(
        stock_info={
            "300442": _tdx_info("300442"),
            "600001": _tdx_info("600001", eps="1.0", bvps="5.0"),
        },
        snapshots={
            "600001": {
                "price": 10.0,
                "prev_close": 9.9,
                "volume": 100,
                "amount": 1000,
                "timestamp": "20260712103000",
            }
        },
    )
    provider = ValuationDataProvider(
        cache=cache,
        tdx_source=source,
        now_fn=lambda: datetime(2026, 7, 12, 10, 31),
    )

    first = provider.get_peers("300442", limit=1)
    keys_calls = cache.keys_calls
    source.snapshots["600001"]["price"] = 12.0
    cache.advance(6)
    second = provider.get_peers("300442", limit=1)

    assert first["peers"][0]["price"] == 10.0
    assert second["peers"][0]["price"] == 12.0
    assert second["peers"][0]["pe"] == 12.0
    assert cache.keys_calls == keys_calls
    assert source.info_calls.count("600001") == 1


def test_peer_record_derives_growth_rate_from_cached_financial_history():
    from quant.valuation.data import ValuationDataProvider

    cache = FakeValuationCache(
        {
            "fin:abstract:600001": [
                {"report_date": "20231231", "revenue_growth": 12.0},
                {"report_date": "20241231", "revenue_growth": 18.0},
                {"report_date": "20251231", "revenue_growth": 24.0},
            ],
            "valuation:daily_summary:600001": {
                "code": "600001",
                "name": "Peer",
                "latest_date": "20260713",
                "close": 10.0,
                "amount": 1000.0,
            },
        }
    )
    provider = ValuationDataProvider(
        cache=cache,
        tdx_source=FakeValuationSource(
            stock_info={"600001": _tdx_info("600001")},
            snapshots={
                "600001": {
                    "price": 10.0,
                    "volume": 100,
                    "amount": 1000,
                    "timestamp": "20260713103000",
                }
            },
        ),
    )

    row = provider._peer_record("600001")

    assert row is not None
    assert row["growth_rate"] == pytest.approx(0.18)


def test_provider_executor_has_hard_outstanding_bound_under_repeated_timeouts():
    from quant.valuation.data import ValuationDataProvider

    candidates = [f"60{i:04d}" for i in range(20)]
    values = {
        "stock:universe": ["300442", *candidates],
        "stock:industry:300442": "C|计算机",
    }
    for code in candidates:
        values[f"stock:industry:{code}"] = "C|计算机"
        values[f"valuation:daily_summary:{code}"] = {
            "code": code,
            "name": code,
            "latest_date": "20260711",
            "close": 10.0,
            "amount": 1000.0,
        }
    source = FakeValuationSource(
        stock_info={code: _tdx_info(code) for code in candidates},
        delay=0.15,
    )
    provider = ValuationDataProvider(
        cache=FakeValuationCache(values),
        tdx_source=source,
        max_workers=2,
        max_pending_tasks=2,
        peer_timeout=0.01,
        max_peer_scan=10,
    )
    try:
        for target in ("300442", "300443", "300444"):
            provider.get_peers(target, industry="C|计算机", limit=5)
        metrics = provider.executor_metrics()

        assert metrics["max_workers"] == 2
        assert metrics["max_pending_tasks"] == 2
        assert metrics["outstanding"] <= 4
        assert metrics["rejected"] > 0
        assert source.max_active <= 2
    finally:
        time.sleep(0.2)
        provider.close()


def test_valuation_input_base_sections_run_in_parallel_without_deadlock():
    from quant.valuation.data import ValuationDataProvider

    cache = FakeValuationCache(
        {
            "stock:industry:300442": "C|计算机",
            "fin:abstract:300442": [
                {"report_date": "20260331", "ann_date": "20260428", "roe": 12.0}
            ],
            "valuation:market_summaries": [
                {
                    "code": "300442",
                    "latest_date": "20260711",
                    "change_pct": 1.0,
                    "amount": 1000.0,
                }
            ],
        }
    )
    source = FakeValuationSource(
        stock_info={"300442": _tdx_info("300442")},
        snapshots={
            "300442": {
                "price": 82.0,
                "prev_close": 81.0,
                "volume": 100,
                "amount": 8200,
                "timestamp": "20260712103000",
            }
        },
        klines={
            "300442": [{"date": "20260711", "close": 82.0}],
            "SH000300": [{"date": "20260711", "close": 4000.0}],
        },
        delay=0.05,
        snapshot_delay=0.05,
        kline_delay=0.05,
    )
    provider = ValuationDataProvider(
        cache=cache,
        tdx_source=source,
        max_workers=5,
        max_pending_tasks=5,
    )
    try:
        started = time.perf_counter()
        out = provider.get_valuation_inputs("300442", include_peers=False)
        elapsed = time.perf_counter() - started

        assert out["quote"]["price"] == 82.0
        assert out["fundamentals"]["eps"] == 1.2
        assert out["daily_history"]["sample_length"] == 1
        assert out["market"]["index"]["sample_length"] == 1
        assert elapsed < 0.16
        assert source.max_active >= 3
    finally:
        provider.close()


def _absolute_inputs(**fundamental_overrides):
    fundamentals = {
        "operating_cash_flow": 1_200_000_000.0,
        "capex": 300_000_000.0,
        "total_shares": 1_000_000_000.0,
        "long_term_debt": 400_000_000.0,
        "cash": 200_000_000.0,
        "revenue": 6_000_000_000.0,
        "net_profit": 800_000_000.0,
    }
    fundamentals.update(fundamental_overrides)
    return {
        "code": "300442",
        "name": "润泽科技",
        "fundamentals": fundamentals,
        "financial_history": {
            "records": [
                {"report_period": "20231231", "revenue": 4_800_000_000.0},
                {"report_period": "20241231", "revenue": 5_400_000_000.0},
                {"report_period": "20251231", "revenue": 6_000_000_000.0},
            ]
        },
        "market": {
            "risk_free_rate": 0.025,
            "market_risk_premium": 0.055,
        },
        "beta": 1.1,
    }


def test_absolute_valuation_returns_ordered_scenarios_and_sensitivity():
    from quant.valuation.absolute import absolute_valuation

    result = absolute_valuation(_absolute_inputs())

    assert result["status"] == "success"
    assert 0 < result["low"] < result["mid"] < result["high"]
    assert len(result["details"]["sensitivity"]) == 9
    assert result["details"]["cash_flow_method"] == "ocf_minus_capex"
    assert result["details"]["forecast_years"] == 5


def test_absolute_valuation_discloses_capex_proxy_and_never_uses_profit_as_fcff():
    from quant.valuation.absolute import absolute_valuation

    proxy = absolute_valuation(_absolute_inputs(capex=None))
    invalid = absolute_valuation(
        _absolute_inputs(
            operating_cash_flow=-10.0,
            capex=None,
            net_profit=5_000_000_000.0,
        )
    )

    assert proxy["status"] == "partial"
    assert proxy["details"]["cash_flow_method"] == "maintenance_capex_proxy"
    assert any("资本开支" in warning for warning in proxy["warnings"])
    assert invalid["status"] == "unavailable"
    assert invalid["mid"] is None


def test_absolute_valuation_prefers_disclosed_fcfe_and_growth_history():
    from quant.valuation.absolute import absolute_valuation

    inputs = _absolute_inputs(capex=None)
    inputs["financial_history"]["records"] = [
        {
            "report_period": "20231231",
            "revenue_growth": 19.1,
            "enterprise_fcf_per_share": 1.2,
        },
        {"report_period": "20241231", "revenue_growth": 0.32},
        {
            "report_period": "20251231",
            "revenue_growth": 29.99,
            "enterprise_fcf_per_share": -0.559467,
            "shareholder_fcf_per_share": 3.05939,
        },
    ]

    result = absolute_valuation(inputs)

    assert result["status"] == "success"
    assert result["details"]["cash_flow_method"] == "reported_fcfe_per_share"
    assert result["details"]["cash_flow_period"] == "20251231"
    assert result["details"]["base_fcff"] is None
    assert result["details"]["base_fcfe"] > 0
    assert result["details"]["derived_growth"] == pytest.approx(0.191)
    assert not any("capex" in warning.lower() for warning in result["warnings"])
    assert not any("6%" in warning for warning in result["warnings"])


def test_absolute_valuation_rejects_missing_shares_and_invalid_wacc():
    from quant.valuation.absolute import absolute_valuation

    missing_shares = absolute_valuation(_absolute_inputs(total_shares=None))
    invalid_wacc = absolute_valuation(
        _absolute_inputs(), assumptions={"wacc": 0.01, "terminal_growth": 0.02}
    )

    assert missing_shares["status"] == "unavailable"
    assert "总股本" in missing_shares["error"]
    assert invalid_wacc["status"] == "unavailable"
    assert "WACC" in invalid_wacc["error"]


def _relative_target(**overrides):
    target = {
        "code": "300442",
        "eps": 1.5,
        "bvps": 8.0,
        "revenue": 8_000_000_000.0,
        "total_shares": 1_000_000_000.0,
        "growth_rate": 0.20,
    }
    target.update(overrides)
    return target


def _relative_peers():
    return [
        {"code": "600001", "pe": 20.0, "pb": 2.0, "ps": 3.0, "growth_rate": 0.18},
        {"code": "600002", "pe": 24.0, "pb": 2.4, "ps": 3.4, "growth_rate": 0.22},
        {"code": "600003", "pe": 28.0, "pb": 2.8, "ps": 3.8, "growth_rate": 0.25},
        {"code": "600004", "pe": -10.0, "pb": -1.0, "ps": None, "growth_rate": -0.1},
        {"code": "600005", "pe": 400.0, "pb": 40.0, "ps": 50.0, "growth_rate": 0.30},
    ]


def test_relative_valuation_filters_invalid_outliers_and_exposes_methods():
    from quant.valuation.relative import relative_valuation

    result = relative_valuation(_relative_target(), _relative_peers())

    assert result["status"] == "partial"
    assert result["details"]["sample_count"] == 3
    assert result["details"]["excluded_count"] == 2
    assert set(result["details"]["methods"]) >= {"pe", "pb", "ps", "peg"}
    assert 0 < result["low"] <= result["mid"] <= result["high"]
    assert result["details"]["peer_codes"] == ["600001", "600002", "600003"]


def test_relative_valuation_omits_methods_with_invalid_target_metrics():
    from quant.valuation.relative import relative_valuation

    result = relative_valuation(
        _relative_target(eps=-1.0, bvps=-2.0, growth_rate=-0.1),
        _relative_peers(),
    )

    assert result["status"] == "partial"
    assert "pe" not in result["details"]["methods"]
    assert "peg" not in result["details"]["methods"]
    assert "pb" not in result["details"]["methods"]
    assert "ps" in result["details"]["methods"]


def test_relative_valuation_returns_unavailable_without_valid_method():
    from quant.valuation.relative import relative_valuation

    result = relative_valuation(
        _relative_target(
            eps=None,
            bvps=None,
            revenue=None,
            total_shares=None,
            growth_rate=None,
        ),
        _relative_peers(),
    )

    assert result["status"] == "unavailable"
    assert result["mid"] is None


def test_market_valuation_reports_actual_coverage_and_bounded_adjustment():
    from quant.valuation.market import market_valuation

    history = [
        {"date": f"2025{month:02d}28", "close": 40.0 + month}
        for month in range(1, 13)
    ] + [
        {"date": f"2026{month:02d}28", "close": 52.0 + month}
        for month in range(1, 7)
    ]
    context = {
        "breadth": {"advance_ratio": 0.9},
        "liquidity": {"amount_ratio": 2.5},
        "index": {"regime": "bull", "percentile": 0.9},
    }
    peers = [{"pe": 10.0}, {"pe": 20.0}, {"pe": 30.0}]

    result = market_valuation(
        {"price": 70.0, "eps": 2.0},
        history,
        context,
        peers=peers,
        reference_mid=60.0,
    )

    assert result["status"] == "partial"
    assert result["details"]["coverage_months"] == 18
    assert abs(result["details"]["adjustment"]) <= 0.20
    assert any("不足3年" in warning for warning in result["warnings"])
    assert 0 < result["low"] <= result["mid"] <= result["high"]


def test_market_valuation_degrades_without_reference_or_market_dimensions():
    from quant.valuation.market import market_valuation

    unavailable = market_valuation(
        {"price": 20.0},
        [],
        {},
        peers=[],
        reference_mid=None,
    )
    partial = market_valuation(
        {"price": 20.0},
        [{"date": "20260701", "close": 20.0}],
        {},
        peers=[],
        reference_mid=20.0,
    )

    assert unavailable["status"] == "unavailable"
    assert partial["status"] == "partial"
    assert partial["details"]["adjustment"] == 0.0


VALID_GLM_VALUATION = {
    "target_low": 75.0,
    "target_mid": 88.0,
    "target_high": 102.0,
    "confidence": 0.72,
    "assumptions": ["收入保持增长"],
    "drivers": ["算力基础设施需求"],
    "risks": ["资本开支"],
    "invalidation_conditions": ["增长显著低于预期"],
    "model_version": "glm-5.2",
    "prompt_version": "valuation-v2",
}


def test_validate_glm_output_accepts_strict_schema_and_rejects_bad_prices():
    from quant.valuation.glm import validate_glm_output

    valid = validate_glm_output(VALID_GLM_VALUATION, current_price=82.0)
    unordered = validate_glm_output(
        {**VALID_GLM_VALUATION, "target_low": 100.0, "target_high": 80.0},
        current_price=82.0,
    )
    extreme = validate_glm_output(
        {**VALID_GLM_VALUATION, "target_high": 500.0},
        current_price=82.0,
    )
    missing_array = validate_glm_output(
        {**VALID_GLM_VALUATION, "risks": "资本开支"},
        current_price=82.0,
    )

    assert valid["status"] == "success"
    assert valid["mid"] == 88.0
    assert unordered["status"] == "error"
    assert extreme["status"] == "error"
    assert missing_array["status"] == "error"


class FakeValuationInputProvider:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def get_valuation_inputs(self, code, include_peers=True):
        self.calls += 1
        return json.loads(json.dumps(self.payload, ensure_ascii=False))


def _service_payload():
    peers = [
        {
            "code": f"60000{index}",
            "pe": 18.0 + index,
            "pb": 2.0,
            "ps": 3.0,
            "growth_rate": 0.12 + index * 0.01,
        }
        for index in range(1, 7)
    ]
    return {
        "code": "300442",
        "name": "润泽科技",
        "data_date": "20260713T103000",
        "report_period": "20260331",
        "quote": {"price": 82.0, "as_of": "20260713T103000"},
        "fundamentals": {
            "eps": 1.5,
            "bvps": 8.0,
            "revenue": 8_000_000_000.0,
            "total_shares": 1_000_000_000.0,
            "operating_cash_flow": None,
        },
        "financial_history": {
            "records": [
                {"report_period": "20241231", "revenue": 6_000_000_000.0},
                {"report_period": "20251231", "revenue": 7_000_000_000.0},
                {"report_period": "20260331", "revenue": 8_000_000_000.0},
            ]
        },
        "daily_history": {
            "bars": [
                {"date": f"2026{month:02d}28", "close": 60.0 + month}
                for month in range(1, 7)
            ]
        },
        "industry": {"industry": "计算机", "industry_code": "C39"},
        "peers": {"peers": peers},
        "market": {
            "breadth": {"advance_ratio": 0.55},
            "liquidity": {"amount_ratio": 1.05},
            "index": {"regime": "neutral", "percentile": 0.5},
        },
        "warnings": [],
    }


def test_service_analyze_isolates_tracks_never_calls_glm_and_persists(temp_cache):
    from quant.valuation.service import ValuationService

    provider = FakeValuationInputProvider(_service_payload())
    glm_calls = []

    def forbidden_glm(*args, **kwargs):
        glm_calls.append((args, kwargs))
        raise AssertionError("analyze must not call GLM")

    service = ValuationService(
        cache=temp_cache,
        data_provider=provider,
        glm_client=forbidden_glm,
    )
    result = service.analyze("300442")
    again = service.analyze("300442")

    assert set(result["valuations"]) == {"absolute", "relative", "market"}
    assert result["valuations"]["absolute"]["status"] == "unavailable"
    assert result["valuations"]["relative"]["status"] == "success"
    assert result["valuations"]["market"]["status"] == "partial"
    assert glm_calls == []
    assert again["valuation_id"] == result["valuation_id"]
    rows = temp_cache._conn.execute(
        "SELECT COUNT(*) FROM stock_valuations"
    ).fetchone()[0]
    assert rows == 3
    audit_rows = temp_cache._conn.execute(
        "SELECT COUNT(*) FROM audit_events WHERE event_type='stock_valuation'"
    ).fetchone()[0]
    assert audit_rows >= 3


def test_service_signature_changes_with_data_and_formula_versions(temp_cache):
    from quant.valuation.service import ValuationService

    payload = _service_payload()
    service = ValuationService(
        cache=temp_cache,
        data_provider=FakeValuationInputProvider(payload),
        glm_client=lambda *args, **kwargs: {},
    )

    original = service.build_data_signature(payload)
    price_date = service.build_data_signature(
        {**payload, "data_date": "20260714T103000"}
    )
    report = service.build_data_signature(
        {**payload, "report_period": "20260630"}
    )
    formula = service.build_data_signature(
        payload, formula_versions={"absolute": "absolute-dcf-v3"}
    )

    assert len({original, price_date, report, formula}) == 4


def test_service_glm_track_is_manual_cached_and_does_not_replace_rules(temp_cache):
    from quant.valuation.service import ValuationService

    calls = []

    def fake_glm(*args, **kwargs):
        calls.append((args, kwargs))
        return {
            "success": True,
            "data": dict(VALID_GLM_VALUATION),
            "usage": {"total_tokens": 100},
        }

    service = ValuationService(
        cache=temp_cache,
        data_provider=FakeValuationInputProvider(_service_payload()),
        glm_client=fake_glm,
    )
    deterministic = service.analyze("300442")
    glm_result = service.glm_analyze("300442")
    cached = service.glm_analyze("300442")
    latest = service.latest("300442")

    assert glm_result["valuation"]["status"] == "success"
    assert glm_result["valuation"]["mid"] == 88.0
    assert len(calls) == 1
    assert cached["valuation_id"] == glm_result["valuation_id"]
    assert deterministic["valuations"]["relative"]["mid"] != 88.0
    assert set(latest["valuations"]) == {
        "absolute",
        "relative",
        "market",
        "glm",
    }


def test_service_rejects_invalid_glm_without_losing_deterministic_tracks(temp_cache):
    from quant.valuation.service import ValuationService

    calls = []

    def invalid_glm(*args, **kwargs):
        calls.append((args, kwargs))
        return {
            "success": True,
            "data": {**VALID_GLM_VALUATION, "confidence": 2.0},
        }

    service = ValuationService(
        cache=temp_cache,
        data_provider=FakeValuationInputProvider(_service_payload()),
        glm_client=invalid_glm,
    )
    deterministic = service.analyze("300442")
    glm_result = service.glm_analyze("300442")
    retried = service.glm_analyze("300442")
    latest = service.latest("300442")

    assert glm_result["valuation"]["status"] == "error"
    assert retried["valuation"]["status"] == "error"
    assert len(calls) == 2
    assert latest["valuations"]["relative"]["valuation_id"] == deterministic["valuation_id"]
    assert latest["valuations"]["glm"]["status"] == "error"


def test_compact_glm_input_bounds_history_and_keeps_decision_evidence(temp_cache):
    from quant.valuation.service import ValuationService

    payload = _service_payload()
    payload["daily_history"]["bars"] = [
        {
            "date": f"2025{month:02d}{day:02d}",
            "open": 50.0,
            "high": 55.0,
            "low": 48.0,
            "close": 52.0 + month / 10,
            "volume": 1_000_000 + day,
            "amount": 50_000_000 + day,
        }
        for month in range(1, 13)
        for day in range(1, 21)
    ]
    payload["financial_history"]["records"] = [
        {
            "report_period": f"{year}1231",
            "revenue": year * 1_000_000.0,
            "net_profit": year * 100_000.0,
            "extra": "x" * 500,
        }
        for year in range(2016, 2026)
    ]
    payload["market"]["index"] = {
        "code": "000001",
        "bars": [
            {"date": f"2026{month:02d}{day:02d}", "close": 3000 + month + day}
            for month in range(1, 7)
            for day in range(1, 21)
        ],
        "sample_length": 120,
        "latest_date": "20260620",
        "source": "test",
    }
    service = ValuationService(
        cache=temp_cache,
        data_provider=FakeValuationInputProvider(payload),
        glm_client=lambda *args, **kwargs: {},
    )
    deterministic = service.analyze("300442")

    compact = service.build_glm_input(payload, deterministic)
    serialized = json.dumps(compact, ensure_ascii=False)

    assert len(serialized) < 20_000
    assert len(compact["daily_history"]["recent_bars"]) <= 24
    assert len(compact["financial_history"]["recent_records"]) <= 8
    assert "bars" not in compact["market"]["index"]
    assert len(compact["market"]["index"]["recent_bars"]) <= 12
    assert set(compact["deterministic_valuations"]) == {
        "absolute",
        "relative",
        "market",
    }
    assert compact["valuation_semantics"]["market_adjustment"] == (
        "applied_once_after_base_value"
    )
    assert compact["current_price"] == 82.0


def test_glm_valuation_reserves_output_budget_for_reasoning_model():
    from quant.valuation.glm import glm_valuation

    captured = {}

    def fake_chat_json(*args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        return {
            "success": True,
            "data": dict(VALID_GLM_VALUATION),
            "usage": {},
        }

    result, _ = glm_valuation(
        {"code": "300442", "current_price": 82.0},
        current_price=82.0,
        chat_json_fn=fake_chat_json,
    )

    assert result["status"] == "success"
    assert captured["max_tokens"] >= 3000
    assert captured["timeout"] >= 90
    assert captured["max_retries"] == 0
    assert "市场状态随后只调整一次" in captured["args"][1]
    assert "严禁描述为绝对、相对、市场三轨共同加权" in captured["args"][1]


def test_point_in_time_filter_excludes_unannounced_records_and_marks_quality():
    from quant.valuation.financials import filter_point_in_time_records

    result = filter_point_in_time_records(
        [
            {"report_date": "20241231", "ann_date": "20250320", "revenue": 100.0},
            {"report_date": "20250331", "ann_date": "20250430", "revenue": 30.0},
            {"report_date": "20250630", "ann_date": "20250820", "revenue": 70.0},
        ],
        "20250501",
    )

    assert [row["report_date"] for row in result["records"]] == [
        "20241231",
        "20250331",
    ]
    assert result["financial_as_of"] == "20250430"
    assert result["quality"] == "announcement_date"
    assert result["quality_score"] == 1.0

    report_only = filter_point_in_time_records(
        [{"report_date": "20241231", "revenue": 100.0}],
        "20250501",
    )
    assert report_only["quality"] == "report_period_only"
    assert report_only["quality_score"] < 1.0


def test_ttm_metrics_use_annual_plus_current_ytd_minus_prior_ytd():
    from quant.valuation.financials import build_ttm_metrics

    result = build_ttm_metrics(
        [
            {
                "report_date": "20240331",
                "revenue": 20.0,
                "net_profit": 4.0,
                "operating_cash_flow": 3.0,
            },
            {
                "report_date": "20241231",
                "revenue": 100.0,
                "net_profit": 20.0,
                "operating_cash_flow": 18.0,
            },
            {
                "report_date": "20250331",
                "revenue": 30.0,
                "net_profit": 7.0,
                "operating_cash_flow": 8.0,
            },
        ]
    )

    assert result["period"] == "20250331"
    assert result["formula"] == "latest_annual+current_ytd-prior_ytd"
    assert result["revenue"] == 110.0
    assert result["net_profit"] == 23.0
    assert result["operating_cash_flow"] == 23.0


def test_fcfe_uses_cost_of_equity_and_three_stage_forecast():
    from quant.valuation.absolute import absolute_valuation

    inputs = _absolute_inputs(capex=None)
    inputs["quote"] = {"price": 20.0}
    inputs["financial_history"]["records"] = [
        {
            "report_period": "20231231",
            "shareholder_fcf_per_share": 1.0,
            "revenue_growth": 12.0,
        },
        {
            "report_period": "20241231",
            "shareholder_fcf_per_share": 2.0,
            "revenue_growth": 10.0,
        },
        {
            "report_period": "20251231",
            "shareholder_fcf_per_share": 3.0,
            "revenue_growth": 8.0,
        },
    ]

    result = absolute_valuation(inputs)

    assert result["status"] == "success"
    assert result["details"]["cash_flow_method"] == "normalized_fcfe"
    assert result["details"]["discount_rate_type"] == "cost_of_equity"
    assert result["details"]["cost_of_equity"] == pytest.approx(
        0.025 + 1.1 * 0.055
    )
    assert result["details"]["normalized_cash_flow"]["per_share"] == 2.0
    assert len(result["details"]["forecast_schedule"]) == 5
    assert [row["stage"] for row in result["details"]["forecast_schedule"]] == [
        "high_growth",
        "high_growth",
        "high_growth",
        "transition",
        "transition",
    ]


def test_fcff_uses_full_wacc_with_debt_tax_shield():
    from quant.valuation.absolute import absolute_valuation

    inputs = _absolute_inputs(capex=None)
    inputs["quote"] = {"price": 10.0}
    inputs["financial_history"]["records"] = [
        {
            "report_period": "20231231",
            "enterprise_fcf_per_share": 1.0,
            "revenue_growth": 10.0,
        },
        {
            "report_period": "20241231",
            "enterprise_fcf_per_share": 1.2,
            "revenue_growth": 9.0,
        },
        {
            "report_period": "20251231",
            "enterprise_fcf_per_share": 1.4,
            "revenue_growth": 8.0,
        },
    ]

    result = absolute_valuation(
        inputs,
        assumptions={"pre_tax_cost_of_debt": 0.05, "tax_rate": 0.25},
    )

    details = result["details"]
    assert result["status"] == "success"
    assert details["discount_rate_type"] == "wacc"
    assert details["wacc"] < details["cost_of_equity"]
    assert details["wacc_components"]["after_tax_cost_of_debt"] == pytest.approx(
        0.0375
    )
    assert details["wacc_components"]["equity_weight"] > 0
    assert details["wacc_components"]["debt_weight"] > 0


def test_relative_peg_prefers_earnings_growth_and_weights_similar_peers():
    from quant.valuation.relative import relative_valuation

    target = {
        **_relative_target(),
        "market_cap": 10_000.0,
        "earnings_growth_rate": 0.10,
        "growth_rate": 0.50,
        "roe": 20.0,
        "net_margin": 15.0,
    }
    peers = [
        {
            "code": "600001",
            "pe": 20.0,
            "pb": 2.0,
            "ps": 3.0,
            "market_cap": 11_000.0,
            "earnings_growth_rate": 0.10,
            "growth_rate": 0.50,
            "roe": 21.0,
            "net_margin": 14.0,
        },
        {
            "code": "600002",
            "pe": 40.0,
            "pb": 4.0,
            "ps": 6.0,
            "market_cap": 1_000_000.0,
            "earnings_growth_rate": 0.10,
            "growth_rate": 0.50,
            "roe": 5.0,
            "net_margin": 2.0,
        },
    ]

    result = relative_valuation(target, peers)

    assert result["details"]["growth_metric"] == "earnings_growth_rate"
    assert "peg" in result["details"]["methods"]
    weights = result["details"]["peer_weights"]
    assert weights["600001"] > weights["600002"]
    assert result["details"]["methods"]["peg"]["mid"] < 45.0


def test_calibration_uses_neutral_prior_until_twenty_samples():
    from quant.valuation.calibration import calibration_from_outcomes

    small = calibration_from_outcomes(
        [{"absolute_pct_error": 0.10, "direction_hit": 1}] * 10
    )
    assert small["source"] == "neutral_prior"
    assert small["reliability"] == 1.0

    mature = calibration_from_outcomes(
        [{"absolute_pct_error": 0.08, "direction_hit": 1}] * 20
    )
    assert mature["source"] == "historical_outcomes"
    assert 1.0 < mature["reliability"] <= 1.5


def test_calibration_forecasts_settle_and_summary_is_persisted(temp_cache):
    from quant.valuation.calibration import (
        get_calibration,
        record_forecast,
        settle_forecasts,
    )

    for index in range(20):
        assert record_forecast(
            temp_cache,
            valuation_id=f"valuation-{index}",
            code="300442",
            model_type="absolute",
            predicted_mid=110.0,
            spot_price=100.0,
            horizon_days=30,
            valuation_date="2020-01-01",
        )
    assert settle_forecasts(
        temp_cache,
        "300442",
        [{"date": "20200201", "close": 112.0}],
    ) == 20

    result = get_calibration(temp_cache, "absolute")

    assert result["source"] == "historical_outcomes"
    assert result["sample_count"] == 20
    stored = temp_cache._conn.execute(
        """
        SELECT sample_count, source
        FROM valuation_model_calibration
        WHERE model_type = 'absolute'
        """
    ).fetchone()
    assert stored == (20, "historical_outcomes")


def test_consensus_combines_absolute_and_relative_before_market_once():
    from quant.valuation.consensus import build_consensus

    result = build_consensus(
        {
            "absolute": {
                "status": "success",
                "low": 90.0,
                "mid": 100.0,
                "high": 110.0,
                "confidence": 1.0,
            },
            "relative": {
                "status": "success",
                "low": 70.0,
                "mid": 80.0,
                "high": 90.0,
                "confidence": 0.5,
            },
        },
        data_quality={"absolute": 1.0, "relative": 1.0},
        calibration={
            "absolute": {"reliability": 1.0, "source": "neutral_prior"},
            "relative": {"reliability": 1.0, "source": "neutral_prior"},
        },
        market_adjustment=0.10,
    )

    assert result["base_mid"] == pytest.approx(
        (100.0 * 1.0 + 80.0 * 0.5) / 1.5
    )
    assert result["final_mid"] == pytest.approx(result["base_mid"] * 1.10)
    assert result["weights"]["absolute"] == pytest.approx(2 / 3)
    assert result["weights"]["relative"] == pytest.approx(1 / 3)
    assert result["market_applied_once"] is True
