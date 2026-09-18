"""可插拔滑点模型 — 策略模式替代硬编码公式

设计目标:
  把 simulator.py / backtest/engine.py / portfolio_backtest.py 三处
  重复的 slippage = price * rate 公式收拢到可替换的策略对象，
  同时保持向后兼容 (默认 FixedRateSlippage 行为与旧代码完全一致)。

模型层次:
  ISlippageModel (Protocol)
    ├── FixedRateSlippage    —  固定费率 (默认, 旧行为)
    ├── ProportionalSlippage —  与订单/ADV 比例相关
    ├── VolumeSlippage       —  按成交量分档
    └── CompositeSlippage    —  多模型叠加

用法:
  # 旧代码不动 (默认 FixedRate)
  model = FixedRateSlippage(rate=0.0001)

  # 新代码按需选模型
  model = ProportionalSlippage(base_rate=0.0001, participation_rate=0.05)

  # 统一调用
  fill_price, slippage_cost = model.compute(
      price=10.0, direction="buy", quantity=1000, adv=50000
  )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@runtime_checkable
class ISlippageModel(Protocol):
    """滑点模型协议 — 所有实现必须满足。"""

    @property
    def name(self) -> str: ...

    def compute(
        self,
        *,
        price: float,
        direction: str,
        quantity: int = 0,
        adv: int = 0,
        **kwargs: object,
    ) -> tuple[float, float]:
        """计算成交价和滑点成本。

        Args:
            price: 参考价格 (通常为次日开盘价或实时价)
            direction: 'buy' 或 'sell'
            quantity: 委托数量 (股)
            adv: 20 日平均成交量 (股), Volume/Proportional 模型需要
            **kwargs: 扩展参数 (各模型可自定义)

        Returns:
            (fill_price, slippage_cost)
            fill_price: 含滑点的成交价
            slippage_cost: 滑点总额 (|fill_price - price| * quantity)
        """
        ...

    def to_dict(self) -> dict: ...


# ── 固定费率 (默认, 与旧代码完全一致) ────────────────────────

@dataclass(frozen=True, slots=True)
class FixedRateSlippage:
    """固定费率滑点: fill = price * (1 ± rate)

    与 simulator.py line 65 / engine.py line 630 / portfolio_backtest.py line 139
    完全等价。
    """
    rate: float = 0.0001
    version: str = "fixed-rate-v1"

    @property
    def name(self) -> str:
        return "fixed_rate"

    def compute(
        self,
        *,
        price: float,
        direction: str,
        quantity: int = 0,
        adv: int = 0,
        **kwargs: object,
    ) -> tuple[float, float]:
        slippage_per_share = price * self.rate
        if direction == "buy":
            fill_price = price + slippage_per_share
        else:
            fill_price = price - slippage_per_share
        slippage_cost = slippage_per_share * max(0, int(quantity))
        return round(fill_price, 6), round(slippage_cost, 6)

    def to_dict(self) -> dict:
        return {"type": "fixed_rate", "rate": self.rate, "version": self.version}


# ── 成交量比例滑点 ──────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class ProportionalSlippage:
    """与订单占 ADV 比例相关的滑点。

    公式: impact = base_rate + k * (quantity / adv)
    反映大单对市场的冲击——订单越大、ADV 越小，滑点越高。
    """
    base_rate: float = 0.0001
    k: float = 0.1  # 冲击系数
    version: str = "proportional-v1"

    @property
    def name(self) -> str:
        return "proportional"

    def compute(
        self,
        *,
        price: float,
        direction: str,
        quantity: int = 0,
        adv: int = 0,
        **kwargs: object,
    ) -> tuple[float, float]:
        participation = float(quantity) / float(adv) if adv > 0 else 0.0
        effective_rate = self.base_rate + self.k * participation
        effective_rate = min(effective_rate, 0.05)  # 上限 5%
        slippage_per_share = price * effective_rate
        if direction == "buy":
            fill_price = price + slippage_per_share
        else:
            fill_price = price - slippage_per_share
        slippage_cost = slippage_per_share * max(0, int(quantity))
        return round(fill_price, 6), round(slippage_cost, 6)

    def to_dict(self) -> dict:
        return {"type": "proportional", "base_rate": self.base_rate, "k": self.k, "version": self.version}


# ── 成交量分档滑点 ──────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class VolumeSlippage:
    """按订单占 ADV 比例分档的滑点。

    参考 A 股微观结构实证研究:
    - < 1% ADV:  1 bps
    - 1-5% ADV:  3 bps
    - 5-10% ADV: 8 bps
    - 10-20% ADV: 15 bps
    - > 20% ADV: 25 bps
    """
    tiers: tuple[tuple[float, float], ...] = (
        (0.01, 0.0001),   # < 1% ADV → 1 bps
        (0.05, 0.0003),   # 1-5% ADV → 3 bps
        (0.10, 0.0008),   # 5-10% ADV → 8 bps
        (0.20, 0.0015),   # 10-20% ADV → 15 bps
        (1.00, 0.0025),   # > 20% ADV → 25 bps
    )
    version: str = "volume-tier-v1"

    @property
    def name(self) -> str:
        return "volume_tier"

    def _rate_for_participation(self, participation: float) -> float:
        for threshold, rate in self.tiers:
            if participation <= threshold:
                return rate
        return self.tiers[-1][1]

    def compute(
        self,
        *,
        price: float,
        direction: str,
        quantity: int = 0,
        adv: int = 0,
        **kwargs: object,
    ) -> tuple[float, float]:
        participation = float(quantity) / float(adv) if adv > 0 else 0.0
        rate = self._rate_for_participation(participation)
        slippage_per_share = price * rate
        if direction == "buy":
            fill_price = price + slippage_per_share
        else:
            fill_price = price - slippage_per_share
        slippage_cost = slippage_per_share * max(0, int(quantity))
        return round(fill_price, 6), round(slippage_cost, 6)

    def to_dict(self) -> dict:
        return {"type": "volume_tier", "tiers": self.tiers, "version": self.version}


# ── 复合模型 (叠加) ─────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class CompositeSlippage:
    """多模型叠加: total_slippage = sum(model各自的 slippage)。

    典型用法: 固定费率 + 市场冲击 = CompositeSlippage([
        FixedRateSlippage(0.0001),
        ProportionalSlippage(k=0.05),
    ])
    """
    models: tuple[ISlippageModel, ...] = ()
    version: str = "composite-v1"

    @property
    def name(self) -> str:
        names = "+".join(m.name for m in self.models)
        return f"composite({names})"

    def compute(
        self,
        *,
        price: float,
        direction: str,
        quantity: int = 0,
        adv: int = 0,
        **kwargs: object,
    ) -> tuple[float, float]:
        total_slippage_cost = 0.0
        current_price = price
        for model in self.models:
            fill_p, cost = model.compute(
                price=current_price, direction=direction,
                quantity=quantity, adv=adv, **kwargs,
            )
            total_slippage_cost += cost
            current_price = fill_p
        return round(current_price, 6), round(total_slippage_cost, 6)

    def to_dict(self) -> dict:
        return {
            "type": "composite",
            "models": [m.to_dict() for m in self.models],
            "version": self.version,
        }


# ── 工厂 ────────────────────────────────────────────────────

def create_slippage_model(config: dict | None = None) -> ISlippageModel:
    """从配置 dict 创建滑点模型 (JSON config 兼容)。

    config 示例:
        {"type": "fixed_rate", "rate": 0.0001}
        {"type": "proportional", "base_rate": 0.0001, "k": 0.1}
        {"type": "volume_tier"}
        {"type": "composite", "models": [
            {"type": "fixed_rate", "rate": 0.0001},
            {"type": "proportional", "k": 0.05},
        ]}
        None 或 {} → FixedRateSlippage(rate=0.0001) (向后兼容)
    """
    if not config:
        return FixedRateSlippage()
    model_type = str(config.get("type", "fixed_rate"))
    if model_type == "fixed_rate":
        return FixedRateSlippage(rate=float(config.get("rate", 0.0001)))
    if model_type == "proportional":
        return ProportionalSlippage(
            base_rate=float(config.get("base_rate", 0.0001)),
            k=float(config.get("k", 0.1)),
        )
    if model_type == "volume_tier":
        return VolumeSlippage()
    if model_type == "composite":
        sub_models = [
            create_slippage_model(m) for m in config.get("models", [])
        ]
        return CompositeSlippage(models=tuple(sub_models))
    return FixedRateSlippage()
