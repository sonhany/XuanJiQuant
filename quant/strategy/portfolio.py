"""Pure deterministic portfolio construction for F4 research."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Mapping


@dataclass(frozen=True, slots=True)
class PortfolioPolicy:
    top_k: int = 20
    rebalance_bars: int = 5
    max_name_weight: float = 0.10
    max_industry_weight: float = 0.25
    lot_size: int = 100
    adv_participation: float = 0.10
    target_gross_exposure: float = 1.0
    version: str = "portfolio-policy-v1"


@dataclass(frozen=True, slots=True)
class PortfolioTarget:
    weights: dict[str, float]
    cash_weight: float
    exclusions: dict[str, int] = field(default_factory=dict)


def build_target_weights(
    rows: Iterable[Mapping[str, object]], policy: PortfolioPolicy
) -> PortfolioTarget:
    valid: list[tuple[float, str, str]] = []
    invalid = 0
    for row in rows:
        code = str(row.get("code") or "").strip()
        try:
            score = float(row.get("score"))
        except (TypeError, ValueError):
            invalid += 1
            continue
        if not code or not math.isfinite(score):
            invalid += 1
            continue
        industry = str(row.get("industry") or "industry_unknown").strip()
        valid.append((score, code, industry or "industry_unknown"))
    valid.sort(key=lambda item: (-item[0], item[1]))
    candidates = valid[: max(0, int(policy.top_k))]
    if not candidates:
        exclusions = {"invalid_score": invalid} if invalid else {}
        return PortfolioTarget(weights={}, cash_weight=1.0, exclusions=exclusions)

    gross = min(1.0, max(0.0, float(policy.target_gross_exposure)))
    base_weight = min(
        gross / max(1, int(policy.top_k)), max(0.0, policy.max_name_weight)
    )
    industry_totals: dict[str, float] = {}
    weights: dict[str, float] = {}
    exclusions: dict[str, int] = {}
    if invalid:
        exclusions["invalid_score"] = invalid
    for _score, code, industry in candidates:
        if industry_totals.get(industry, 0.0) + base_weight > policy.max_industry_weight + 1e-12:
            exclusions["industry_cap"] = exclusions.get("industry_cap", 0) + 1
            continue
        weights[code] = base_weight
        industry_totals[industry] = industry_totals.get(industry, 0.0) + base_weight
    total_weight = sum(weights.values())
    if total_weight > gross and weights:
        # Repeated binary floating-point additions can exceed the exact gross
        # target by a few ulps (for example, 20 * 0.05).  Keep the persisted
        # target fail-closed by absorbing that deterministic residue into the
        # final selected name instead of publishing an over-gross portfolio.
        last_code = next(reversed(weights))
        weights[last_code] = max(0.0, weights[last_code] - (total_weight - gross))
    invested = min(1.0, sum(weights.values()))
    return PortfolioTarget(
        weights=weights,
        cash_weight=max(0.0, 1.0 - invested),
        exclusions=exclusions,
    )
