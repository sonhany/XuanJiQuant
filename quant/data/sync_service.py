"""数据同步服务 — 盘中实时行情 + 收盘后当日K线入库

数据源: 新浪财经 hq.sinajs.cn (免费、GBK编码、支持任意股票实时报价)

设计原则 (Ultra Think 修订版):
  - 盘中实时报价写到独立 key `stock:realtime:<code>` (TTL 120s)
  - 盘中当日K线快照写到独立 key `kline:<code>:intraday` (仅展示用，不污染历史)
  - 只有收盘后 (15:00 后) 才把当日完整K线合并进 `kline:<code>:d`
  - volume 单位统一为"股" (新浪原生单位)，与历史数据一致性由 factor engine 的 amount/close 兜底
  - 所有合并走 schema 校验

Key 规范:
  kline:<code>:d           → 日K历史 (只追加已收盘的完整bar)
  kline:<code>:intraday    → 当日盘中快照 (实时覆盖，仅展示)
  stock:realtime:<code>    → 实时报价 dict (TTL 120s)
  stock:name:<code>        → 股票名称
  sync:trading             → {is_trading, is_afterhours, session}

启动: python -m quant.data.sync_service
"""
import json
import logging
import os
import re
import sys
import time
import urllib.request
from datetime import datetime
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from quant.data.cache import create_cache
from quant.data.schema import validate_bar, validate_series, SchemaError

logger = logging.getLogger("sync_service")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

SINA_URL = "http://hq.sinajs.cn/list={codes}"


def is_trading_time(now: Optional[datetime] = None) -> dict:
    """判断当前是否为A股交易时段。"""
    now = now or datetime.now()
    wd = now.weekday()
    if wd >= 5:
        return {"is_trading": False, "is_afterhours": True, "session": "weekend"}
    hm = now.hour * 100 + now.minute
    if 915 <= hm < 930:
        return {"is_trading": False, "is_afterhours": False, "session": "pre_market"}
    if 930 <= hm < 1130 or 1300 <= hm < 1500:
        return {"is_trading": True, "is_afterhours": False, "session": "market"}
    if 1500 <= hm < 1530:
        return {"is_trading": True, "is_afterhours": False, "session": "closing"}
    return {"is_trading": False, "is_afterhours": True, "session": "closed"}


def fetch_sina_quotes(codes: List[str]) -> Dict[str, dict]:
    """从新浪拉实时报价 (支持批量)。
    返回 {code: {name, open, close(昨收), price, high, low, volume(股), amount(元), date, time}}
    """
    if not codes:
        return {}
    sina_codes = []
    code_map = {}
    for c in codes:
        c6 = str(c).replace('.SZ', '').replace('.SH', '').replace('.BJ', '').replace('sz', '').replace('sh', '').zfill(6)
        if c6.startswith('6'):
            sc = f'sh{c6}'
        elif c6.startswith(('0', '3')):
            sc = f'sz{c6}'
        elif c6.startswith(('8', '4')):
            sc = f'bj{c6}'
        else:
            sc = f'sz{c6}'
        sina_codes.append(sc)
        code_map[sc] = c6

    out: Dict[str, dict] = {}
    for i in range(0, len(sina_codes), 50):
        batch = sina_codes[i:i+50]
        url = SINA_URL.format(codes=','.join(batch))
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0',
                'Referer': 'http://finance.sina.com.cn',
            })
            with urllib.request.urlopen(req, timeout=8) as resp:
                raw = resp.read().decode('gbk', errors='replace')
            for line in raw.split('\n'):
                m = re.search(r'hq_str_([a-z]+\d+)="([^"]*)"', line)
                if not m:
                    continue
                sc = m.group(1)
                fields = m.group(2).split(',')
                if len(fields) < 10:
                    continue
                orig = code_map.get(sc, sc)
                price = float(fields[3]) if fields[3] else 0
                prev_close = float(fields[2]) if fields[2] else 0
                if price == 0 and prev_close > 0:
                    price = prev_close
                out[orig] = {
                    'name': fields[0],
                    'open': float(fields[1]) if fields[1] else 0,
                    'close': prev_close,
                    'price': price,
                    'high': float(fields[4]) if fields[4] else 0,
                    'low': float(fields[5]) if fields[5] else 0,
                    'volume': int(float(fields[8])) if fields[8] else 0,
                    'amount': float(fields[9]) if fields[9] else 0,
                    'date': fields[30] if len(fields) > 30 else '',
                    'time': fields[31] if len(fields) > 31 else '',
                }
        except Exception as e:
            logger.warning(f"sina fetch batch {i//50} failed: {e}")
    return out


