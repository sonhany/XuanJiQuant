"""Deterministic FCFF/FCFE discounted cash-flow valuation."""
from __future__ import annotations

from statistics import median

from .contracts import derive_growth_rate, model_result, safe_number
from .financials import annual_records


FORMULA_VERSION = "absolute-dcf-v3"


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def cost_of_equity(risk_free: float, beta: float, market_risk_premium: float) -> float:
    return risk_free + beta * market_risk_premium


def weighted_average_cost_of_capital(
    equity_value: float,
    debt_value: float,
    equity_cost: float,
    pre_tax_cost_of_debt: float,
    tax_rate: float,
) -> tuple[float, dict]:
    total = max(0.0, equity_value) + max(0.0, debt_value)
    if total <= 0:
        return equity_cost, {
            "equity_weight": 1.0,
            "debt_weight": 0.0,
            "pre_tax_cost_of_debt": pre_tax_cost_of_debt,
            "after_tax_cost_of_debt": pre_tax_cost_of_debt * (1 - tax_rate),
            "tax_rate": tax_rate,
        }
    equity_weight = max(0.0, equity_value) / total
    debt_weight = max(0.0, debt_value) / total
    after_tax_cost = pre_tax_cost_of_debt * (1 - tax_rate)
    wacc = equity_weight * equity_cost + debt_weight * after_tax_cost
    return wacc, {
        "equity_weight": equity_weight,
        "debt_weight": debt_weight,
        "pre_tax_cost_of_debt": pre_tax_cost_of_debt,
        "after_tax_cost_of_debt": after_tax_cost,
        "tax_rate": tax_rate,
    }


def _normalized_annual_cash_flow(
    records: list[dict],
    field: str,
) -> tuple[float | None, list[dict]]:
    samples = []
    for row in annual_records(records)[-3:]:
        value = safe_number(row.get(field))
        if value is not None:
            samples.append(
                {
                    "period": str(
                        row.get("report_period")
                        or row.get("report_date")
                        or row.get("end_date")
                        or ""
                    ),
                    "value": value,
                }
            )
    if len(samples) < 3:
        return None, []
    return median(sample["value"] for sample in samples), samples


def _latest_positive_cash_flow(
    records: list[dict],
    field: str,
) -> tuple[float | None, str | None]:
    candidates: list[tuple[str, float]] = []
    for row in records:
        if not isinstance(row, dict):
            continue
        period = str(
            row.get("report_period")
            or row.get("report_date")
            or row.get("end_date")
            or ""
        )
        value = safe_number(row.get(field))
        if period and value is not None and value > 0:
            candidates.append((period, value))
    if not candidates:
        return None, None
    return max(candidates, key=lambda item: item[0])[1], max(
        candidates, key=lambda item: item[0]
    )[0]


def _forecast_schedule(growth: float, terminal_growth: float, years: int = 5) -> list[dict]:
    schedule: list[dict] = []
    for year in range(1, years + 1):
        if year <= 3:
            year_growth = growth * (1 - 0.08 * (year - 1))
            stage = "high_growth"
        else:
            progress = (year - 3) / 3
            year_growth = growth + (terminal_growth - growth) * progress
            stage = "transition"
        schedule.append(
            {
                "year": year,
                "stage": stage,
                "growth": _clamp(year_growth, -0.20, 0.50),
            }
        )
    return schedule


def discounted_cash_flow(
    base_cash: float,
    growth: float,
    discount: float,
    terminal_growth: float,
    years: int = 5,
) -> float | None:
    """Return present value for a staged cash-flow forecast."""
    if (
        base_cash <= 0
        or years <= 0
        or not (-0.20 <= growth <= 0.50)
        or not (0 <= terminal_growth < discount < 0.30)
    ):
        return None
    current = base_cash
    present = 0.0
    schedule = _forecast_schedule(growth, terminal_growth, years)
    for row in schedule:
        current *= 1 + row["growth"]
        present += current / (1 + discount) ** row["year"]
    terminal = current * (1 + terminal_growth) / (discount - terminal_growth)
    return present + terminal / (1 + discount) ** years


