from __future__ import annotations

import json
import threading
from json import JSONDecodeError

import pandas as pd

from scripts import build_f4_market_references as reference_builder
from quant.qlib.f4_references import (
    build_benchmark_payload,
    build_industry_payload,
    normalize_industry_records,
)


def test_bounded_cninfo_client_passes_connect_and_read_timeout_and_normalizes_records():
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "records": [
                    {
                        "SECCODE": "600036",
                        "VARYDATE": "2026-06-01",
                        "F001V": "008002",
                        "F003V": "J66",
                        "F006V": "货币金融服务",
                    }
                ]
            }

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    client = reference_builder.BoundedCninfoIndustryClient(
        post=post,
        accept_enckey="token",
        timeout=(3.0, 7.0),
    )

    frame = client.stock_industry_change_cninfo(
        symbol="600036", start_date="20260601", end_date="20260603"
    )

    assert calls[0][1]["timeout"] == (3.0, 7.0)
    assert calls[0][1]["params"] == {
        "scode": "600036",
        "sdate": "2026-06-01",
        "edate": "2026-06-03",
    }
    assert frame.to_dict(orient="records") == [
        {
            "证券代码": "600036",
            "变更日期": "2026-06-01",
            "分类标准编码": "008002",
            "行业编码": "J66",
            "行业大类": "货币金融服务",
        }
    ]


