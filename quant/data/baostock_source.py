"""Baostock 数据源 — 全A股日K线 (含成交额)，反爬宽松

定位: 批量下载的主力 K 线源。腾讯/东财批量请求易触发限流(HTTP 501)，
baostock 作为证券类开源数据库，反爬宽松、数据完整(含 amount 字段)、稳定。

接口:
  fetch_klines(code, count)   — 单股日K (前复权)
  fetch_klines_range(code, start, end) — 指定日期范围

数据格式 (与 tencent_source 对齐):
  list[dict] 每根 {date, open, high, low, close, volume, amount}
  date: 'YYYYMMDD', volume: 手, amount: 元

注意:
  - baostock 需要先 login()，本模块自动管理(单例)
  - 代码格式: 6位 -> sh.XXXXXX / sz.XXXXXX / bj.XXXXXX
  - adjustflag: '1'后复权 '2'前复权 '3'不复权 (默认前复权，与腾讯一致)
"""
import logging
import threading
from typing import List, Optional

from quant.data.schema import validate_bar, validate_series, SchemaError

logger = logging.getLogger("baostock_source")

_login_lock = threading.Lock()
_logged_in = False


def _ensure_login():
    """确保 baostock 已登录 (线程安全单例)"""
    global _logged_in
    with _login_lock:
        if not _logged_in:
            import baostock as bs
            lg = bs.login()
            if lg.error_code != '0':
                raise SchemaError(f"baostock login failed: {lg.error_msg}")
            _logged_in = True
            logger.info("baostock logged in")


def _bs_symbol(code: str) -> str:
    """6位代码 -> baostock 格式 sh.XXXXXX / sz.XXXXXX / bj.XXXXXX"""
    c = code.split('.')[0]
    if c.startswith('6') or c.startswith('9'):
        return f'sh.{c}'
    if c.startswith('0') or c.startswith('3') or c.startswith('2'):
        return f'sz.{c}'
    if c.startswith('8') or c.startswith('4'):
        return f'bj.{c}'
    return f'sh.{c}'


def fetch_klines(code: str, count: int = 250, adjustflag: str = '2') -> List[dict]:
    """拉取单只股票最近 count 根日K (前复权)

    Args:
        code: 6位股票代码
        count: K线根数 (默认250，约1年)
        adjustflag: '1'后复权 '2'前复权 '3'不复权

    Returns: 符合 schema 的 list[dict]，失败返回 []
    """
    _ensure_login()
    import baostock as bs

    sym = _bs_symbol(code)
    # baostock 没有直接"最近N根"，用日期范围近似: 取近 count*2 天确保够
    from datetime import datetime, timedelta
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=count * 2)).strftime('%Y-%m-%d')

    rs = bs.query_history_k_data_plus(
        sym,
        'date,open,high,low,close,volume,amount',
        start_date=start, end_date=end,
        frequency='d', adjustflag=adjustflag,
    )
    if rs.error_code != '0':
        logger.debug(f"[{code}] baostock query failed: {rs.error_msg}")
        return []

    bars = []
    while rs.next():
        row = rs.get_row_data()
        try:
            d = row[0].replace('-', '')  # YYYY-MM-DD -> YYYYMMDD
            bar = {
                'date':   d,
                'open':   float(row[1]),
                'high':   float(row[2]),
                'low':    float(row[3]),
                'close':  float(row[4]),
                'volume': int(float(row[5])) if row[5] else 0,
                'amount': float(row[6]) if row[6] else 0.0,
            }
            bars.append(validate_bar(bar))
        except (ValueError, SchemaError):
            continue

    if not bars:
        return []
    # 取最近 count 根
    bars = bars[-count:] if len(bars) > count else bars
    try:
        return validate_series(bars, code=code)
    except SchemaError as e:
        # 复权异常/价格跳变: 降级返回原始数据(不校验)，避免整只股票丢失
        logger.warning(f"[{code}] schema校验失败({str(e)[:60]}), 返回未校验数据")
        return bars


def fetch_klines_range(code: str, start: str, end: str, adjustflag: str = '2') -> List[dict]:
    """拉取指定日期范围的日K

    Args:
        start/end: 'YYYYMMDD' 或 'YYYY-MM-DD'
    """
    _ensure_login()
    import baostock as bs

    sym = _bs_symbol(code)
    s = start.replace('-', '')
    e = end.replace('-', '')
    s = f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    e = f"{e[:4]}-{e[4:6]}-{e[6:8]}"

    rs = bs.query_history_k_data_plus(
        sym, 'date,open,high,low,close,volume,amount',
        start_date=s, end_date=e, frequency='d', adjustflag=adjustflag,
    )
    if rs.error_code != '0':
        return []

    bars = []
    while rs.next():
        row = rs.get_row_data()
        try:
            bar = {
                'date':   row[0].replace('-', ''),
                'open':   float(row[1]),
                'high':   float(row[2]),
                'low':    float(row[3]),
                'close':  float(row[4]),
                'volume': int(float(row[5])) if row[5] else 0,
                'amount': float(row[6]) if row[6] else 0.0,
            }
            bars.append(validate_bar(bar))
        except (ValueError, SchemaError):
            continue
    return validate_series(bars, code=code)


def logout():
    """退出登录 (程序结束时调用)"""
    global _logged_in
    if _logged_in:
        import baostock as bs
        bs.logout()
        _logged_in = False