class SyncService:
    def __init__(self, watch_codes: Optional[List[str]] = None):
        self.cache = create_cache()
        self._running = False
        self.watch_codes = watch_codes
        # 已收盘合并的日期 (避免重复合并)
        self._merged_dates: set = set()

    def _load_watch_codes(self) -> List[str]:
        if self.watch_codes:
            return self.watch_codes
        cached = self.cache.get('stock:universe')
        if cached and isinstance(cached, list) and len(cached) > 0:
            return [str(c) for c in cached][:200]
        return ['000001','600036','601318','000858','600519','600276','000725','601398',
                '000333','600030','601166','002594','000651','600887','601012']

    # ─── 实时报价 → 独立缓存 (不碰历史K线) ──────────────

    def sync_realtime(self, quotes: Dict[str, dict]):
        ok = 0
        for code, q in quotes.items():
            try:
                self.cache.set(f'stock:realtime:{code}', q, ttl=120)
                if q.get('name'):
                    self.cache.set(f'stock:name:{code}', q['name'])
                ok += 1
            except Exception:
                continue
        self.cache.set('sync:trading', is_trading_time(), ttl=300)
        return ok

    # ─── 盘中快照 → 独立 intraday key (仅展示) ──────────

    def sync_intraday_snapshot(self, quotes: Dict[str, dict]):
        """盘中把当日OHLCV写到 kline:<code>:intraday，实时覆盖。
        绝不写入 kline:<code>:d (历史)。只有收盘后才合并。
        """
        today = datetime.now().strftime('%Y%m%d')
        ok = 0
        for code, q in quotes.items():
            if q['price'] <= 0:
                continue
            bar = {
                'date': today,
                'open': q['open'], 'high': q['high'], 'low': q['low'],
                'close': q['price'], 'volume': q['volume'], 'amount': q['amount'],
                'time': q.get('time', ''),
            }
            # 写独立 intraday key，与历史完全隔离
            self.cache.set(f'kline:{code}:intraday', bar, ttl=14400)
            ok += 1
        return ok

    # ─── 收盘后合并: intraday → 历史 kline:d ──────────────

    def merge_closed_bars(self, quotes: Dict[str, dict]):
        """收盘后 (15:00 后) 把当日完整K线合并进 kline:<code>:d。
        会做 schema 校验 + 去重。每天每只只合并一次。
        """
        today = datetime.now().strftime('%Y%m%d')
        if today in self._merged_dates:
            return 0
        ok = 0
        for code, q in quotes.items():
            if q['price'] <= 0:
                continue
            key = f'kline:{code}:d'
            existing = self.cache.get(key) or []
            today_bar = {
                'date': today,
                'open': q['open'], 'high': q['high'], 'low': q['low'],
                'close': q['price'], 'volume': q['volume'], 'amount': q['amount'],
            }
            # 如果今天已存在 (不应该，但防御性)，替换；否则追加
            existing_dates = {b.get('date') for b in existing}
            if today in existing_dates:
                existing = [today_bar if b.get('date') == today else b for b in existing]
            else:
                existing.append(today_bar)
                existing = existing[-300:]
            # schema 校验
            try:
                existing = validate_series(existing, code=code)
            except SchemaError as e:
                logger.warning(f"[{code}] merge validation failed, skip: {e}")
                continue
            self.cache.set(key, existing)
            ok += 1
        if ok:
            self._merged_dates.add(today)
            logger.info(f"收盘合并: {ok} stocks merged into kline:d for {today}")
        return ok

    # ─── 主循环 ──────────────────────────────────────────────

    def run(self):
        self._running = True
        codes = self._load_watch_codes()
        logger.info(f"SyncService started, watching {len(codes)} codes")

        cycle = 0
        while self._running:
            try:
                trading = is_trading_time()
                self.cache.set('sync:trading', trading, ttl=300)

                quotes = fetch_sina_quotes(codes)
                rt_ok = self.sync_realtime(quotes)
                logger.info(f"[{trading['session']}] realtime {rt_ok}/{len(codes)} | "
                            f"{datetime.now().strftime('%H:%M:%S')}")

                if trading['is_trading']:
                    # 盘中: 只写 intraday 快照 (隔离)
                    self.sync_intraday_snapshot(quotes)
                else:
                    # 盘后/收盘: 合并当日完整K线进历史 (每天一次)
                    # 只在 15:00 后且当天还没合并过时执行
                    if datetime.now().hour >= 15 and trading['session'] != 'weekend':
                        self.merge_closed_bars(quotes)

                cycle += 1
                time.sleep(10 if trading['is_trading'] else 60)
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"main loop error: {e}", exc_info=True)
                time.sleep(30)

    def stop(self):
        self._running = False


if __name__ == '__main__':
    svc = SyncService()
    try:
        svc.run()
    except KeyboardInterrupt:
        svc.stop()
        logger.info("SyncService stopped")
