"""Isolated Qlib research integration.

Modules in this package must not read or write the online trading database.
"""

from .environment import inspect_environment

__all__ = ["inspect_environment"]
