from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class FailureDetail:
    reason_code: str
    retryable: bool
    message: str
    exception_type: str

    def as_dict(self) -> dict:
        return asdict(self)


def classify_failure(exc: BaseException) -> FailureDetail:
    message = str(exc)[:500]
    lowered = message.lower()
    if "missing column" in lowered or "\u7f3a\u5c11\u5b57\u6bb5" in message:
        code, retryable = "missing_columns", False
    elif isinstance(exc, (TimeoutError, ConnectionError)) or any(
        token in lowered for token in ("timeout", "timed out", "connection")
    ):
        code, retryable = "source_network", True
    elif "price jump" in lowered:
        code, retryable = "price_jump", False
    elif "calendar" in lowered or "trade date" in lowered:
        code, retryable = "calendar_mismatch", False
    elif "empty" in lowered or "no rows" in lowered:
        code, retryable = "empty_window", False
    elif isinstance(exc, OSError):
        code, retryable = "write_failure", True
    else:
        code, retryable = "unknown", False
    return FailureDetail(code, retryable, message, type(exc).__name__)
