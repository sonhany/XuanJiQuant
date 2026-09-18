"""Historical outcome calibration for deterministic valuation models."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from statistics import mean

from .contracts import normalize_code, safe_number


MIN_CALIBRATION_SAMPLES = 20


def _iso_day(value: object) -> str:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    if len(digits) < 8:
        return ""
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"


def calibration_from_outcomes(outcomes: list[dict]) -> dict:
    """Return a bounded reliability multiplier from settled forecasts."""
    rows = [row for row in outcomes if isinstance(row, dict)]
    if len(rows) < MIN_CALIBRATION_SAMPLES:
        return {
            "source": "neutral_prior",
            "sample_count": len(rows),
            "minimum_samples": MIN_CALIBRATION_SAMPLES,
            "reliability": 1.0,
        }
    errors = [
        value
        for row in rows
        if (value := safe_number(
            row.get("absolute_pct_error", row.get("abs_pct_error"))
        )) is not None
        and value >= 0
    ]
    hits = [
        value
        for row in rows
        if (value := safe_number(row.get("direction_hit"))) is not None
    ]
    mape = mean(errors) if errors else 0.50
    hit_rate = mean(1.0 if value > 0 else 0.0 for value in hits) if hits else 0.50
    reliability = 1.0 + (hit_rate - 0.5) * 0.6 - min(mape, 0.5) * 0.5
    return {
        "source": "historical_outcomes",
        "sample_count": len(rows),
        "minimum_samples": MIN_CALIBRATION_SAMPLES,
        "mape": mape,
        "direction_hit_rate": hit_rate,
        "reliability": max(0.5, min(1.5, reliability)),
    }


def _resources(cache):
    connection = getattr(cache, "_conn", None)
    lock = getattr(cache, "_lock", None)
    return connection, lock


def ensure_calibration_schema(cache) -> bool:
    connection, lock = _resources(cache)
    if connection is None or lock is None:
        return False
    with lock:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS valuation_forecasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                valuation_id TEXT NOT NULL,
                code TEXT NOT NULL,
                model_type TEXT NOT NULL,
                valuation_date TEXT NOT NULL,
                predicted_mid REAL NOT NULL,
                spot_price REAL,
                horizon_days INTEGER NOT NULL,
                due_date TEXT NOT NULL,
                actual_price REAL,
                absolute_pct_error REAL,
                direction_hit INTEGER,
                settled_at TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_valuation_forecasts_identity
            ON valuation_forecasts(valuation_id, model_type, horizon_days)
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_valuation_forecasts_model_settled
            ON valuation_forecasts(model_type, settled_at)
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS valuation_model_calibration (
                model_type TEXT PRIMARY KEY,
                sample_count INTEGER NOT NULL,
                reliability REAL NOT NULL,
                mape REAL,
                direction_hit_rate REAL,
                source TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.commit()
    return True


def record_forecast(
    cache,
    *,
    valuation_id: str,
    code: object,
    model_type: str,
    predicted_mid: object,
    spot_price: object,
    horizon_days: int = 90,
    valuation_date: str | None = None,
) -> bool:
    if not ensure_calibration_schema(cache):
        return False
    normalized = normalize_code(code)
    prediction = safe_number(predicted_mid)
    spot = safe_number(spot_price)
    if not normalized or prediction is None or prediction <= 0:
        return False
    current = date.fromisoformat(valuation_date) if valuation_date else datetime.now(timezone.utc).date()
    due = current + timedelta(days=max(1, int(horizon_days)))
    connection, lock = _resources(cache)
    with lock:
        connection.execute(
            """
            INSERT OR IGNORE INTO valuation_forecasts (
                valuation_id, code, model_type, valuation_date,
                predicted_mid, spot_price, horizon_days, due_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(valuation_id),
                normalized,
                str(model_type),
                current.isoformat(),
                prediction,
                spot,
                int(horizon_days),
                due.isoformat(),
            ),
        )
        connection.commit()
    return True


def settle_forecasts(cache, code: object, bars: list[dict]) -> int:
    """Settle due forecasts from the first close on or after their due date."""
    if not ensure_calibration_schema(cache):
        return 0
    normalized = normalize_code(code)
    available = sorted(
        (
            (
                _iso_day(row.get("date") or row.get("time")),
                safe_number(row.get("close")),
            )
            for row in bars
            if isinstance(row, dict)
        ),
        key=lambda item: item[0],
    )
    available = [(day, close) for day, close in available if day and close and close > 0]
    if not normalized or not available:
        return 0
    connection, lock = _resources(cache)
    today = available[-1][0]
    with lock:
        pending = connection.execute(
            """
            SELECT id, predicted_mid, spot_price, due_date
            FROM valuation_forecasts
            WHERE code = ? AND settled_at IS NULL AND due_date <= ?
            """,
            (normalized, today),
        ).fetchall()
        settled = 0
        for forecast_id, prediction, spot, due_date in pending:
            actual = next((close for day, close in available if day >= due_date), None)
            if actual is None:
                continue
            error = abs(actual - prediction) / actual if actual > 0 else None
            direction_hit = None
            if spot is not None and spot > 0:
                direction_hit = int((prediction - spot) * (actual - spot) >= 0)
            connection.execute(
                """
                UPDATE valuation_forecasts
                SET actual_price = ?, absolute_pct_error = ?,
                    direction_hit = ?, settled_at = ?
                WHERE id = ?
                """,
                (
                    actual,
                    error,
                    direction_hit,
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    forecast_id,
                ),
            )
            settled += 1
        connection.commit()
    return settled


def get_calibration(cache, model_type: str, *, limit: int = 200) -> dict:
    if not ensure_calibration_schema(cache):
        return calibration_from_outcomes([])
    connection, lock = _resources(cache)
    with lock:
        rows = connection.execute(
            """
            SELECT absolute_pct_error, direction_hit
            FROM valuation_forecasts
            WHERE model_type = ? AND settled_at IS NOT NULL
            ORDER BY id DESC
            LIMIT ?
            """,
            (str(model_type), max(1, int(limit))),
        ).fetchall()
    result = calibration_from_outcomes(
        [
            {"absolute_pct_error": row[0], "direction_hit": row[1]}
            for row in rows
        ]
    )
    connection, lock = _resources(cache)
    with lock:
        connection.execute(
            """
            INSERT INTO valuation_model_calibration (
                model_type, sample_count, reliability, mape,
                direction_hit_rate, source, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(model_type) DO UPDATE SET
                sample_count = excluded.sample_count,
                reliability = excluded.reliability,
                mape = excluded.mape,
                direction_hit_rate = excluded.direction_hit_rate,
                source = excluded.source,
                updated_at = excluded.updated_at
            """,
            (
                str(model_type),
                int(result.get("sample_count") or 0),
                float(result.get("reliability") or 1.0),
                safe_number(result.get("mape")),
                safe_number(result.get("direction_hit_rate")),
                str(result.get("source") or "neutral_prior"),
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
        connection.commit()
    return result
