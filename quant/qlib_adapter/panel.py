from __future__ import annotations

from typing import Mapping

import pandas as pd


QLIB_COLUMNS = ["datetime", "instrument", "$open", "$high", "$low", "$close", "$volume", "$amount"]


def _date_text(value) -> str:
    text = str(value)
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text[:10]


def to_qlib_panel(klines: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    """Convert {code: kline_df} into a qlib-like long panel.

    Output columns intentionally use qlib feature names such as ``$close`` so
    offline workers can be swapped to full qlib later without changing callers.
    """
    rows = []
    for code, df in (klines or {}).items():
        if df is None or df.empty or "date" not in df.columns:
            continue
        src = df.copy()
        out = pd.DataFrame()
        out["datetime"] = src["date"].map(_date_text)
        out["instrument"] = str(code)
        for src_col, qlib_col in (
            ("open", "$open"),
            ("high", "$high"),
            ("low", "$low"),
            ("close", "$close"),
            ("volume", "$volume"),
            ("amount", "$amount"),
        ):
            out[qlib_col] = pd.to_numeric(src[src_col], errors="coerce") if src_col in src.columns else pd.NA
        rows.append(out[QLIB_COLUMNS])
    if not rows:
        return pd.DataFrame(columns=QLIB_COLUMNS)
    panel = pd.concat(rows, ignore_index=True)
    return panel.sort_values(["datetime", "instrument"]).reset_index(drop=True)
