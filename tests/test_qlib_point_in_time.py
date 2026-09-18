def test_name_changes_create_shenzhen_st_interval():
    from quant.qlib.point_in_time import build_st_intervals

    changes = [
        {"date": "2021-01-05", "before": "测试股份", "after": "ST测试"},
        {"date": "2022-06-01", "before": "ST测试", "after": "测试股份"},
    ]

    assert build_st_intervals("SZ000001", changes) == [
        {
            "instrument": "SZ000001",
            "start_date": "2021-01-05",
            "end_date": "2022-05-31",
            "status": "st",
        }
    ]


def test_unknown_historical_st_is_not_normal():
    from quant.qlib.point_in_time import build_daily_mask

    mask = build_daily_mask(
        "SH600000",
        "2021-01-05",
        listing_date="1999-11-10",
        delisting_date="",
        st_intervals=[],
        historical_st_uncertain=True,
        volume=100,
    )

    assert mask["st_status"] == "unknown"
    assert mask["tradable"] is False


def test_samples_after_delisting_are_not_tradable():
    from quant.qlib.point_in_time import build_daily_mask

    mask = build_daily_mask(
        "SZ000005",
        "2024-04-29",
        listing_date="1990-12-10",
        delisting_date="2024-04-26",
        st_intervals=[],
        historical_st_uncertain=False,
        volume=100,
    )

    assert mask["delisted"] is True
    assert mask["tradable"] is False


def test_zero_volume_is_paused_and_not_tradable():
    from quant.qlib.point_in_time import build_daily_mask

    mask = build_daily_mask(
        "SZ000001",
        "2024-04-29",
        listing_date="1991-04-03",
        delisting_date="",
        st_intervals=[],
        historical_st_uncertain=False,
        volume=0,
    )

    assert mask["paused"] is True
    assert mask["tradable"] is False
