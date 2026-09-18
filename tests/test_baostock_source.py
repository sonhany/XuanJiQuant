from __future__ import annotations

import sys
import types


def test_ensure_login_applies_a_real_socket_timeout(monkeypatch):
    from quant.data import baostock_source

    class FakeSocket:
        def __init__(self):
            self.timeout = None

        def settimeout(self, value):
            self.timeout = value

    socket = FakeSocket()
    context = types.ModuleType("baostock.common.context")
    context.default_socket = socket
    baostock = types.ModuleType("baostock")
    baostock.login = lambda: types.SimpleNamespace(error_code="0", error_msg="")

    monkeypatch.setitem(sys.modules, "baostock", baostock)
    monkeypatch.setitem(sys.modules, "baostock.common.context", context)
    monkeypatch.setenv("BAOSTOCK_SOCKET_TIMEOUT_SECONDS", "7")
    monkeypatch.setattr(baostock_source, "_logged_in", False)

    baostock_source._ensure_login()

    assert socket.timeout == 7.0


def test_range_query_failure_invalidates_baostock_session(monkeypatch):
    from quant.data import baostock_source

    baostock = types.ModuleType("baostock")
    baostock.query_history_k_data_plus = lambda *args, **kwargs: (_ for _ in ()).throw(
        TimeoutError("socket stalled")
    )
    monkeypatch.setitem(sys.modules, "baostock", baostock)
    monkeypatch.setattr(baostock_source, "_ensure_login", lambda: None)
    monkeypatch.setattr(baostock_source, "_logged_in", True)

    rows = baostock_source.fetch_klines_range(
        "600000", "2020-08-01", "2026-08-14", allow_price_jumps=True
    )

    assert rows == []
    assert baostock_source._logged_in is False
