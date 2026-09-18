import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def test_trade_universe_excludes_920_codes():
    from quant.data.universe import filter_trade_universe_codes, is_supported_trade_universe_code

    assert is_supported_trade_universe_code("600519") is True
    assert is_supported_trade_universe_code("000001") is True
    assert is_supported_trade_universe_code("688001") is True
    assert is_supported_trade_universe_code("920001") is False
    assert filter_trade_universe_codes(["600519", "920001", "000001", "920999"]) == ["600519", "000001"]


if __name__ == "__main__":
    test_trade_universe_excludes_920_codes()
    print("universe_filter_contract_tests: OK")
