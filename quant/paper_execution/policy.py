"""Versioned, immutable policy for deterministic daily simulation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .contracts import stable_id


@dataclass(frozen=True, slots=True)
class ExperimentalPaperPolicy:
    """Explicit permission for research-rejected, simulation-only cycles."""

    enabled: bool = False
    policy_version: str = "f5-experimental-paper-v1"
    allowed_f4_statuses: tuple[str, ...] = ("f4_rejected",)
    require_zero_constraint_violations: bool = True
    require_zero_future_data_violations: bool = True

    def __post_init__(self) -> None:
        if not str(self.policy_version).strip():
            raise ValueError("experimental_policy_version_missing")
        if tuple(self.allowed_f4_statuses) != ("f4_rejected",):
            raise ValueError("experimental_f4_status_forbidden")


@dataclass(frozen=True, slots=True)
class PaperExecutionPolicy:
    version: str = "f5-paper-policy-v2-staged-rebalance"
    enabled: bool = False
    kill_switch: bool = False
    initial_capital: float = 1_000_000.0
    commission_rate: float = 0.0003
    minimum_commission: float = 5.0
    stamp_tax_rate: float = 0.0005
    transfer_fee_rate: float = 0.00001
    slippage_rate: float = 0.0001
    participation_cap: float = 0.10
    lot_size: int = 100
    execution_mode: str = "paper_daily"
    paper_execution_authority: bool = True
    live_execution_authority: bool = False
    experimental_paper: ExperimentalPaperPolicy = field(
        default_factory=ExperimentalPaperPolicy
    )

    def __post_init__(self) -> None:
        if self.live_execution_authority is not False:
            raise ValueError("live_execution_authority_forbidden")

    @property
    def policy_hash(self) -> str:
        return stable_id("paper_policy", asdict(self)).split("_", 2)[-1]

    def to_dict(self) -> dict:
        return {**asdict(self), "policy_hash": self.policy_hash}