def absolute_valuation(inputs: dict, *, assumptions: dict | None = None) -> dict:
    """Value one stock with FCFE/Ke or FCFF/WACC, never mixing the two."""
    assumptions = assumptions or {}
    fundamentals = inputs.get("fundamentals") if isinstance(inputs.get("fundamentals"), dict) else {}
    history = inputs.get("financial_history") if isinstance(inputs.get("financial_history"), dict) else {}
    records = history.get("records") if isinstance(history.get("records"), list) else []
    warnings: list[str] = []

    shares = safe_number(fundamentals.get("total_shares"))
    if shares is None or shares <= 0:
        return model_result(
            "absolute",
            "unavailable",
            error="缺少有效总股本，无法换算每股价值",
            details={"formula_version": FORMULA_VERSION},
        )

    normalized_fcff, fcff_samples = _normalized_annual_cash_flow(
        records, "enterprise_fcf_per_share"
    )
    normalized_fcfe, fcfe_samples = _normalized_annual_cash_flow(
        records, "shareholder_fcf_per_share"
    )
    cash_flow_is_equity = False
    cash_flow_period = None
    normalized_details: dict = {}
    if normalized_fcff is not None and normalized_fcff > 0:
        base_cash = normalized_fcff * shares
        cash_flow_method = "normalized_fcff"
        normalized_details = {"per_share": normalized_fcff, "samples": fcff_samples}
        cash_flow_period = fcff_samples[-1]["period"]
    elif normalized_fcfe is not None and normalized_fcfe > 0:
        base_cash = normalized_fcfe * shares
        cash_flow_method = "normalized_fcfe"
        normalized_details = {"per_share": normalized_fcfe, "samples": fcfe_samples}
        cash_flow_period = fcfe_samples[-1]["period"]
        cash_flow_is_equity = True
    else:
        ttm = history.get("ttm") if isinstance(history.get("ttm"), dict) else {}
        ttm_fcff = safe_number(ttm.get("enterprise_fcf_per_share"))
        ttm_fcfe = safe_number(ttm.get("shareholder_fcf_per_share"))
        latest_fcff, latest_fcff_period = _latest_positive_cash_flow(
            records, "enterprise_fcf_per_share"
        )
        latest_fcfe, latest_fcfe_period = _latest_positive_cash_flow(
            records, "shareholder_fcf_per_share"
        )
        latest_period = max(
            str(
                row.get("report_period")
                or row.get("report_date")
                or row.get("end_date")
                or ""
            )
            for row in records
            if isinstance(row, dict)
        ) if records else ""
        latest_row = next(
            (
                row
                for row in reversed(records)
                if isinstance(row, dict)
                and str(
                    row.get("report_period")
                    or row.get("report_date")
                    or row.get("end_date")
                    or ""
                ) == latest_period
            ),
            {},
        )
        latest_row_fcff = safe_number(latest_row.get("enterprise_fcf_per_share"))
        latest_row_fcfe = safe_number(latest_row.get("shareholder_fcf_per_share"))
        if latest_row_fcff is not None and latest_row_fcff > 0:
            base_cash = latest_row_fcff * shares
            cash_flow_method = "reported_fcff_per_share"
            cash_flow_period = latest_period
            normalized_details = {"per_share": latest_row_fcff, "samples": []}
        elif latest_row_fcfe is not None and latest_row_fcfe > 0:
            base_cash = latest_row_fcfe * shares
            cash_flow_method = "reported_fcfe_per_share"
            cash_flow_period = latest_period
            normalized_details = {"per_share": latest_row_fcfe, "samples": []}
            cash_flow_is_equity = True
        elif ttm_fcff is not None and ttm_fcff > 0:
            base_cash = ttm_fcff * shares
            cash_flow_method = "ttm_fcff"
            cash_flow_period = ttm.get("period")
            normalized_details = {"per_share": ttm_fcff, "formula": ttm.get("formula")}
        elif ttm_fcfe is not None and ttm_fcfe > 0:
            base_cash = ttm_fcfe * shares
            cash_flow_method = "ttm_fcfe"
            cash_flow_period = ttm.get("period")
            normalized_details = {"per_share": ttm_fcfe, "formula": ttm.get("formula")}
            cash_flow_is_equity = True
        elif latest_fcff is not None:
            base_cash = latest_fcff * shares
            cash_flow_method = "reported_fcff_per_share"
            cash_flow_period = latest_fcff_period
            normalized_details = {"per_share": latest_fcff, "samples": []}
        elif latest_fcfe is not None:
            base_cash = latest_fcfe * shares
            cash_flow_method = "reported_fcfe_per_share"
            cash_flow_period = latest_fcfe_period
            normalized_details = {"per_share": latest_fcfe, "samples": []}
            cash_flow_is_equity = True
        else:
            operating_cash = safe_number(fundamentals.get("operating_cash_flow"))
            if operating_cash is None or operating_cash <= 0:
                return model_result(
                    "absolute",
                    "unavailable",
                    error="经营现金流不足，禁止使用净利润替代自由现金流",
                    details={"formula_version": FORMULA_VERSION},
                )
            capex = safe_number(fundamentals.get("capex"))
            if capex is not None and capex >= 0:
                base_cash = operating_cash - capex
                cash_flow_method = "ocf_minus_capex"
            else:
                revenue = safe_number(fundamentals.get("revenue"))
                proxy = max(operating_cash * 0.15, (revenue or 0.0) * 0.03)
                base_cash = operating_cash - proxy
                cash_flow_method = "maintenance_capex_proxy"
                warnings.append("资本开支缺失，使用维护性资本开支代理")
            normalized_details = {"total": base_cash, "samples": []}

    if base_cash <= 0:
        return model_result(
            "absolute",
            "unavailable",
            error="自由现金流不为正，DCF 当前不可用",
            details={"formula_version": FORMULA_VERSION, "cash_flow_method": cash_flow_method},
            warnings=warnings,
        )

    derived_growth = derive_growth_rate(records)
    growth = safe_number(assumptions.get("growth"))
    if growth is None:
        growth = derived_growth if derived_growth is not None else 0.06
        if derived_growth is None:
            warnings.append("历史增长样本不足，使用6%基准增长假设")
    growth = _clamp(growth, -0.05, 0.25)

    market = inputs.get("market") if isinstance(inputs.get("market"), dict) else {}
    risk_free = safe_number(assumptions.get("risk_free_rate", market.get("risk_free_rate")))
    premium = safe_number(assumptions.get("market_risk_premium", market.get("market_risk_premium")))
    beta = safe_number(assumptions.get("beta", inputs.get("beta")))
    risk_free = 0.025 if risk_free is None else _clamp(risk_free, 0.0, 0.10)
    premium = 0.055 if premium is None else _clamp(premium, 0.02, 0.12)
    beta = 1.0 if beta is None else _clamp(beta, 0.2, 2.5)
    equity_cost = safe_number(assumptions.get("cost_of_equity"))
    equity_cost = equity_cost if equity_cost is not None else cost_of_equity(risk_free, beta, premium)

    debt = max(0.0, safe_number(fundamentals.get("long_term_debt")) or 0.0)
    cash = max(0.0, safe_number(fundamentals.get("cash")) or 0.0)
    quote = inputs.get("quote") if isinstance(inputs.get("quote"), dict) else {}
    price = safe_number(quote.get("price"))
    equity_value = price * shares if price and price > 0 else max(shares, debt * 4)
    pre_tax_cost = safe_number(assumptions.get("pre_tax_cost_of_debt"))
    pre_tax_cost = pre_tax_cost if pre_tax_cost is not None else risk_free + 0.02
    tax_rate = safe_number(assumptions.get("tax_rate"))
    tax_rate = 0.25 if tax_rate is None else _clamp(tax_rate, 0.0, 0.50)
    wacc, wacc_components = weighted_average_cost_of_capital(
        equity_value, debt, equity_cost, pre_tax_cost, tax_rate
    )

    if cash_flow_is_equity:
        discount_rate = equity_cost
        discount_rate_type = "cost_of_equity"
    else:
        override_wacc = safe_number(assumptions.get("wacc"))
        discount_rate = override_wacc if override_wacc is not None else wacc
        discount_rate_type = "wacc"
    terminal_growth = safe_number(assumptions.get("terminal_growth"))
    terminal_growth = 0.02 if terminal_growth is None else terminal_growth
    if not (0 <= terminal_growth <= 0.03 and terminal_growth < discount_rate < 0.30):
        label = "股权资本成本" if cash_flow_is_equity else "WACC"
        return model_result(
            "absolute",
            "unavailable",
            error=f"{label}必须高于永续增长率且低于30%",
            details={
                "formula_version": FORMULA_VERSION,
                "discount_rate_type": discount_rate_type,
                "discount_rate": discount_rate,
                "wacc": wacc,
                "cost_of_equity": equity_cost,
                "terminal_growth": terminal_growth,
            },
            warnings=warnings,
        )

    scenarios = {
        "conservative": {
            "growth": _clamp(growth - 0.03, -0.08, 0.20),
            "discount_rate": _clamp(discount_rate + 0.015, terminal_growth + 0.01, 0.29),
            "terminal_growth": _clamp(terminal_growth - 0.01, 0.0, 0.02),
        },
        "base": {
            "growth": growth,
            "discount_rate": discount_rate,
            "terminal_growth": terminal_growth,
        },
        "optimistic": {
            "growth": _clamp(growth + 0.03, -0.02, 0.28),
            "discount_rate": _clamp(discount_rate - 0.01, terminal_growth + 0.005, 0.29),
            "terminal_growth": _clamp(terminal_growth + 0.005, 0.0, 0.03),
        },
    }
    scenario_values: dict[str, dict[str, float]] = {}
    for name, params in scenarios.items():
        present_value = discounted_cash_flow(
            base_cash,
            params["growth"],
            params["discount_rate"],
            params["terminal_growth"],
        )
        if present_value is None:
            continue
        equity = present_value if cash_flow_is_equity else present_value - debt + cash
        scenario_values[name] = {
            **params,
            "wacc": params["discount_rate"],
            "enterprise_value": present_value,
            "equity_value": equity,
            "per_share": equity / shares if equity > 0 else 0.0,
        }
    if len(scenario_values) != 3:
        return model_result(
            "absolute",
            "unavailable",
            error="DCF 情景参数无法形成有效估值",
            details={"formula_version": FORMULA_VERSION},
            warnings=warnings,
        )

    sensitivity: list[dict] = []
    for discount_delta in (-0.01, 0.0, 0.01):
        for terminal_delta in (-0.005, 0.0, 0.005):
            sensitivity_discount = discount_rate + discount_delta
            sensitivity_terminal = _clamp(terminal_growth + terminal_delta, 0.0, 0.03)
            present_value = discounted_cash_flow(
                base_cash, growth, sensitivity_discount, sensitivity_terminal
            )
            equity = None if present_value is None else (
                present_value if cash_flow_is_equity else present_value - debt + cash
            )
            sensitivity.append(
                {
                    "discount_rate": sensitivity_discount,
                    "wacc": sensitivity_discount,
                    "terminal_growth": sensitivity_terminal,
                    "per_share": equity / shares if equity is not None and equity > 0 else None,
                }
            )

    ordered = sorted(value["per_share"] for value in scenario_values.values())
    point_in_time_score = safe_number(history.get("point_in_time_quality_score"))
    completeness = 1.0 - min(0.5, len(warnings) * 0.15)
    if point_in_time_score is not None:
        completeness *= point_in_time_score
    return model_result(
        "absolute",
        "partial" if warnings else "success",
        low=ordered[0],
        mid=median(ordered),
        high=ordered[-1],
        confidence=completeness,
        details={
            "formula_version": FORMULA_VERSION,
            "forecast_years": 5,
            "forecast_schedule": _forecast_schedule(growth, terminal_growth),
            "cash_flow_method": cash_flow_method,
            "cash_flow_period": cash_flow_period,
            "cash_flow_is_equity": cash_flow_is_equity,
            "normalized_cash_flow": normalized_details,
            "base_cash_flow": base_cash,
            "base_fcff": None if cash_flow_is_equity else base_cash,
            "base_fcfe": base_cash if cash_flow_is_equity else None,
            "derived_growth": derived_growth,
            "discount_rate_type": discount_rate_type,
            "discount_rate": discount_rate,
            "cost_of_equity": equity_cost,
            "wacc": wacc,
            "wacc_components": wacc_components,
            "terminal_growth": terminal_growth,
            "risk_free_rate": risk_free,
            "market_risk_premium": premium,
            "beta": beta,
            "net_debt": debt - cash,
            "scenarios": scenario_values,
            "sensitivity": sensitivity,
            "parameter_completeness": completeness,
            "point_in_time_quality": history.get("point_in_time_quality"),
        },
        warnings=warnings,
    )
