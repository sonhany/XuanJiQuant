from quant.qlib.failures import classify_failure


def test_missing_columns_is_not_retryable():
    result = classify_failure(ValueError("missing columns: volume, amount"))

    assert (result.reason_code, result.retryable) == ("missing_columns", False)


def test_timeout_is_retryable():
    result = classify_failure(TimeoutError("source timed out"))

    assert (result.reason_code, result.retryable) == ("source_network", True)


def test_price_jump_is_not_retryable():
    result = classify_failure(RuntimeError("price jump exceeds tolerance"))

    assert (result.reason_code, result.retryable) == ("price_jump", False)
