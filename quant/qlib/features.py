from __future__ import annotations


def _alpha_handler_config(
    handler: str,
    *,
    instruments: str = "all",
    start_time: str,
    end_time: str,
    fit_start_time: str,
    fit_end_time: str,
) -> dict:
    return {
        "class": handler,
        "module_path": "qlib.contrib.data.handler",
        "kwargs": {
            "start_time": start_time,
            "end_time": end_time,
            "fit_start_time": fit_start_time,
            "fit_end_time": fit_end_time,
            "instruments": instruments,
            "infer_processors": [
                {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature", "clip_outlier": True}},
                {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
            ],
            "learn_processors": [
                {"class": "DropnaLabel"},
                {"class": "CSRankNorm", "kwargs": {"fields_group": "label"}},
            ],
            "label": ["Ref($close, -5) / $close - 1"],
        },
    }


def alpha158_handler_config(
    *,
    instruments: str = "all",
    start_time: str,
    end_time: str,
    fit_start_time: str,
    fit_end_time: str,
) -> dict:
    return _alpha_handler_config(
        "Alpha158",
        instruments=instruments,
        start_time=start_time,
        end_time=end_time,
        fit_start_time=fit_start_time,
        fit_end_time=fit_end_time,
    )


def alpha360_handler_config(
    *,
    instruments: str = "all",
    start_time: str,
    end_time: str,
    fit_start_time: str,
    fit_end_time: str,
) -> dict:
    return _alpha_handler_config(
        "Alpha360",
        instruments=instruments,
        start_time=start_time,
        end_time=end_time,
        fit_start_time=fit_start_time,
        fit_end_time=fit_end_time,
    )
