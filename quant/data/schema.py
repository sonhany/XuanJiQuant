"""数据契约 — K线数据格式定义 + 校验

唯一权威：所有写入 Redis 的 K 线必须通过 validate_bar() 校验

字段规范（严格统一为完整英文小写）：
  date:    str   "YYYYMMDD"  (8位数字)
  open:    float > 0
  high:    float > 0  且 >= max(open, close, low)
  low:     float > 0  且 <= min(open, close, high)
  close:   float > 0
  volume:  int  >= 0  (单位: 手, A股标准)
  amount:  float >= 0  (单位: 元)
"""

from typing import Any, Dict, List, Optional


REQUIRED_FIELDS = ('date', 'open', 'high', 'low', 'close', 'volume', 'amount')


class SchemaError(ValueError):
    """数据违反 schema 时抛出"""
    pass


def _is_valid_date(s: Any) -> bool:
    if not isinstance(s, str):
        return False
    return len(s) == 8 and s.isdigit() and '19000101' <= s <= '21001231'


def validate_bar(bar: Dict[str, Any], *, strict: bool = True) -> Dict[str, Any]:
    """校验单根 K 线；strict=True 时违反契约抛 SchemaError；返回规范化后的 dict"""
    if not isinstance(bar, dict):
        raise SchemaError(f"bar must be dict, got {type(bar).__name__}")

    missing = [f for f in REQUIRED_FIELDS if f not in bar]
    if missing:
        raise SchemaError(f"missing required fields: {missing}")

    date = bar['date']
    if not _is_valid_date(date):
        raise SchemaError(f"invalid date: {date!r} (must be 'YYYYMMDD')")

    try:
        o, h, l, c = float(bar['open']), float(bar['high']), float(bar['low']), float(bar['close'])
        v = int(bar['volume'])
        a = float(bar['amount'])
    except (TypeError, ValueError) as e:
        raise SchemaError(f"numeric conversion failed: {e}")

    if min(o, h, l, c) <= 0:
        raise SchemaError(f"prices must be > 0, got o={o} h={h} l={l} c={c}")
    if h < max(o, c, l):
        raise SchemaError(f"high {h} < max(open={o}, close={c}, low={l})")
    if l > min(o, c, h):
        raise SchemaError(f"low {l} > min(open={o}, close={c}, high={h})")
    if v < 0:
        raise SchemaError(f"volume must be >= 0, got {v}")
    if a < 0:
        raise SchemaError(f"amount must be >= 0, got {a}")

    return {
        'date':   date,
        'open':   round(o, 4),
        'high':   round(h, 4),
        'low':    round(l, 4),
        'close':  round(c, 4),
        'volume': v,
        'amount': round(a, 2),
    }


def validate_series(bars: List[Dict[str, Any]], *, code: str = '?') -> List[Dict[str, Any]]:
    """校验一段连续的 K 线，返回按日期升序排序后的规范化结果

    跳变检测：连续两根 close 价格变化超过 +/- 30% 即视为脏数据，整段抛错
    （正常涨跌停 +/- 10%，留 3 倍 buffer 即 30%）
    """
    if not bars:
        return []
    out = [validate_bar(b) for b in bars]
    out.sort(key=lambda x: x['date'])
    # 去重（同日期取最后一根）
    dedup = {}
    for b in out:
        dedup[b['date']] = b
    out = list(dedup.values())
    out.sort(key=lambda x: x['date'])
    # 跳变校验
    for i in range(1, len(out)):
        prev_c = out[i-1]['close']
        cur_c = out[i]['close']
        if prev_c <= 0:
            continue
        ratio = cur_c / prev_c
        if ratio > 1.3 or ratio < 0.7:
            raise SchemaError(
                f"[{code}] price jump detected on {out[i]['date']}: "
                f"{prev_c} -> {cur_c} (ratio={ratio:.3f})"
            )
    return out


# ─── Realtime 行情 schema ──────────────────────────────────

REQUIRED_QUOTE_FIELDS = ('code', 'name', 'price', 'open', 'high', 'low', 'prev_close', 'volume', 'amount', 'timestamp')


def validate_quote(quote: Dict[str, Any]) -> Dict[str, Any]:
    """校验实时行情 quote dict"""
    if not isinstance(quote, dict):
        raise SchemaError(f"quote must be dict, got {type(quote).__name__}")
    missing = [f for f in REQUIRED_QUOTE_FIELDS if f not in quote]
    if missing:
        raise SchemaError(f"quote missing fields: {missing}")
    try:
        price = float(quote['price'])
        prev = float(quote['prev_close'])
        if price <= 0 or prev <= 0:
            raise SchemaError(f"price/prev_close must be > 0, got price={price} prev={prev}")
    except (TypeError, ValueError) as e:
        raise SchemaError(f"quote numeric conv failed: {e}")
    return quote
