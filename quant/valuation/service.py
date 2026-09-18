"""Orchestration for deterministic and manually-triggered GLM valuation."""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Callable
from uuid import uuid4

from quant.data.audit import write_audit_event

from .absolute import FORMULA_VERSION as ABSOLUTE_VERSION
from .absolute import absolute_valuation
from .calibration import get_calibration, record_forecast, settle_forecasts
from .consensus import build_consensus
from .contracts import derive_growth_rate, model_result, normalize_code, safe_number
from .data import ValuationDataProvider
from .financials import derive_earnings_growth
from .glm import PROMPT_VERSION, glm_valuation
from .market import FORMULA_VERSION as MARKET_VERSION
from .market import market_valuation
from .relative import FORMULA_VERSION as RELATIVE_VERSION
from .relative import relative_valuation
from .store import latest_valuation, save_valuation


DETERMINISTIC_TTL = 30 * 60
GLM_TTL = 30 * 60
FORMULA_VERSIONS = {
    "absolute": ABSOLUTE_VERSION,
    "relative": RELATIVE_VERSION,
    "market": MARKET_VERSION,
    "consensus": "valuation-consensus-v1",
}
_FINANCIAL_FIELDS = (
    "report_period",
    "report_date",
    "end_date",
    "revenue",
    "net_profit",
    "operating_cash_flow",
    "capital_expenditure",
    "total_assets",
    "total_liabilities",
    "equity",
    "eps",
    "bvps",
    "roe",
    "gross_margin",
    "net_margin",
)
_BAR_FIELDS = ("date", "open", "high", "low", "close", "volume", "amount")


def _stable_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _growth_rate(records: list[dict]) -> float | None:
    return derive_growth_rate(records)


