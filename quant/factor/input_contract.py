"""Versioned, non-authorizing input contract for factor research."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from quant.data.snapshot import read_latest_passed_snapshot
from quant.data.universe import filter_trade_universe_codes


class FactorInputContractError(RuntimeError):
    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = str(reason_code)
        self.detail = str(detail)
        super().__init__(f"{self.reason_code}: {self.detail}" if self.detail else self.reason_code)


def universe_version(codes: list[str] | tuple[str, ...]) -> str:
    return hashlib.sha256(",".join(codes).encode("utf-8")).hexdigest()


def _compact_date(value: object) -> str:
    return str(value or "").replace("-", "")[:8]


def governed_daily_bars(cache, code: str, input_snapshot) -> list[dict[str, Any]]:
    """Return only complete daily bars at or before the bound snapshot date."""
    as_of = _compact_date(
        input_snapshot.as_of
        if hasattr(input_snapshot, "as_of")
        else (input_snapshot or {}).get("as_of")
    )
    raw = cache.get(f"kline:{str(code).split('.')[0]}:d") or []
    if not isinstance(raw, list):
        return []
    return [
        bar
        for bar in raw
        if isinstance(bar, dict)
        and _compact_date(bar.get("date") or bar.get("d"))
        and (not as_of or _compact_date(bar.get("date") or bar.get("d")) <= as_of)
    ]


def _special_treatment(name: object) -> bool:
    text = str(name or "").strip().upper()
    return "ST" in text or "退" in text


@dataclass(frozen=True, slots=True)
class FactorInputSnapshot:
    snapshot_id: str
    data_version: str
    as_of: str
    universe_version: str
    active_codes: tuple[str, ...]
    data_codes: tuple[str, ...]
    eligible_codes: tuple[str, ...]
    excluded_reasons: dict[str, int]
    data_coverage: float

    def metadata(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "data_version": self.data_version,
            "as_of": self.as_of,
            "universe_version": self.universe_version,
            "universe_policy": "current_tradeable_v1",
            "active_count": len(self.active_codes),
            "data_count": len(self.data_codes),
            "eligible_count": len(self.eligible_codes),
            "data_coverage": self.data_coverage,
            "excluded_reasons": dict(self.excluded_reasons),
            "promotion_state": "research_only",
            "execution_authority": False,
        }


def load_factor_input_snapshot(
    cache,
    *,
    expected_date: str | None = None,
    minimum_data_coverage: float = 0.95,
    minimum_history_bars: int = 30,
    publish_cache: bool = True,
) -> FactorInputSnapshot:
    snapshot = read_latest_passed_snapshot(cache, "a_share_daily")
    if not snapshot:
        raise FactorInputContractError("factor_snapshot_missing")
    if snapshot.get("quality_status") != "passed" or snapshot.get("freshness_status") != "fresh":
        raise FactorInputContractError("factor_snapshot_not_passed")

    as_of = _compact_date(snapshot.get("as_of"))
    expected = _compact_date(expected_date)
    if expected and (not as_of or as_of < expected):
        raise FactorInputContractError(
            "factor_snapshot_stale",
            f"snapshot={as_of or 'missing'} expected={expected}",
        )

    active_codes = tuple(filter_trade_universe_codes(cache.get("stock:universe") or []))
    actual_universe_version = universe_version(active_codes)
    if actual_universe_version != str(snapshot.get("universe_version") or ""):
        raise FactorInputContractError(
            "factor_universe_mismatch",
            f"snapshot={snapshot.get('universe_version')} current={actual_universe_version}",
        )

    threshold = max(0.0, min(float(minimum_data_coverage), 1.0))
    cache_key = (
        f"factor:input_contract:{snapshot.get('snapshot_id')}:"
        f"{max(1, int(minimum_history_bars))}:{threshold:.6f}"
    )
    cached = cache.get(cache_key)
    if (
        isinstance(cached, dict)
        and cached.get("snapshot_id") == str(snapshot.get("snapshot_id") or "")
        and cached.get("data_version")
        == str(snapshot.get("content_hash") or snapshot.get("snapshot_id") or "")
        and cached.get("as_of") == as_of
        and cached.get("universe_version") == actual_universe_version
        and tuple(cached.get("active_codes") or ()) == active_codes
    ):
        return FactorInputSnapshot(
            snapshot_id=str(cached["snapshot_id"]),
            data_version=str(cached["data_version"]),
            as_of=str(cached["as_of"]),
            universe_version=str(cached["universe_version"]),
            active_codes=active_codes,
            data_codes=tuple(cached.get("data_codes") or ()),
            eligible_codes=tuple(cached.get("eligible_codes") or ()),
            excluded_reasons=dict(cached.get("excluded_reasons") or {}),
            data_coverage=float(cached.get("data_coverage") or 0.0),
        )

    data_codes: list[str] = []
    eligible_codes: list[str] = []
    excluded: dict[str, int] = {}

    def exclude(reason: str) -> None:
        excluded[reason] = excluded.get(reason, 0) + 1

    for code in active_codes:
        raw_bars = cache.get(f"kline:{code}:d") or []
        bars = [
            bar
            for bar in raw_bars
            if isinstance(bar, dict)
            and _compact_date(bar.get("date") or bar.get("d"))
            and _compact_date(bar.get("date") or bar.get("d")) <= as_of
        ] if isinstance(raw_bars, list) else []
        if not isinstance(bars, list) or not bars:
            exclude("missing_kline")
            continue
        latest = bars[-1] if isinstance(bars[-1], dict) else {}
        latest_date = _compact_date(latest.get("date") or latest.get("d"))
        if not latest_date or latest_date < as_of:
            exclude("stale_kline")
            continue
        data_codes.append(code)
        name = cache.get(f"stock:name:{code}") or code
        if _special_treatment(name):
            exclude("special_treatment_or_delisting")
            continue
        if len(bars) < max(1, int(minimum_history_bars)):
            exclude("insufficient_history")
            continue
        volume = latest.get("volume", latest.get("vol"))
        if volume is not None:
            try:
                if float(volume) <= 0:
                    exclude("zero_volume")
                    continue
            except (TypeError, ValueError):
                exclude("invalid_volume")
                continue
        eligible_codes.append(code)

    coverage = len(data_codes) / len(active_codes) if active_codes else 0.0
    if coverage < threshold:
        raise FactorInputContractError(
            "factor_coverage_below_gate",
            f"coverage={coverage:.6f} threshold={threshold:.6f}",
        )

    result = FactorInputSnapshot(
        snapshot_id=str(snapshot.get("snapshot_id") or ""),
        data_version=str(snapshot.get("content_hash") or snapshot.get("snapshot_id") or ""),
        as_of=as_of,
        universe_version=actual_universe_version,
        active_codes=active_codes,
        data_codes=tuple(data_codes),
        eligible_codes=tuple(eligible_codes),
        excluded_reasons=excluded,
        data_coverage=round(coverage, 8),
    )
    if publish_cache:
        cache.set(
            cache_key,
            {
                "snapshot_id": result.snapshot_id,
                "data_version": result.data_version,
                "as_of": result.as_of,
                "universe_version": result.universe_version,
                "active_codes": list(result.active_codes),
                "data_codes": list(result.data_codes),
                "eligible_codes": list(result.eligible_codes),
                "excluded_reasons": dict(result.excluded_reasons),
                "data_coverage": result.data_coverage,
                "promotion_state": "research_only",
                "execution_authority": False,
            },
        )
    return result
