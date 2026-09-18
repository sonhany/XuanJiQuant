import hashlib
import json
import types
import sys


class FakeCache:
    def __init__(self, data=None):
        self.data = dict(data or {})

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ttl=None):
        self.data[key] = value

    def keys(self, pattern=""):
        return list(self.data.keys())


def test_kline_key_count_uses_direct_sql_when_available():
    from scripts import daily_update

    class Cursor:
        def fetchone(self):
            return (5204,)

    class Connection:
        def execute(self, sql, params):
            assert "COUNT(*)" in sql
            assert "kline:%:d" in sql
            return Cursor()

    cache = types.SimpleNamespace(_conn=Connection())

    assert daily_update._kline_key_count(cache) == 5204


def test_incremental_klines_skips_remote_when_cached_date_reaches_expected(monkeypatch):
    from scripts import daily_update

    cache = FakeCache({
        "kline:600519:d": [{"date": "20260709", "close": 100}],
    })

    def fail_fetch(*args, **kwargs):
        raise AssertionError("remote fetch should be skipped for fresh cached K-line")

    monkeypatch.setattr(daily_update, "fetch_kline_dual", fail_fetch)

    result = daily_update.incremental_klines(
        ["600519"],
        cache,
        expected_date="20260709",
        workers=1,
        sleep_sec=0,
    )

    assert result["skip"] == 1
    assert result["remote_fetches"] == 0


def test_incremental_klines_always_emits_machine_parseable_final_progress(monkeypatch):
    from scripts import daily_update

    cache = FakeCache({
        "kline:600519:d": [{"date": "20260709", "close": 100}],
    })
    lines = []
    monkeypatch.setattr(daily_update.logger, "info", lines.append)

    daily_update.incremental_klines(
        ["600519"],
        cache,
        expected_date="20260709",
        workers=1,
        sleep_sec=0,
    )

    assert any(
        "K线增量 [1/1] ok=0 skip=1 err=0 新增0根" in line
        for line in lines
    )


def test_incremental_klines_does_not_logout_baostock_when_no_baostock_request(monkeypatch):
    from scripts import daily_update

    cache = FakeCache({
        "kline:600519:d": [{"date": "20260709", "close": 100}],
    })
    monkeypatch.setattr(
        daily_update,
        "logout",
        lambda: (_ for _ in ()).throw(
            AssertionError("Baostock logout must not run when no Baostock session was used")
        ),
    )

    result = daily_update.incremental_klines(
        ["600519"],
        cache,
        expected_date="20260709",
        workers=1,
        sleep_sec=0,
    )

    assert result["skip"] == 1


def test_incremental_klines_uses_small_recent_fetch_window(monkeypatch):
    from scripts import daily_update

    cache = FakeCache({
        "kline:600519:d": [{"date": "20260708", "close": 100}],
    })
    seen = {}

    def fake_fetch(code, *, count, period):
        seen["count"] = count
        return {"ok": True, "bars": [
            {"date": "20260708", "close": 100},
            {"date": "20260709", "close": 101},
        ]}

    monkeypatch.setattr(daily_update, "fetch_kline_dual", fake_fetch)

    result = daily_update.incremental_klines(
        ["600519"],
        cache,
        expected_date="20260709",
        workers=1,
        sleep_sec=0,
    )

    assert result["ok"] == 1
    assert result["new_bars"] == 1
    assert seen["count"] <= 30
    assert cache.get("kline:600519:d")[-1]["date"] == "20260709"


def test_run_daily_update_financial_only_skips_kline(monkeypatch):
    from scripts import daily_update

    cache = FakeCache()
    monkeypatch.setattr(daily_update, "sync_universe", lambda force=False: ["600519"])
    monkeypatch.setattr(daily_update, "create_cache", lambda: cache)
    monkeypatch.setattr(
        daily_update,
        "incremental_klines",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("financial-only must not run K-line update")),
    )
    monkeypatch.setattr(daily_update, "refresh_financials", lambda codes, cache, **kwargs: {"ok": len(codes), "err": 0})

    result = daily_update.run_daily_update(financial=True, financial_only=True, limit=1, workers=1)

    assert "kline" not in result
    assert result["financial"]["ok"] == 1


def test_run_daily_update_uses_selected_codes_without_refreshing_universe(monkeypatch):
    from scripts import daily_update

    cache = FakeCache()
    seen = {}
    monkeypatch.setattr(
        daily_update,
        "sync_universe",
        lambda force=False: (_ for _ in ()).throw(
            AssertionError("selected-code update must not refresh the full universe")
        ),
    )
    monkeypatch.setattr(daily_update, "create_cache", lambda: cache)
    def fake_incremental_klines(codes, cache, **kwargs):
        seen["codes"] = list(codes)
        return {"ok": len(codes), "skip": 0, "err": 0, "new_bars": len(codes)}

    monkeypatch.setattr(daily_update, "incremental_klines", fake_incremental_klines)

    daily_update.run_daily_update(
        selected_codes=["600519.SH", "sz000001", "920001", "600519"],
        workers=1,
    )

    assert seen["codes"] == ["600519", "000001"]


