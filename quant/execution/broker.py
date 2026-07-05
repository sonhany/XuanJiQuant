"""Broker adapter boundary.

Live trading is intentionally disabled by default. The first live phase should
only support read-only account sync, shadow signals, and manual approval.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class BrokerAdapterError(RuntimeError):
    pass


class BrokerAdapter(ABC):
    name = "base"

    @abstractmethod
    def account_snapshot(self) -> dict:
        raise NotImplementedError

    @abstractmethod
    def submit_order(self, order: dict) -> dict:
        raise NotImplementedError

    def shadow_signal(self, signal: dict) -> dict:
        return {"success": True, "mode": "shadow", "signal": signal}


class PaperBrokerAdapter(BrokerAdapter):
    name = "paper"

    def __init__(self, status_fn, order_fn):
        self._status_fn = status_fn
        self._order_fn = order_fn

    def account_snapshot(self) -> dict:
        return self._status_fn()

    def submit_order(self, order: dict) -> dict:
        return self._order_fn(order)


class LiveBrokerAdapter(BrokerAdapter):
    """Guarded live adapter placeholder.

    This class documents the allowed first live phase. Any automatic order
    submission is rejected until a concrete broker integration implements
    manual approval, kill switch, capital caps, drawdown fuse, and reconciliation.
    """

    name = "live_guarded"

    def __init__(self, read_only_account_fn=None):
        self._read_only_account_fn = read_only_account_fn

    def account_snapshot(self) -> dict:
        if not self._read_only_account_fn:
            return {"success": False, "mode": "read_only", "error": "未配置只读账户同步"}
        return self._read_only_account_fn()

    def submit_order(self, order: dict) -> dict:
        return {
            "success": False,
            "mode": "manual_approve_required",
            "error": "实盘自动下单默认禁用: 仅允许只读账户同步、shadow signal、人工批准订单",
            "order": order,
        }

