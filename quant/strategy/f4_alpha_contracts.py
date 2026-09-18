"""Immutable contracts for the research-only F4 v2 alpha registry."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .f4_candidate_factory import (
    FACTORY_VERSION_V1,
    FACTORY_VERSION_V2,
    SUPPORTED_FACTORY_VERSIONS,
    canonical_payload_hash,
)
from .f4_contracts import authority_fields
from .portfolio import PortfolioPolicy


FORBIDDEN_FUNDAMENTAL_FEATURES = frozenset(
    {
        "roe",
        "roa",
        "gross_margin",
        "net_margin",
        "revenue_growth",
        "profit_growth",
        "debt_ratio",
        "current_ratio",
        "inventory_turnover",
        "receivable_turnover",
        "asset_turnover",
    }
)

_FAMILY_PREFIXES = {
    "momentum": "M",
    "reversal": "R",
    "defensive": "D",
    "liquidity": "L",
    "ensemble": "E",
    "qlib": "Q",
}
_RULE_FAMILIES = frozenset({"momentum", "reversal", "defensive", "liquidity"})
BASE_RULE_ALPHA_IDS = (
    "M1",
    "M2",
    "M3",
    "M4",
    "R1",
    "R2",
    "R3",
    "R4",
    "D1",
    "D2",
    "D3",
    "D4",
    "L1",
    "L2",
    "L3",
    "L4",
)
_SAFE_POLICY = {
    "top_k": 10,
    "target_gross_exposure": 0.95,
    "max_name_weight": 0.095,
    "max_industry_weight": 0.25,
    "lot_size": 100,
    "adv_participation": 0.10,
}
_ENSEMBLE_CONTRACTS = {
    "E1": (BASE_RULE_ALPHA_IDS, "equal_family_sleeves"),
    "E2": (BASE_RULE_ALPHA_IDS, "train_rank_ic_shrinkage"),
    "E3": (BASE_RULE_ALPHA_IDS, "train_correlation_cluster"),
    "E4": (BASE_RULE_ALPHA_IDS, "train_subperiod_stability"),
}
_QLIB_CONTRACTS = {
    "Q1": ("Alpha158", "LightGBM"),
    "Q2": ("Alpha360", "LightGBM"),
    "Q3": ("Alpha158", "XGBoost"),
    "Q4": ("Alpha158", "Linear"),
}


@dataclass(frozen=True, slots=True)
class AlphaSpec:
    alpha_id: str
    family: str
    input_features: tuple[str, ...]
    formula: tuple[tuple[str, float], ...]
    preprocessing: str
    fit_method: str
    label_horizon_bars: int = 5
    minimum_coverage: float = 0.95
    seed: int = 20260821
    handler: str = ""
    model_type: str = ""
    version: str = "f4-alpha-spec-v2"


@dataclass(frozen=True, slots=True)
class F4CandidateV2:
    family: str
    alpha_spec: AlphaSpec
    portfolio_policy: PortfolioPolicy
    version: str = FACTORY_VERSION_V2

    def payload(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "alpha_spec": asdict(self.alpha_spec),
            "portfolio_policy": asdict(self.portfolio_policy),
            "version": self.version,
        }

    @property
    def candidate_id(self) -> str:
        return canonical_payload_hash(self.payload())

    def to_dict(self) -> dict[str, Any]:
        return {"candidate_id": self.candidate_id, **self.payload(), **authority_fields()}

    def validate(self) -> None:
        if self.version != FACTORY_VERSION_V2:
            raise ValueError("candidate_version_invalid")
        prefix = _FAMILY_PREFIXES.get(self.family)
        if prefix is None:
            raise ValueError("candidate_family_invalid")
        alpha = self.alpha_spec
        if alpha.family != self.family:
            raise ValueError("candidate_alpha_family_mismatch")
        if alpha.alpha_id not in {f"{prefix}{index}" for index in range(1, 5)}:
            raise ValueError("candidate_alpha_id_invalid")
        if alpha.version != "f4-alpha-spec-v2":
            raise ValueError("alpha_spec_version_invalid")
        if (
            not isinstance(alpha.label_horizon_bars, int)
            or isinstance(alpha.label_horizon_bars, bool)
            or alpha.label_horizon_bars <= 0
        ):
            raise ValueError("alpha_label_horizon_invalid")
        if not math.isfinite(float(alpha.minimum_coverage)) or not (
            0.0 < float(alpha.minimum_coverage) <= 1.0
        ):
            raise ValueError("alpha_minimum_coverage_invalid")
        if not alpha.preprocessing or not alpha.fit_method:
            raise ValueError("alpha_processing_contract_invalid")

        feature_names = tuple(str(feature).strip() for feature in alpha.input_features)
        formula_features = tuple(str(feature).strip() for feature, _weight in alpha.formula)
        checked_features = {
            feature.lower().lstrip("+-") for feature in (*feature_names, *formula_features)
        }
        if checked_features & FORBIDDEN_FUNDAMENTAL_FEATURES:
            raise ValueError("fundamental_feature_forbidden")
        for _feature, weight in alpha.formula:
            try:
                finite = math.isfinite(float(weight))
            except (TypeError, ValueError):
                finite = False
            if not finite:
                raise ValueError("alpha_formula_weight_nonfinite")

        if self.family in _RULE_FAMILIES:
            if (
                not feature_names
                or not alpha.formula
                or feature_names != formula_features
                or alpha.fit_method != "fixed_weighted_sum"
                or alpha.handler
                or alpha.model_type
            ):
                raise ValueError("rule_alpha_contract_invalid")
        elif self.family == "ensemble":
            expected_features, expected_fit = _ENSEMBLE_CONTRACTS[alpha.alpha_id]
            if (
                alpha.formula
                or feature_names != expected_features
                or alpha.fit_method != expected_fit
                or alpha.handler
                or alpha.model_type
            ):
                raise ValueError("ensemble_contract_invalid")
        else:
            expected_handler, expected_model = _QLIB_CONTRACTS[alpha.alpha_id]
            if (
                alpha.formula
                or feature_names
                or alpha.fit_method != "qlib_model"
                or alpha.handler != expected_handler
                or alpha.model_type != expected_model
            ):
                raise ValueError("qlib_contract_invalid")

        policy = self.portfolio_policy
        if any(getattr(policy, field) != value for field, value in _SAFE_POLICY.items()):
            raise ValueError("candidate_policy_unsafe")
        if (
            not isinstance(policy.rebalance_bars, int)
            or isinstance(policy.rebalance_bars, bool)
            or policy.rebalance_bars <= 0
        ):
            raise ValueError("candidate_rebalance_invalid")
        if policy.version != "f4-standard-top10-policy-v2":
            raise ValueError("candidate_policy_version_invalid")
        if authority_fields() != {
            "promotion_state": "research_only",
            "execution_authority": False,
        }:
            raise ValueError("candidate_authority_invalid")
        approved = _APPROVED_BY_ALPHA_ID.get(alpha.alpha_id)
        if approved is None:
            raise ValueError("candidate_alpha_id_unregistered")
        if alpha != approved.alpha_spec:
            raise ValueError("candidate_alpha_spec_unregistered")
        if policy != approved.portfolio_policy:
            raise ValueError("candidate_policy_unregistered")


def _policy(rebalance_bars: int) -> PortfolioPolicy:
    return PortfolioPolicy(
        top_k=10,
        rebalance_bars=rebalance_bars,
        max_name_weight=0.095,
        max_industry_weight=0.25,
        lot_size=100,
        adv_participation=0.10,
        target_gross_exposure=0.95,
        version="f4-standard-top10-policy-v2",
    )


def _rule_candidate(
    alpha_id: str,
    family: str,
    formula: tuple[tuple[str, float], ...],
    rebalance_bars: int,
) -> F4CandidateV2:
    return F4CandidateV2(
        family=family,
        alpha_spec=AlphaSpec(
            alpha_id=alpha_id,
            family=family,
            input_features=tuple(feature for feature, _weight in formula),
            formula=formula,
            preprocessing="cross_sectional_winsorize_zscore",
            fit_method="fixed_weighted_sum",
        ),
        portfolio_policy=_policy(rebalance_bars),
    )


def _ensemble_candidate(alpha_id: str, rebalance_bars: int) -> F4CandidateV2:
    input_features, fit_method = _ENSEMBLE_CONTRACTS[alpha_id]
    return F4CandidateV2(
        family="ensemble",
        alpha_spec=AlphaSpec(
            alpha_id=alpha_id,
            family="ensemble",
            input_features=input_features,
            formula=(),
            preprocessing="cross_sectional_rank_normalize",
            fit_method=fit_method,
        ),
        portfolio_policy=_policy(rebalance_bars),
    )


def _qlib_candidate(alpha_id: str) -> F4CandidateV2:
    handler, model_type = _QLIB_CONTRACTS[alpha_id]
    return F4CandidateV2(
        family="qlib",
        alpha_spec=AlphaSpec(
            alpha_id=alpha_id,
            family="qlib",
            input_features=(),
            formula=(),
            preprocessing="qlib_handler_default",
            fit_method="qlib_model",
            handler=handler,
            model_type=model_type,
        ),
        portfolio_policy=_policy(5),
    )


def validate_v2_candidate_registry(
    candidates: Iterable[F4CandidateV2],
) -> tuple[F4CandidateV2, ...]:
    registry = tuple(candidates)
    alpha_ids: set[str] = set()
    candidate_ids: set[str] = set()
    for candidate in registry:
        alpha_id = candidate.alpha_spec.alpha_id
        if alpha_id in alpha_ids:
            raise ValueError("alpha_id_duplicate")
        candidate.validate()
        if candidate.candidate_id in candidate_ids:
            raise ValueError("candidate_id_duplicate")
        alpha_ids.add(alpha_id)
        candidate_ids.add(candidate.candidate_id)
    return registry


_APPROVED_CANDIDATES = (
            _rule_candidate("M1", "momentum", (("ret_20", 0.60), ("ret_60", 0.40)), 20),
            _rule_candidate(
                "M2",
                "momentum",
                (("ret_5", 0.40), ("ret_10", 0.35), ("roc_10", 0.25)),
                10,
            ),
            _rule_candidate(
                "M3",
                "momentum",
                (
                    ("ret_20_over_volatility_20", 0.60),
                    ("ret_60_over_volatility_60", 0.40),
                ),
                20,
            ),
            _rule_candidate(
                "M4",
                "momentum",
                (
                    ("trend_strength", 0.35),
                    ("ema_gap_12", 0.25),
                    ("macd_hist_norm", 0.20),
                    ("ret_20", 0.20),
                ),
                10,
            ),
            _rule_candidate("R1", "reversal", (("reversal_3", 1.0),), 5),
            _rule_candidate("R2", "reversal", (("reversal_5", 1.0),), 5),
            _rule_candidate("R3", "reversal", (("reversal_10", 1.0),), 10),
            _rule_candidate(
                "R4",
                "reversal",
                (
                    ("-overnight_ret", 0.40),
                    ("-intraday_ret", 0.35),
                    ("-bias_20", 0.25),
                ),
                5,
            ),
            _rule_candidate(
                "D1",
                "defensive",
                (("-volatility_5", 0.40), ("-volatility_20", 0.60)),
                10,
            ),
            _rule_candidate(
                "D2",
                "defensive",
                (
                    ("-volatility_20", 0.60),
                    ("-volatility_60", 0.25),
                    ("-range_pct", 0.15),
                ),
                20,
            ),
            _rule_candidate(
                "D3",
                "defensive",
                (("-atr_14_norm", 0.45), ("-range_pct", 0.30), ("-boll_width", 0.25)),
                10,
            ),
            _rule_candidate(
                "D4",
                "defensive",
                (("-volatility_20", 0.60), ("trend_strength", 0.25), ("ret_20", 0.15)),
                20,
            ),
            _rule_candidate(
                "L1",
                "liquidity",
                (("vol_ratio_5", 0.55), ("turnover_5_over_20", 0.45)),
                5,
            ),
            _rule_candidate(
                "L2",
                "liquidity",
                (("amt_ratio_5", 0.50), ("vol_ratio_5", 0.30), ("pvcorr_5", 0.20)),
                5,
            ),
            _rule_candidate(
                "L3",
                "liquidity",
                (("obv_slope_10", 0.50), ("ad_slope_10", 0.50)),
                10,
            ),
            _rule_candidate(
                "L4",
                "liquidity",
                (
                    ("mfi_14", 0.35),
                    ("vwap_dev_20", 0.30),
                    ("pvcorr_10", 0.20),
                    ("pvbeta_20", 0.15),
                ),
                10,
            ),
            _ensemble_candidate("E1", 10),
            _ensemble_candidate("E2", 10),
            _ensemble_candidate("E3", 10),
            _ensemble_candidate("E4", 20),
            _qlib_candidate("Q1"),
            _qlib_candidate("Q2"),
            _qlib_candidate("Q3"),
            _qlib_candidate("Q4"),
)
_APPROVED_BY_ALPHA_ID = {
    candidate.alpha_spec.alpha_id: candidate for candidate in _APPROVED_CANDIDATES
}


def build_v2_candidate_registry() -> tuple[F4CandidateV2, ...]:
    registry = validate_v2_candidate_registry(_APPROVED_CANDIDATES)
    if len(registry) != 24 or Counter(item.family for item in registry) != {
        family: 4 for family in _FAMILY_PREFIXES
    }:
        raise ValueError("candidate_registry_shape_invalid")
    return registry


__all__ = [
    "FACTORY_VERSION_V1",
    "FACTORY_VERSION_V2",
    "SUPPORTED_FACTORY_VERSIONS",
    "FORBIDDEN_FUNDAMENTAL_FEATURES",
    "BASE_RULE_ALPHA_IDS",
    "AlphaSpec",
    "F4CandidateV2",
    "build_v2_candidate_registry",
    "validate_v2_candidate_registry",
]
