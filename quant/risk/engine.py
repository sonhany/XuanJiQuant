"""风控与监控引擎: 组合风险 + 系统健康

从 Redis 和已有 Layer 1-4 数据计算风险指标，不重复计算因子/策略/执行。
"""
import logging
import time
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

logger = logging.getLogger("quant.risk")


class RiskEngine:
    """风控引擎: 组合风险 + 系统健康度 + 运行监控"""

    def __init__(self, cache=None):
        self._cache = cache

    # ── 组合风险 ──────────────────────────────────────

    def portfolio_risk(
        self,
        execution_state: Optional[dict] = None,
        risk_limits: Optional[dict] = None,
    ) -> dict:
        """计算当前组合风险

        Args:
            execution_state: 执行引擎状态 (含 positions, cash, initial_capital)

        Returns:
            {var_95, max_drawdown, volatility, concentration, exposure}
        """
        if not execution_state:
            return self._empty_risk()

        positions = execution_state.get("positions", {})
        cash = execution_state.get("cash", 0)
        initial = execution_state.get("initial_capital", 1000000)
        total_equity = cash + sum(
            p["quantity"] * p.get("current_price", p["avg_price"])
            for p in positions.values()
        )

        if not positions:
            return {
                "var_95": 0, "max_drawdown_pct": 0,
                "volatility_pct": 0, "concentration_pct": 0,
                "max_position_equity_pct": 0,
                "gross_exposure_pct": 0, "net_exposure_pct": 0,
                "expected_shortfall_pct": 0,
                "risk_budget_usage_pct": 0,
                "stress_loss_pct": 0,
                "stress_scenario": "持仓价格同步下跌 5%",
                "position_count": 0, "total_equity": total_equity,
            }

        # 集中度: 最大持仓占比
        market_values = {c: p["quantity"] * p.get("current_price", p["avg_price"])
                         for c, p in positions.items()}
        total_mv = sum(market_values.values())
        max_pos = max(market_values.values()) if market_values else 0
        concentration = max_pos / total_mv * 100 if total_mv else 0
        max_position_equity = max_pos / total_equity * 100 if total_equity else 0

        # 暴露度
        gross = total_mv / total_equity * 100 if total_equity else 0
        net = (total_mv - 0) / total_equity * 100  # 无做空, net = gross

        # VaR 近似 (基于日收益率标准差, 从 kline 数据估算)
        returns = self._estimate_returns(list(positions.keys()))
        var_95 = 0
        expected_shortfall = 0
        vol = 0
        if returns:
            if len(returns) > 20:
                var_threshold = float(np.percentile(returns, 5))
                var_95 = var_threshold * 100
                tail = [value for value in returns if value <= var_threshold]
                expected_shortfall = float(np.mean(tail)) * 100 if tail else var_95
            vol = float(np.std(returns)) * np.sqrt(252) * 100 if len(returns) > 5 else 0

        limits = risk_limits or {}
        position_limit_pct = float(limits.get("max_position_pct") or 0) * 100
        gross_limit_pct = float(limits.get("max_gross_exposure_pct") or 0)
        usage = []
        if position_limit_pct > 0:
            usage.append(max_position_equity / position_limit_pct * 100)
        if gross_limit_pct > 0:
            usage.append(gross / gross_limit_pct * 100)
        risk_budget_usage = max(usage) if usage else None
        stress_loss = -(gross * 0.05)

        return {
            "var_95": round(var_95, 2),
            "max_drawdown_pct": 0,  # 需要在回测中计算
            "volatility_pct": round(vol, 2),
            "concentration_pct": round(concentration, 1),
            "max_position_equity_pct": round(max_position_equity, 1),
            "gross_exposure_pct": round(gross, 1),
            "net_exposure_pct": round(net, 1),
            "expected_shortfall_pct": round(expected_shortfall, 2),
            "risk_budget_usage_pct": round(risk_budget_usage, 1) if risk_budget_usage is not None else None,
            "stress_loss_pct": round(stress_loss, 2),
            "stress_scenario": "持仓价格同步下跌 5%",
            "position_count": len(positions),
            "total_equity": round(total_equity, 2),
        }

    def _estimate_returns(self, codes: list) -> list:
        """从 Redis kline 估算各股日收益率"""
        if not self._cache or not codes:
            return []
        all_returns = []
        for code in codes[:10]:  # 最多取 10 只
            raw = self._cache.get(f"kline:{code}:d")
            if not raw or len(raw) < 5:
                continue
            closes = [float(b.get('close') or b.get('c') or 0) for b in raw[-60:]]
            if len(closes) < 5:
                continue
            rets = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
            all_returns.extend(rets)
        return all_returns

    def _empty_risk(self) -> dict:
        return {
            "var_95": 0, "max_drawdown_pct": 0,
            "volatility_pct": 0, "concentration_pct": 0,
            "max_position_equity_pct": 0,
            "gross_exposure_pct": 0, "net_exposure_pct": 0,
            "expected_shortfall_pct": 0,
            "risk_budget_usage_pct": 0,
            "stress_loss_pct": 0,
            "stress_scenario": "持仓价格同步下跌 5%",
            "position_count": 0, "total_equity": 0,
        }

    # ── 系统运行记录 ──────────────────────────────────

    def system_log(self, lines: int = 20) -> list:
        """最近系统事件（从 Redis 读取）"""
        if not self._cache:
            return []
        raw = self._cache.get("system:events")
        if not raw:
            return []
        return raw[-lines:]