def test_main_financial_only_summary_does_not_require_kline(monkeypatch):
    from scripts import daily_update

    cache = FakeCache({"kline:600519:d": [{"date": "20260709"}]})
    monkeypatch.setattr(sys, "argv", ["daily_update.py", "--financial", "--limit", "1"])
    monkeypatch.setattr(daily_update, "sync_universe", lambda force=False: ["600519"])
    monkeypatch.setattr(daily_update, "create_cache", lambda: cache)
    monkeypatch.setattr(
        daily_update,
        "incremental_klines",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("financial-only must not run K-line update")),
    )
    monkeypatch.setattr(daily_update, "refresh_financials", lambda codes, cache, **kwargs: {"ok": len(codes), "err": 0})

    daily_update.main()


def test_sync_universe_prefers_cached_universe_without_akshare_call(monkeypatch):
    from scripts import daily_update

    cache = FakeCache({"stock:universe": ["600519", "000001"]})
    called = {"akshare": 0}

    class FakeAkshare:
        @staticmethod
        def stock_info_a_code_name():
            called["akshare"] += 1
            raise AssertionError("cached universe should be used without AkShare")

    monkeypatch.setattr(daily_update, "create_cache", lambda: cache)
    monkeypatch.setitem(sys.modules, "akshare", FakeAkshare)

    assert daily_update.sync_universe() == ["600519", "000001"]
    assert called["akshare"] == 0


def test_refresh_financials_resumes_matching_interrupted_checkpoint(tmp_path):
    from scripts import daily_update

    codes = ["600519", "000001"]
    progress_file = tmp_path / "financial_update_progress.json"
    universe_hash = hashlib.sha256(",".join(codes).encode("utf-8")).hexdigest()
    progress_file.write_text(
        json.dumps(
            {
                "status": "running",
                "universe_hash": universe_hash,
                "completed_codes": ["600519"],
                "ok": 1,
                "err": 0,
            }
        ),
        encoding="utf-8",
    )
    cache = FakeCache()
    calls = []

    def fake_fetch(code):
        calls.append(code)
        return {
            "ok": True,
            "akshare_records": [{"report_date": "20260331", "revenue": 1}],
            "tushare_records": [],
            "merged": {"code": code},
        }

    result = daily_update.refresh_financials(
        codes,
        cache,
        sleep_sec=0,
        progress_file=str(progress_file),
        fetcher=fake_fetch,
        checkpoint_every=1,
    )

    assert calls == ["000001"]
    assert result == {
        "ok": 2,
        "err": 0,
        "done": 2,
        "total": 2,
        "resumed": 1,
        "cached": 0,
    }
    saved = json.loads(progress_file.read_text(encoding="utf-8"))
    assert saved["status"] == "completed"
    assert saved["completed_codes"] == codes


def test_refresh_financials_marks_checkpoint_interrupted_on_keyboard_interrupt(tmp_path):
    from scripts import daily_update

    codes = ["600519", "000001"]
    progress_file = tmp_path / "financial_update_progress.json"
    cache = FakeCache()
    calls = []

    def interrupt_after_first(code):
        calls.append(code)
        if code == "000001":
            raise KeyboardInterrupt()
        return {
            "ok": True,
            "akshare_records": [{"report_date": "20260331", "revenue": 1}],
            "tushare_records": [],
            "merged": {"code": code},
        }

    try:
        daily_update.refresh_financials(
            codes,
            cache,
            sleep_sec=0,
            progress_file=str(progress_file),
            fetcher=interrupt_after_first,
            checkpoint_every=1,
        )
    except KeyboardInterrupt:
        pass
    else:
        raise AssertionError("KeyboardInterrupt must propagate")

    saved = json.loads(progress_file.read_text(encoding="utf-8"))
    assert saved["status"] == "interrupted"
    assert saved["completed_codes"] == ["600519"]


def test_refresh_financials_skips_current_complete_history(tmp_path):
    from scripts import daily_update

    records = [
        {
            "report_date": period,
            "revenue": 1,
            "net_profit": 1,
            "operating_cash_flow": 1,
        }
        for period in ("20250930", "20251231", "20260331", "20260630")
    ]
    cache = FakeCache({"fin:abstract:600519": records})

    result = daily_update.refresh_financials(
        ["600519"],
        cache,
        sleep_sec=0,
        progress_file=str(tmp_path / "financial_update_progress.json"),
        fetcher=lambda code: (_ for _ in ()).throw(
            AssertionError("current complete history must not be fetched again")
        ),
        checkpoint_every=1,
    )

    assert result == {
        "ok": 1,
        "err": 0,
        "done": 1,
        "total": 1,
        "resumed": 0,
        "cached": 1,
    }
