import json

import numpy as np
import pandas as pd
import pytest


def test_exporter_writes_native_qlib_layout(tmp_path):
    from quant.qlib.exporter import write_qlib_bin

    frame = pd.DataFrame(
        [
            {
                "instrument": "SH600000",
                "datetime": "2026-01-02",
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10.5,
                "volume": 100,
                "amount": 1050,
                "factor": 1.0,
            },
            {
                "instrument": "SH600000",
                "datetime": "2026-01-05",
                "open": 10.5,
                "high": 11.2,
                "low": 10.2,
                "close": 11,
                "volume": 120,
                "amount": 1320,
                "factor": 1.0,
            },
        ]
    )

    result = write_qlib_bin(frame, tmp_path)

    calendar = (tmp_path / "calendars" / "day.txt").read_text().splitlines()
    instruments = (tmp_path / "instruments" / "all.txt").read_text().splitlines()
    close_data = np.fromfile(
        tmp_path / "features" / "sh600000" / "close.day.bin",
        dtype="<f4",
    )
    assert calendar == ["2026-01-02", "2026-01-05"]
    assert instruments == ["SH600000\t2026-01-02\t2026-01-05"]
    assert close_data.tolist() == pytest.approx([0.0, 10.5, 11.0])
    assert result["instruments"] == 1


def test_exporter_writes_factor_and_tradable_features(tmp_path):
    from quant.qlib.exporter import write_qlib_bin

    frame = pd.DataFrame(
        [
            {
                "instrument": "SH600000",
                "datetime": "2026-01-02",
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10,
                "volume": 100,
                "amount": 1000,
                "factor": 0.8,
                "tradable": 1,
                "is_st": 0,
                "st_unknown": 0,
                "listed": 1,
                "delisted": 0,
                "paused": 0,
                "limit_up": 0,
                "limit_down": 0,
            }
        ]
    )

    write_qlib_bin(frame, tmp_path)

    feature_dir = tmp_path / "features" / "sh600000"
    assert (feature_dir / "factor.day.bin").exists()
    assert (feature_dir / "tradable.day.bin").exists()
    assert (feature_dir / "is_st.day.bin").exists()
    assert (feature_dir / "listed.day.bin").exists()


def test_streaming_exporter_builds_calendar_without_global_dataframe(tmp_path):
    from quant.qlib.exporter import write_qlib_bin_from_json_files

    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "SH600000.json").write_text(
        json.dumps(
            [
                {
                    "instrument": "SH600000",
                    "datetime": "2026-01-02",
                    "open": 10,
                    "high": 11,
                    "low": 9,
                    "close": 10,
                    "volume": 100,
                    "amount": 1000,
                    "factor": 1,
                }
            ]
        ),
        encoding="utf-8",
    )
    (raw / "SZ000001.json").write_text(
        json.dumps(
            [
                {
                    "instrument": "SZ000001",
                    "datetime": "2026-01-05",
                    "open": 12,
                    "high": 13,
                    "low": 11,
                    "close": 12,
                    "volume": 200,
                    "amount": 2400,
                    "factor": 1,
                }
            ]
        ),
        encoding="utf-8",
    )

    result = write_qlib_bin_from_json_files(sorted(raw.glob("*.json")), tmp_path / "bin")

    assert result["calendar_days"] == 2
    assert result["instruments"] == 2
    assert (tmp_path / "bin" / "calendars" / "day.txt").read_text().splitlines() == [
        "2026-01-02",
        "2026-01-05",
    ]
    assert (tmp_path / "bin" / "features" / "sh600000" / "close.day.bin").exists()
    assert (tmp_path / "bin" / "features" / "sz000001" / "close.day.bin").exists()


def test_streaming_exporter_registers_benchmark_but_excludes_it_from_market_universe(tmp_path):
    from quant.qlib.exporter import write_qlib_bin_from_json_files

    raw = tmp_path / "raw"
    raw.mkdir()
    for instrument in ("SH600000", "SH000300"):
        (raw / f"{instrument}.json").write_text(
            json.dumps(
                [{
                    "instrument": instrument,
                    "datetime": "2026-01-02",
                    "open": 10,
                    "high": 11,
                    "low": 9,
                    "close": 10,
                }]
            ),
            encoding="utf-8",
        )

    result = write_qlib_bin_from_json_files(
        sorted(raw.glob("*.json")),
        tmp_path / "bin",
        universe_exclusions={"SH000300"},
    )

    provider_universe = (tmp_path / "bin" / "instruments" / "all.txt").read_text().splitlines()
    market_universe = (tmp_path / "bin" / "instruments" / "market.txt").read_text().splitlines()
    assert provider_universe == [
        "SH000300\t2026-01-02\t2026-01-02",
        "SH600000\t2026-01-02\t2026-01-02",
    ]
    assert market_universe == ["SH600000\t2026-01-02\t2026-01-02"]
    assert (tmp_path / "bin" / "features" / "sh000300" / "close.day.bin").exists()
    assert result["instruments"] == 1
    assert result["provider_instruments"] == 2
    assert result["feature_instruments"] == 2


def test_benchmark_reference_is_strictly_adapted_for_native_qlib_export():
    from quant.qlib.exporter import benchmark_reference_rows

    payload = {
        "status": "passed",
        "code": "000300",
        "dataset_version": "daily-pit-v1",
        "research_only": True,
        "execution_authority": False,
        "bars": [
            {
                "date": "2026-01-02",
                "open": 4000,
                "high": 4050,
                "low": 3990,
                "close": 4040,
                "volume": 1000,
                "amount": 4040000,
            }
        ],
    }

    rows = benchmark_reference_rows(payload, expected_dataset_version="daily-pit-v1")

    assert rows[0]["instrument"] == "SH000300"
    assert rows[0]["datetime"] == "2026-01-02"
    assert rows[0]["factor"] == 1.0
    assert rows[0]["tradable"] == 1


@pytest.mark.parametrize(
    "drift",
    ["status", "version", "authority", "empty"],
)
def test_benchmark_reference_export_fails_closed_on_identity_or_authority_drift(drift):
    from quant.qlib.exporter import benchmark_reference_rows

    payload = {
        "status": "passed",
        "code": "000300",
        "dataset_version": "daily-pit-v1",
        "research_only": True,
        "execution_authority": False,
        "bars": [{"date": "2026-01-02", "close": 4040}],
    }
    if drift == "status":
        payload["status"] = "failed"
    elif drift == "version":
        payload["dataset_version"] = "old"
    elif drift == "authority":
        payload["execution_authority"] = True
    else:
        payload["bars"] = []

    with pytest.raises(ValueError, match="benchmark"):
        benchmark_reference_rows(payload, expected_dataset_version="daily-pit-v1")
