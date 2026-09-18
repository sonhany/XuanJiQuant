from quant.data import tdxrs_tick_source as tdxrs


def test_tdxrs_tick_source_normalizes_transaction_rows():
    rows = [
        {"time": "10:08", "price": 1187.1, "vol": 14.0, "num": 14, "buyorsell": 0},
        {"time": "10:08", "price": 1186.96, "vol": 6.0, "num": 9, "buyorsell": 1},
    ]

    ticks = tdxrs.normalize_transaction_rows("600519", rows, trade_date="20260710")

    assert ticks[0]["code"] == "600519"
    assert ticks[0]["date"] == "20260710"
    assert ticks[0]["time"] == "10:08:00"
    assert ticks[0]["price"] == 1187.1
    assert ticks[0]["volume"] == 1400
    assert ticks[0]["amount"] == round(1187.1 * 1400, 2)
    assert ticks[0]["direction"] == "B"
    assert ticks[0]["source"] == "tdxrs_transaction"
    assert ticks[1]["direction"] == "S"


def test_tdxrs_tick_source_builds_stats_from_true_transactions():
    ticks = tdxrs.normalize_transaction_rows("000001", [
        {"time": "10:00", "price": 10.0, "vol": 10, "buyorsell": 0},
        {"time": "10:01", "price": 10.2, "vol": 20, "buyorsell": 1},
    ], trade_date="20260710")

    stats = tdxrs.summarize_ticks("000001", ticks)

    assert stats["code"] == "000001"
    assert stats["count"] == 2
    assert stats["true_tick_count"] == 2
    assert stats["total_volume"] == 3000
    assert stats["buy_volume"] == 1000
    assert stats["sell_volume"] == 2000
    assert round(stats["vwap"], 4) == round((10.0 * 1000 + 10.2 * 2000) / 3000, 4)
    assert stats["source"] == "tdxrs_transaction"


def test_tdxrs_tick_source_uses_expected_trade_date_when_rows_have_no_date(monkeypatch):
    monkeypatch.setattr(tdxrs, "_default_trade_date", lambda: "20260710", raising=False)

    ticks = tdxrs.normalize_transaction_rows("000001", [
        {"time": "10:00", "price": 10.0, "vol": 10, "buyorsell": 0},
    ])

    assert ticks[0]["date"] == "20260710"


def test_tdxrs_tick_source_fetches_full_day_with_pagination(monkeypatch):
    calls = []

    def fake_fetch_rows(code, start, count, timeout):
        calls.append((code, start, count))
        if start == 0:
            return [
                {"time": f"09:30:{i + 1:02d}", "price": 10.0 + i / 100, "vol": 1, "buyorsell": i % 2}
                for i in range(20)
            ]
        if start == 20:
            return [
                {"time": "09:31:01", "price": 10.2, "vol": 3, "buyorsell": 0},
            ]
        return []

    monkeypatch.setattr(tdxrs, "_fetch_rows_page", fake_fetch_rows)

    out = tdxrs.fetch_full_day_ticks("000001", page_size=20, max_pages=5, trade_date="20260711")

    assert [c[1] for c in calls] == [0, 20]
    assert out["code"] == "000001"
    assert out["fetched"] == 21
    assert out["pages"] == 2
    assert out["pagination_complete"] is True
    assert out["complete"] is False
    assert out["first_time"] == "09:30:01"
    assert out["last_time"] == "09:31:01"
    assert len(out["ticks"]) == 21
