from scripts import execution_runner


def test_daily_equity_history_keeps_latest_snapshot_and_computes_drawdown():
    rows = [
        {
            "id": 1,
            "total_equity": 1_000_000,
            "cash": 800_000,
            "position_count": 2,
            "created_at": "2026-07-20 09:40:00",
        },
        {
            "id": 2,
            "total_equity": 1_020_000,
            "cash": 790_000,
            "position_count": 2,
            "created_at": "2026-07-20 14:55:00",
        },
        {
            "id": 3,
            "total_equity": 999_600,
            "cash": 760_000,
            "position_count": 3,
            "created_at": "2026-07-21 14:55:00",
        },
    ]

    history = execution_runner._daily_equity_history(rows, limit=60)

    assert [point["date"] for point in history] == ["2026-07-20", "2026-07-21"]
    assert history[0]["equity"] == 1_020_000
    assert history[1]["drawdown_pct"] == -2.0


def test_daily_equity_history_drops_invalid_rows_and_applies_limit():
    rows = [
        {"id": 1, "total_equity": None, "created_at": "2026-07-18 10:00:00"},
        {"id": 2, "total_equity": 980_000, "created_at": "2026-07-19 10:00:00"},
        {"id": 3, "total_equity": 990_000, "created_at": "2026-07-20 10:00:00"},
        {"id": 4, "total_equity": 1_010_000, "created_at": "2026-07-21 10:00:00"},
    ]

    history = execution_runner._daily_equity_history(rows, limit=2)

    assert [point["date"] for point in history] == ["2026-07-20", "2026-07-21"]
    assert all(point["equity"] > 0 for point in history)


def test_daily_equity_history_accepts_sqlite_tuple_rows():
    rows = [
        (10, 1_000_000, 800_000, 2, "2026-07-20 10:00:00"),
        (11, 1_010_000, 790_000, 3, "2026-07-21 10:00:00"),
    ]

    history = execution_runner._daily_equity_history(rows)

    assert [point["equity"] for point in history] == [1_000_000, 1_010_000]


def test_daily_equity_history_excludes_audited_recovery_intervals():
    rows = [
        (239, 1_019_346.03, 685_415.36, 3, "2026-07-24 12:25:53"),
        (240, 900.0, 900.0, 0, "2026-07-27 09:35:00"),
        (336, 900.0, 900.0, 0, "2026-07-27 15:05:00"),
        (0, 1_027_953.36, 685_415.36, 3, "2026-07-29 10:18:33"),
    ]
    excluded_intervals = [{
        "start": "2026-07-25 21:52:50",
        "end": "2026-07-29 10:18:33",
        "reason": "pytest_fixture_overwrite",
    }]

    history = execution_runner._daily_equity_history(
        rows,
        excluded_intervals=excluded_intervals,
    )

    assert [point["date"] for point in history] == ["2026-07-24", "2026-07-29"]
    assert history[-1]["drawdown_pct"] == 0.0
