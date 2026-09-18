"""Deterministic, simulation-only F5 paper execution.

This bounded context is deliberately independent from the retired Agent and
legacy execution engines.  Importing it never grants execution authority.
"""

from .contracts import InvalidStateTransition, stable_id
from .ledger import PaperLedger
from .slippage import (
    ISlippageModel,
    FixedRateSlippage,
    ProportionalSlippage,
    VolumeSlippage,
    CompositeSlippage,
    create_slippage_model,
)

__all__ = [
    "InvalidStateTransition", "PaperLedger", "stable_id",
    "ISlippageModel", "FixedRateSlippage", "ProportionalSlippage",
    "VolumeSlippage", "CompositeSlippage", "create_slippage_model",
]