class ValuationService:
    """Run isolated valuation tracks and persist a replayable audit trail."""

    def __init__(
        self,
        *,
        cache: Any = None,
        data_provider: Any = None,
        glm_client: Callable[..., dict] | None = None,
        glm_model: str | None = None,
        prompt_version: str = PROMPT_VERSION,
    ):
        if cache is None:
            from quant.data.cache import create_cache

            cache = create_cache()
        self.cache = cache
        if data_provider is None:
            from quant.data.financial_reconciler import (
                fetch_financial_crosscheck,
            )

            data_provider = ValuationDataProvider(
                cache=cache,
                financial_fetcher=fetch_financial_crosscheck,
            )
        self.data_provider = data_provider
        self.glm_client = glm_client
        self.glm_model = (
            glm_model or os.getenv("GLM_MODEL") or "glm-configured"
        )
        self.prompt_version = prompt_version

    @staticmethod
    def _code(value: object) -> str:
        code = normalize_code(value)
        if not code:
            raise ValueError("invalid stock code")
        return code

    def build_data_signature(
        self,
        inputs: dict,
        *,
        formula_versions: dict[str, str] | None = None,
    ) -> str:
        """Hash valuation-driving data and explicit formula versions."""
        versions = {**FORMULA_VERSIONS, **(formula_versions or {})}
        payload = {
            "code": inputs.get("code"),
            "data_date": inputs.get("data_date"),
            "report_period": inputs.get("report_period"),
            "quote": inputs.get("quote"),
            "fundamentals": inputs.get("fundamentals"),
            "financial_history": inputs.get("financial_history"),
            "industry": inputs.get("industry"),
            "daily_history": inputs.get("daily_history"),
            "peers": inputs.get("peers"),
            "market": inputs.get("market"),
            "formula_versions": versions,
            "formula_version_overrides": formula_versions or {},
        }
        return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()

    @staticmethod
    def _target(inputs: dict) -> dict:
        fundamentals = (
            inputs.get("fundamentals")
            if isinstance(inputs.get("fundamentals"), dict)
            else {}
        )
        quote = (
            inputs.get("quote")
            if isinstance(inputs.get("quote"), dict)
            else {}
        )
        history = (
            inputs.get("financial_history")
            if isinstance(inputs.get("financial_history"), dict)
            else {}
        )
        records = (
            history.get("records")
            if isinstance(history.get("records"), list)
            else []
        )
        latest = max(
            (
                row
                for row in records
                if isinstance(row, dict)
            ),
            key=lambda row: str(
                row.get("report_period")
                or row.get("report_date")
                or row.get("end_date")
                or ""
            ),
            default={},
        )
        price = safe_number(quote.get("price"))
        shares = safe_number(fundamentals.get("total_shares"))
        return {
            **fundamentals,
            "code": inputs.get("code"),
            "name": inputs.get("name"),
            "price": price,
            "market_cap": price * shares if price and shares else None,
            "growth_rate": _growth_rate(records),
            "earnings_growth_rate": derive_earnings_growth(records),
            "roe": safe_number(latest.get("roe")),
            "net_margin": safe_number(latest.get("net_margin")),
        }

    @staticmethod
    def build_glm_input(inputs: dict, deterministic: dict) -> dict:
        """Build a bounded evidence packet instead of sending raw histories."""
        quote = inputs.get("quote") if isinstance(inputs.get("quote"), dict) else {}
        financial = (
            inputs.get("financial_history")
            if isinstance(inputs.get("financial_history"), dict)
            else {}
        )
        financial_records = (
            financial.get("records")
            if isinstance(financial.get("records"), list)
            else []
        )
        daily = (
            inputs.get("daily_history")
            if isinstance(inputs.get("daily_history"), dict)
            else {}
        )
        bars = daily.get("bars") if isinstance(daily.get("bars"), list) else []

        def selected(row: object, fields: tuple[str, ...]) -> dict:
            if not isinstance(row, dict):
                return {}
            return {key: row.get(key) for key in fields if row.get(key) is not None}

        compact_tracks = {}
        valuations = (
            deterministic.get("valuations")
            if isinstance(deterministic.get("valuations"), dict)
            else {}
        )
        for kind in ("absolute", "relative", "market"):
            track = valuations.get(kind)
            if not isinstance(track, dict):
                continue
            compact_tracks[kind] = {
                key: track.get(key)
                for key in (
                    "status",
                    "low",
                    "mid",
                    "high",
                    "confidence",
                    "warnings",
                    "details",
                )
                if track.get(key) is not None
            }

        closes = [
            safe_number(row.get("close"))
            for row in bars
            if isinstance(row, dict)
        ]
        closes = [value for value in closes if value is not None and value > 0]
        market = inputs.get("market") if isinstance(inputs.get("market"), dict) else {}
        market_index = (
            market.get("index")
            if isinstance(market.get("index"), dict)
            else {}
        )
        index_bars = (
            market_index.get("bars")
            if isinstance(market_index.get("bars"), list)
            else []
        )
        compact_index = {
            key: market_index.get(key)
            for key in (
                "code",
                "regime",
                "percentile",
                "sample_length",
                "latest_date",
                "source",
                "status",
                "warnings",
            )
            if market_index.get(key) is not None
        }
        if index_bars:
            compact_index["recent_bars"] = [
                selected(row, ("date", "close"))
                for row in index_bars[-12:]
            ]
        return {
            "code": inputs.get("code"),
            "name": inputs.get("name"),
            "current_price": quote.get("price"),
            "data_date": inputs.get("data_date"),
            "report_period": inputs.get("report_period"),
            "deterministic_valuations": compact_tracks,
            "deterministic_consensus": deterministic.get("consensus"),
            "valuation_semantics": {
                "base_value": (
                    "absolute_and_relative_only_weighted_by_confidence_"
                    "data_quality_and_historical_calibration"
                ),
                "market_adjustment": "applied_once_after_base_value",
                "glm_role": "independent_explanation_only_not_in_consensus",
            },
            "fundamentals": inputs.get("fundamentals"),
            "financial_history": {
                "record_count": len(financial_records),
                "recent_records": [
                    selected(row, _FINANCIAL_FIELDS)
                    for row in financial_records[-8:]
                ],
            },
            "daily_history": {
                "bar_count": len(bars),
                "close_min": min(closes) if closes else None,
                "close_max": max(closes) if closes else None,
                "recent_bars": [
                    selected(row, _BAR_FIELDS)
                    for row in bars[-24:]
                ],
            },
            "industry": inputs.get("industry"),
            "market": {
                "breadth": market.get("breadth"),
                "liquidity": market.get("liquidity"),
                "index": compact_index,
                "status": market.get("status"),
                "warnings": market.get("warnings"),
            },
            "data_warnings": (inputs.get("warnings") or [])[:20],
            "safety_boundary": "research_only_no_order_action",
        }

    @staticmethod
    def _track_error(kind: str, exc: Exception) -> dict:
        return model_result(
            kind,
            "error",
            error=f"{kind} valuation failed: {str(exc)[:200]}",
        )

    def _persist(
        self,
        *,
        valuation_id: str,
        inputs: dict,
        kind: str,
        result: dict,
        model_version: str = "",
        prompt_version: str = "",
    ) -> None:
        save_valuation(
            self.cache,
            {
                "valuation_id": valuation_id,
                "code": inputs.get("code"),
                "name": inputs.get("name"),
                "valuation_type": kind,
                "status": result.get("status"),
                "data_date": inputs.get("data_date"),
                "report_period": inputs.get("report_period"),
                "formula_version": FORMULA_VERSIONS.get(kind, ""),
                "model_version": model_version,
                "prompt_version": prompt_version,
                "input": inputs,
                "output": result,
            },
        )
        write_audit_event(
            self.cache,
            "stock_valuation",
            {
                "valuation_id": valuation_id,
                "code": inputs.get("code"),
                "valuation_type": kind,
                "status": result.get("status"),
                "data_date": inputs.get("data_date"),
                "report_period": inputs.get("report_period"),
                "formula_version": FORMULA_VERSIONS.get(kind, ""),
                "model_version": model_version,
                "prompt_version": prompt_version,
                "safety_boundary": "research_only_no_order_action",
            },
            source="valuation_service",
            ref_id=f"{inputs.get('code')}:{kind}",
        )

    def analyze(self, code: str, force: bool = False) -> dict:
        """Run three deterministic tracks. This method never calls an LLM."""
        normalized = self._code(code)
        inputs = self.data_provider.get_valuation_inputs(normalized)
        signature = self.build_data_signature(inputs)
        cache_key = f"valuation:analysis:{normalized}:{signature}"
        if not force:
            cached = self.cache.get(cache_key)
            if isinstance(cached, dict):
                return cached

        valuation_id = uuid4().hex
        target = self._target(inputs)
        peer_section = (
            inputs.get("peers")
            if isinstance(inputs.get("peers"), dict)
            else {}
        )
        peers = (
            peer_section.get("peers")
            if isinstance(peer_section.get("peers"), list)
            else []
        )
        try:
            absolute = absolute_valuation(inputs)
        except Exception as exc:
            absolute = self._track_error("absolute", exc)
        try:
            relative = relative_valuation(target, peers)
        except Exception as exc:
            relative = self._track_error("relative", exc)
        daily = (
            inputs.get("daily_history")
            if isinstance(inputs.get("daily_history"), dict)
            else {}
        )
        bars = daily.get("bars") if isinstance(daily.get("bars"), list) else []
        settle_forecasts(self.cache, normalized, bars)
        calibration = {
            "absolute": get_calibration(self.cache, "absolute"),
            "relative": get_calibration(self.cache, "relative"),
        }
        history = (
            inputs.get("financial_history")
            if isinstance(inputs.get("financial_history"), dict)
            else {}
        )
        peer_quality = min(1.0, len(peers) / 8) if peers else 0.0
        data_quality = {
            "absolute": safe_number(
                history.get("point_in_time_quality_score")
            )
            or 0.75,
            "relative": peer_quality,
        }
        base_consensus = build_consensus(
            {"absolute": absolute, "relative": relative},
            data_quality=data_quality,
            calibration=calibration,
            market_adjustment=0.0,
        )
        reference_mid = safe_number(base_consensus.get("base_mid"))
        market_context = (
            inputs.get("market")
            if isinstance(inputs.get("market"), dict)
            else {}
        )
        try:
            market = market_valuation(
                target,
                bars,
                market_context,
                peers=peers,
                reference_mid=reference_mid,
            )
        except Exception as exc:
            market = self._track_error("market", exc)
        market_adjustment = safe_number(
            (market.get("details") or {}).get("adjustment")
        )
        consensus = build_consensus(
            {"absolute": absolute, "relative": relative},
            data_quality=data_quality,
            calibration=calibration,
            market_adjustment=market_adjustment or 0.0,
        )
        valuations = {
            "absolute": absolute,
            "relative": relative,
            "market": market,
        }
        for kind, result in valuations.items():
            self._persist(
                valuation_id=valuation_id,
                inputs=inputs,
                kind=kind,
                result=result,
            )
        consensus_result = model_result(
            "consensus",
            consensus.get("status", "unavailable"),
            low=consensus.get("final_low"),
            mid=consensus.get("final_mid"),
            high=consensus.get("final_high"),
            confidence=(
                sum(consensus.get("raw_weights", {}).values())
                / max(1, len(consensus.get("raw_weights", {})))
                if consensus.get("raw_weights")
                else None
            ),
            details=consensus,
        )
        for kind, result in {
            "absolute": absolute,
            "relative": relative,
            "consensus": consensus_result,
        }.items():
            record_forecast(
                self.cache,
                valuation_id=valuation_id,
                code=normalized,
                model_type=kind,
                predicted_mid=result.get("mid"),
                spot_price=target.get("price"),
            )
        response = {
            "valuation_id": valuation_id,
            "code": normalized,
            "name": inputs.get("name"),
            "data_signature": signature,
            "data_date": inputs.get("data_date"),
            "report_period": inputs.get("report_period"),
            "current_price": target.get("price"),
            "valuations": valuations,
            "consensus": consensus,
            "calibration": calibration,
            "financial_quality": {
                "valuation_as_of": history.get("valuation_as_of"),
                "financial_as_of": history.get("financial_as_of"),
                "point_in_time_quality": history.get("point_in_time_quality"),
                "point_in_time_quality_score": history.get(
                    "point_in_time_quality_score"
                ),
                "ttm_formula": (
                    history.get("ttm", {}).get("formula")
                    if isinstance(history.get("ttm"), dict)
                    else None
                ),
            },
            "sources": inputs.get("sources") or [],
            "warnings": inputs.get("warnings") or [],
            "safety_boundary": "research_only_no_order_action",
        }
        self.cache.set(cache_key, response, ttl=DETERMINISTIC_TTL)
        self.cache.set(
            f"valuation:analysis_latest:{normalized}",
            response,
            ttl=DETERMINISTIC_TTL,
        )
        return response

    def glm_analyze(
        self,
        code: str,
        force: bool = False,
        *,
        provider: str = "glm",
        model: str | None = None,
        model_source: str = "legacy_default",
    ) -> dict:
        """Manually run the independent AI valuation track."""
        normalized = self._code(code)
        effective_model = str(model or self.glm_model)
        deterministic = self.analyze(normalized)
        inputs = self.data_provider.get_valuation_inputs(normalized)
        signature = self.build_data_signature(inputs)
        glm_signature = hashlib.sha256(
            (
                signature
                + "|"
                + provider
                + "|"
                + effective_model
                + "|"
                + self.prompt_version
            ).encode("utf-8")
        ).hexdigest()
        cache_key = f"valuation:glm:{normalized}:{glm_signature}"
        if not force:
            cached = self.cache.get(cache_key)
            if isinstance(cached, dict):
                return cached

        valuation_id = uuid4().hex
        structured_input = self.build_glm_input(inputs, deterministic)
        result, call_meta = glm_valuation(
            structured_input,
            current_price=structured_input["current_price"],
            chat_json_fn=self.glm_client,
            provider=provider,
            model=effective_model,
        )
        self._persist(
            valuation_id=valuation_id,
            inputs=inputs,
            kind="glm",
            result=result,
            model_version=effective_model,
            prompt_version=self.prompt_version,
        )
        response = {
            "valuation_id": valuation_id,
            "code": normalized,
            "name": inputs.get("name"),
            "data_signature": signature,
            "provider": provider,
            "model": call_meta.get("model") or effective_model,
            "model_source": model_source,
            "model_version": effective_model,
            "prompt_version": self.prompt_version,
            "valuation": result,
            "usage": call_meta.get("usage") or {},
            "safety_boundary": "independent_research_only_no_order_action",
        }
        if result.get("status") == "success":
            self.cache.set(cache_key, response, ttl=GLM_TTL)
        return response

    def latest(self, code: str) -> dict:
        normalized = self._code(code)
        valuations = {}
        for kind in ("absolute", "relative", "market", "glm"):
            row = latest_valuation(self.cache, normalized, kind)
            if row is not None:
                valuations[kind] = row
        return {"code": normalized, "valuations": valuations}
