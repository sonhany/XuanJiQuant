"""Lightweight Qlib-compatible adapters.

The project keeps Tencent/Sina as the source of truth. These helpers only
reshape local bars into qlib-like research frames for offline experiments.
"""

from .panel import to_qlib_panel

__all__ = ["to_qlib_panel"]