def test_industry_builder_uses_last_consumed_f4_date_not_market_tail(
    tmp_path, monkeypatch
):
    calls = []

    class NeverCalledClient:
        def stock_industry_change_cninfo(self, **kwargs):
            calls.append(kwargs)
            raise AssertionError("already validated F4 horizon must not hit network")

    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    (dataset_root / "manifest.json").write_text(
        json.dumps(
            {
                "dataset_version": "daily-pit-2020-08-07-2026-08-21",
                "start_date": "2020-08-07",
                "end_date": "2026-08-21",
                "completed_symbols": ["SH600036", "SZ301699"],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "pit_industry.json"
    output.with_suffix(".progress.json").write_text(
        json.dumps(
            {
                "dataset_version": "daily-pit-2020-08-05-2026-08-19",
                "validated_through": "2026-08-19",
                "validated_through_by_symbol": {"SH600036": "2026-08-19"},
                "records_by_symbol": {
                    "SH600036": [
                        {
                            "instrument": "SH600036",
                            "effective_from": "2021-03-05",
                            "industry_code": "J66",
                            "industry_name": "货币金融服务",
                            "standard_code": "008002",
                            "source": "cninfo_p_stock2110",
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(reference_builder, "_load_akshare", lambda: NeverCalledClient())
    monkeypatch.setattr(
        reference_builder,
        "load_eligible_dates",
        lambda _raw_dir: {
            "SH600036": ["2026-06-03", "2026-08-21"],
            # Listed after the last complete F4 test window, so it is not an
            # input to this factory run and cannot block the historical gate.
            "SZ301699": ["2026-08-20", "2026-08-21"],
        },
    )
    monkeypatch.setattr(
        reference_builder,
        "_required_f4_validation_through",
        lambda *_args, **_kwargs: "2026-06-03",
    )

    payload = reference_builder.build_industry_reference(
        dataset_root=dataset_root,
        output_path=output,
        workers=4,
    )

    assert calls == []
    assert payload["status"] == "passed"
    assert payload["dataset_version"] == "daily-pit-2020-08-07-2026-08-21"
    assert payload["required_validation_through"] == "2026-06-03"
    assert payload["validated_through"] == "2026-08-19"
    assert payload["validated_through_symbols"] == 1
    assert payload["required_symbols"] == 1
    assert payload["deferred_tail_symbols"] == ["SZ301699"]


def test_industry_builder_still_fetches_missing_symbol_inside_consumed_horizon(
    tmp_path, monkeypatch
):
    calls = []

    class FakeClient:
        def stock_industry_change_cninfo(self, **kwargs):
            calls.append(kwargs)
            return pd.DataFrame(
                [
                    {
                        "证券代码": "600036",
                        "变更日期": "2021-03-05",
                        "分类标准编码": "008002",
                        "行业编码": "J66",
                        "行业大类": "货币金融服务",
                    }
                ]
            )

    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    (dataset_root / "manifest.json").write_text(
        json.dumps(
            {
                "dataset_version": "daily-pit-test",
                "start_date": "2020-01-01",
                "end_date": "2026-08-21",
                "completed_symbols": ["SH600036"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(reference_builder, "_load_akshare", lambda: FakeClient())
    monkeypatch.setattr(
        reference_builder,
        "load_eligible_dates",
        lambda _raw_dir: {"SH600036": ["2021-03-05", "2026-06-03"]},
    )
    monkeypatch.setattr(
        reference_builder,
        "_required_f4_validation_through",
        lambda *_args, **_kwargs: "2026-06-03",
    )

    payload = reference_builder.build_industry_reference(
        dataset_root=dataset_root,
        output_path=tmp_path / "pit_industry.json",
        workers=1,
    )

    assert calls == [
        {"symbol": "600036", "start_date": "19900101", "end_date": "20260603"}
    ]
    assert payload["status"] == "passed"
    assert payload["validated_through"] == "2026-06-03"


def test_industry_fetch_treats_cninfo_empty_records_as_valid_empty_history():
    class EmptyAkShare:
        def stock_industry_change_cninfo(self, **_kwargs):
            # AkShare 1.18.60 raises this after CNINFO returns records=[].
            raise KeyError("变更日期")

    assert reference_builder._fetch_industry(
        EmptyAkShare(), "SH600068", "1990-01-01", "2026-08-14"
    ) == []


def test_industry_fetch_retries_transient_response_errors(monkeypatch):
    attempts = 0

    class FlakyAkShare:
        def stock_industry_change_cninfo(self, **_kwargs):
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise JSONDecodeError("empty response", "", 0)
            return pd.DataFrame()

    monkeypatch.setattr(reference_builder.time, "sleep", lambda _seconds: None)

    assert reference_builder._fetch_industry(
        FlakyAkShare(), "SH600036", "1990-01-01", "2026-08-14"
    ) == []
    assert attempts == 3


def test_industry_client_is_initialized_on_main_thread_before_workers(
    tmp_path, monkeypatch
):
    caller_threads: list[str] = []

    class FakeAkShare:
        def stock_industry_change_cninfo(self, **_kwargs):
            return pd.DataFrame(
                [
                    {
                        "证券代码": "600036",
                        "变更日期": "20210305",
                        "分类标准编码": "008002",
                        "行业大类编码": "J66",
                        "行业大类": "货币金融服务",
                    }
                ]
            )

    def load_client():
        caller_threads.append(threading.current_thread().name)
        return FakeAkShare()

    monkeypatch.setattr(reference_builder, "_load_akshare", load_client)
    monkeypatch.setattr(
        reference_builder,
        "load_eligible_dates",
        lambda _raw_dir: {"SH600036": ["2021-03-05"]},
    )
    monkeypatch.setattr(
        reference_builder,
        "_read_object",
        lambda _path: {
            "dataset_version": "daily-pit-test",
            "start_date": "2021-01-01",
            "end_date": "2021-12-31",
        },
    )

    payload = reference_builder.build_industry_reference(
        dataset_root=tmp_path / "dataset",
        output_path=tmp_path / "pit_industry.json",
        workers=4,
    )

    assert caller_threads == [threading.current_thread().name]
    assert payload["source_completed_symbols"] == 1


def test_industry_builder_incrementally_validates_checkpoint_through_new_dataset_end(
    tmp_path, monkeypatch
):
    calls = []

    class FakeAkShare:
        def stock_industry_change_cninfo(self, **kwargs):
            calls.append(kwargs)
            return pd.DataFrame(
                [{
                    "证券代码": "600036",
                    "变更日期": "20260818",
                    "分类标准编码": "008002",
                    "行业大类编码": "J67",
                    "行业大类": "资本市场服务",
                }]
            )

    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    (dataset_root / "manifest.json").write_text(
        '{"dataset_version":"daily-pit-2020-08-05-2026-08-19",'
        '"start_date":"2020-08-05","end_date":"2026-08-19"}',
        encoding="utf-8",
    )
    output = tmp_path / "pit_industry.json"
    output.with_suffix(".progress.json").write_text(
        """{
          "dataset_version": "daily-pit-2020-08-01-2026-08-14",
          "validated_through": "2026-08-14",
          "validated_through_by_symbol": {"SH600036": "2026-08-14"},
          "records_by_symbol": {
            "SH600036": [{
              "instrument": "SH600036",
              "effective_from": "2021-03-05",
              "industry_code": "J66",
              "industry_name": "货币金融服务",
              "standard_code": "008002",
              "source": "cninfo_p_stock2110"
            }]
          }
        }""",
        encoding="utf-8",
    )
    monkeypatch.setattr(reference_builder, "_load_akshare", lambda: FakeAkShare())
    monkeypatch.setattr(
        reference_builder,
        "load_eligible_dates",
        lambda _raw_dir: {"SH600036": ["2026-08-14", "2026-08-19"]},
    )

    payload = reference_builder.build_industry_reference(
        dataset_root=dataset_root,
        output_path=output,
        workers=1,
    )

    assert calls == [{"symbol": "600036", "start_date": "20260815", "end_date": "20260819"}]
    assert [row["effective_from"] for row in payload["records"]] == [
        "2021-03-05",
        "2026-08-18",
    ]
    checkpoint = reference_builder._read_object(output.with_suffix(".progress.json"))
    assert checkpoint["validated_through_by_symbol"]["SH600036"] == "2026-08-19"


def test_reference_builders_ignore_raw_files_not_in_completed_manifest(
    tmp_path, monkeypatch
):
    dataset_root = tmp_path / "dataset"
    raw = dataset_root / "raw"
    raw.mkdir(parents=True)
    (dataset_root / "manifest.json").write_text(
        json.dumps(
            {
                "dataset_version": "daily-pit-v1",
                "start_date": "2026-01-02",
                "end_date": "2026-01-02",
                "completed_symbols": ["SH600000"],
            }
        ),
        encoding="utf-8",
    )
    for symbol in ("SH600000", "SZ300028"):
        (raw / f"{symbol}.json").write_text(
            json.dumps([{"instrument": symbol, "datetime": "2026-01-02", "close": 10}]),
            encoding="utf-8",
        )
    monkeypatch.setattr(reference_builder, "_load_akshare", lambda: object())
    monkeypatch.setattr(reference_builder, "_fetch_industry", lambda *_args: [])

    industry = reference_builder.build_industry_reference(
        dataset_root=dataset_root,
        output_path=tmp_path / "industry.json",
        workers=1,
    )

    assert industry["requested_symbols"] == 1
    assert industry["eligible_symbols"] == 1
    assert "SZ300028" not in industry["failed_symbols"]


def test_industry_records_keep_effective_dates_and_selected_standard():
    rows = [
        {
            "证券代码": "600036",
            "变更日期": "20190101",
            "分类标准编码": "008001",
            "行业大类编码": "J66",
            "行业大类": "货币金融服务",
        },
        {
            "证券代码": "600036",
            "变更日期": "20210305",
            "分类标准编码": "008002",
            "行业大类编码": "J66",
            "行业大类": "货币金融服务",
        },
    ]

    result = normalize_industry_records(rows, standard_code="008002")

    assert result == [
        {
            "instrument": "SH600036",
            "effective_from": "2021-03-05",
            "industry_code": "J66",
            "industry_name": "货币金融服务",
            "standard_code": "008002",
            "source": "cninfo_p_stock2110",
        }
    ]


def test_industry_coverage_does_not_backfill_before_first_effective_date():
    payload = build_industry_payload(
        [
            {
                "instrument": "SH600036",
                "effective_from": "2021-03-05",
                "industry_code": "J66",
                "industry_name": "货币金融服务",
                "standard_code": "008002",
                "source": "cninfo_p_stock2110",
            }
        ],
        {
            "SH600036": ["2021-03-04", "2021-03-05", "2021-03-08"],
            "SZ000001": ["2021-03-05"],
        },
    )

    assert payload["expected_samples"] == 4
    assert payload["covered_samples"] == 2
    assert payload["coverage"] == 0.5
    assert payload["effective_dated"] is True
    assert payload["status"] == "failed"
    assert payload["version"].startswith("cninfo-008002-")


def test_benchmark_coverage_uses_expected_calendar_and_hash_version():
    payload = build_benchmark_payload(
        [
            {"日期": "2026-08-10", "开盘": 4100, "收盘": 4120},
            {"日期": "2026-08-12", "开盘": 4130, "收盘": 4140},
        ],
        expected_dates=["2026-08-10", "2026-08-11", "2026-08-12"],
        code="000300",
    )

    assert payload["code"] == "000300"
    assert payload["expected_dates"] == 3
    assert payload["observed_dates"] == 2
    assert payload["coverage"] == 2 / 3
    assert payload["status"] == "failed"
    assert payload["version"].startswith("000300-")
    assert payload["bars"][0]["date"] == "2026-08-10"


def test_benchmark_cannot_pass_when_latest_expected_session_is_missing():
    expected = [f"2026-04-{day:02d}" for day in range(1, 31)]
    expected += [f"2026-05-{day:02d}" for day in range(1, 32)]
    expected += [f"2026-06-{day:02d}" for day in range(1, 31)]
    expected += [f"2026-07-{day:02d}" for day in range(1, 10)]
    rows = [{"date": value, "close": 4000 + index} for index, value in enumerate(expected[:-1])]

    payload = build_benchmark_payload(rows, expected_dates=expected, code="000300")

    assert payload["coverage"] == 0.99
    assert payload["latest_date_complete"] is False
    assert payload["missing_dates"] == [expected[-1]]
    assert payload["status"] == "failed"


def test_benchmark_primary_transport_is_bounded_and_parses_eastmoney_rows():
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": {
                    "klines": [
                        "2026-08-21,4100,4120,4130,4090,100,200,0"
                    ]
                }
            }

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    frame = reference_builder._fetch_benchmark(
        "2026-08-20", "2026-08-21", get=get, timeout=(3.0, 7.0)
    )

    assert calls[0][1]["timeout"] == (3.0, 7.0)
    assert calls[0][1]["params"]["secid"] == "1.000300"
    assert calls[0][1]["params"]["beg"] == "20260820"
    assert calls[0][1]["params"]["end"] == "20260821"
    assert frame.to_dict(orient="records") == [
        {
            "date": "2026-08-21",
            "open": 4100.0,
            "close": 4120.0,
            "high": 4130.0,
            "low": 4090.0,
            "volume": 100.0,
            "amount": 200.0,
        }
    ]


def test_benchmark_builder_revalidates_exact_cached_bars_when_source_is_down(
    tmp_path, monkeypatch
):
    output = tmp_path / "000300.json"
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    (dataset_root / "manifest.json").write_text(
        '{"dataset_version": "daily-pit-test"}', encoding="utf-8"
    )
    output.write_text(
        """{
          "status": "passed",
          "dataset_version": "old-version",
          "generated_at": "2026-08-17T09:26:06+08:00",
          "bars": [
            {"date": "2026-08-10", "close": 4100.0},
            {"date": "2026-08-11", "close": 4110.0}
          ]
        }""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        reference_builder,
        "load_eligible_dates",
        lambda _raw_dir: {"SH600036": ["2026-08-10", "2026-08-11"]},
    )
    monkeypatch.setattr(
        reference_builder,
        "_fetch_benchmark",
        lambda *_args: (_ for _ in ()).throw(ConnectionError("source down")),
    )
    monkeypatch.setattr(
        reference_builder,
        "_fetch_benchmark_tdx",
        lambda *_args: (_ for _ in ()).throw(ConnectionError("tdx down")),
    )

    payload = reference_builder.build_benchmark_reference(
        dataset_root=dataset_root, output_path=output
    )

    assert payload["status"] == "passed"
    assert payload["dataset_version"] == "daily-pit-test"
    assert payload["source_fetch_status"] == "cache_revalidated"
    assert payload["source_fetched_at"] == "2026-08-17T09:26:06+08:00"
    assert "source down" in payload["source_fetch_error"]


def test_benchmark_builder_merges_tdx_increment_when_primary_source_is_down(
    tmp_path, monkeypatch
):
    output = tmp_path / "000300.json"
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    (dataset_root / "manifest.json").write_text(
        '{"dataset_version": "daily-pit-test"}', encoding="utf-8"
    )
    output.write_text(
        '{"bars":[{"date":"2026-08-10","close":4100.0}],"generated_at":"old"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        reference_builder,
        "load_eligible_dates",
        lambda _raw_dir: {"SH600036": ["2026-08-10", "2026-08-11"]},
    )
    monkeypatch.setattr(
        reference_builder,
        "_fetch_benchmark",
        lambda *_args: (_ for _ in ()).throw(ConnectionError("primary down")),
    )
    monkeypatch.setattr(
        reference_builder,
        "_fetch_benchmark_tdx",
        lambda *_args: [
            {"date": "2026-08-10", "close": 4101.0},
            {"date": "2026-08-11", "close": 4111.0},
        ],
    )

    payload = reference_builder.build_benchmark_reference(
        dataset_root=dataset_root, output_path=output
    )

    assert payload["status"] == "passed"
    assert payload["source_fetch_status"] == "tdx_quant_incremental"
    assert payload["source"] == "akshare_index_zh_a_hist+tdx_quant"
    assert payload["bars"][-1]["date"] == "2026-08-11"
