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

    def portfolio_risk(self, execution_state: Optional[dict] = None) -> dict:
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
                "gross_exposure_pct": 0, "net_exposure_pct": 0,
                "position_count": 0, "total_equity": total_equity,
            }

        # 集中度: 最大持仓占比
        market_values = {c: p["quantity"] * p.get("current_price", p["avg_price"])
                         for c, p in positions.items()}
        total_mv = sum(market_values.values())
        max_pos = max(market_values.values()) if market_values else 0
        concentration = max_pos / total_mv * 100 if total_mv else 0

        # 暴露度
        gross = total_mv / total_equity * 100 if total_equity else 0
        net = (total_mv - 0) / total_equity * 100  # 无做空, net = gross

        # VaR 近似 (基于日收益率标准差, 从 kline 数据估算)
        returns = self._estimate_returns(list(positions.keys()))
        var_95 = 0
        vol = 0
        if returns:
            var_95 = float(np.percentile(returns, 5)) if len(returns) > 20 else 0
            vol = float(np.std(returns)) * np.sqrt(252) * 100 if len(returns) > 5 else 0

        return {
            "var_95": round(var_95, 2),
            "max_drawdown_pct": 0,  # 需要在回测中计算
            "volatility_pct": round(vol, 2),
            "concentration_pct": round(concentration, 1),
            "gross_exposure_pct": round(gross, 1),
            "net_exposure_pct": round(net, 1),
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
            "gross_exposure_pct": 0, "net_exposure_pct": 0,
            "position_count": 0, "total_equity": 0,
        }

    # ── 系统健康 ──────────────────────────────────────

    def system_health(self) -> dict:
        """监控各层健康状态"""
        health = {
            "data_layer": self._check_data_layer(),
            "factor_layer": self._check_factor_layer(),
            "strategy_layer": {"status": "ok", "note": "策略结果在运行时产生"},
            "execution_layer": self._check_execution_layer(),
            "system": self._check_system(),
        }
        all_ok = all(v.get("status") == "ok" for v in health.values())
        health["overall"] = "ok" if all_ok else "warning"
        return health

    def _check_data_layer(self) -> dict:
        if not self._cache:
            return {"status": "error", "note": "缓存不可用"}
        try:
            keys = self._cache.keys("kline:*:d")
            stock_count = len(keys)
            # 最近一条数据的日期
            latest = ""
            sample = keys[:20]
            for k in sample:
                raw = self._cache.get(k)
                if raw and len(raw) > 0:
                    d = str(raw[-1].get('d') or raw[-1].get('date') or '')
                    if d > latest:
                        latest = d
            return {
                "status": "ok",
                "stock_count": stock_count,
                "latest_date": latest[:8] if latest else "N/A",
                "note": f"{stock_count} 只股票 K-line",
            }
        except Exception as e:
            return {"status": "error", "note": str(e)[:100]}

    def _check_factor_layer(self) -> dict:
        if not self._cache:
            return {"status": "warning", "note": "无缓存"}
        try:
            keys = self._cache.keys("factor:*")
            return {
                "status": "ok",
                "cached_factor_count": len(keys),
                "note": f"{len(keys)} 只股票因子已缓存",
            }
        except Exception as e:
            return {"status": "warning", "note": str(e)[:100]}

    def _check_execution_layer(self) -> dict:
        if not self._cache:
            return {"status": "warning", "note": "无缓存"}
        state = self._cache.get("execution:state")
        if not state:
            return {"status": "ok", "note": "未启动交易"}
        pos_count = len(state.get("positions", {}))
        order_count = len(state.get("orders", []))
        return {
            "status": "ok",
            "position_count": pos_count,
            "order_count": order_count,
            "note": f"{pos_count} 持仓, {order_count} 订单",
        }

    def _check_system(self) -> dict:
        try:
            dbsize = 0
            if self._cache:
                try:
                    dbsize = self._cache.size()
                except Exception:
                    pass
            return {
                "status": "ok",
                "dbsize": dbsize,
                "uptime": "服务运行中",
            }
        except Exception as e:
            return {"status": "error", "note": str(e)[:100]}

    # ── 系统运行记录 ──────────────────────────────────

    def system_log(self, lines: int = 20) -> list:
        """最近系统事件（从 Redis 读取）"""
        if not self._cache:
            return []
        raw = self._cache.get("system:events")
        if not raw:
            return []
        return raw[-lines:]
