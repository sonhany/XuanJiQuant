from quant.data.control_plane import get_control_plane_status


class _ControlPlaneCache:
    _conn = None
    _db_path = ""

    def get(self, key):
        if key == "stock:universe":
            return ["000001", "000002"]
        return None

    def keys(self, pattern):
        assert pattern == "kline:*:d"
        return [
            "kline:000001:d",
            "kline:000002:d",
            "kline:300029:d",
        ]

    def size(self):
        return 3


def test_control_plane_separates_universe_coverage_from_all_kline_codes():
    status = get_control_plane_status(_ControlPlaneCache())

    assert status["universe_size"] == 2
    assert status["kline_count"] == 2
    assert status["kline_total_count"] == 3
    assert status["kline_extra_count"] == 1
    assert status["kline_extra_codes"] == ["300029"]
