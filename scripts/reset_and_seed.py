"""一次性脚本: 清空数据库 + 从腾讯财经重灌全量 K 线

用法:
  python scripts/reset_and_seed.py [--codes 600519,000001] [--count 250]

如果不传 --codes，使用 tencent_source.load_universe() 内置种子。
--count 控制每只股票拉多少根日 K（默认 640 根）。
"""
import argparse
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache
from quant.data.tencent_source import fetch_klines, load_universe, normalize_code

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger("reset_and_seed")


def main():
    parser = argparse.ArgumentParser(description='清空数据库 + 重灌 K 线')
    parser.add_argument('--codes', type=str, default='',
                        help='逗号分隔的代码列表（无视交易所后缀）')
    parser.add_argument('--count', type=int, default=640,
                        help='每只股票拉取 K 线根数 (默认 640)')
    args = parser.parse_args()

    if args.codes:
        codes = [normalize_code(c.strip()) for c in args.codes.split(',') if c.strip()]
        codes = [c for c in codes if len(c) == 6 and c.isdigit()]
    else:
        codes = load_universe()
        logger.info(f"Loaded {len(codes)} codes from built-in universe")

    # 1. 清空
    cache = create_cache()
    logger.info(f"Clearing all {cache.size()} keys...")
    cache.clear()
    logger.info("Cache cleared.")

    # 2. 写入股票池
    cache.set('stock:universe', codes)
    logger.info(f"Universe written: {len(codes)} codes -> stock:universe")

    # 3. 逐只拉 K 线
    ok, err = 0, 0
    start_time = time.time()
    for idx, code in enumerate(codes, 1):
        try:
            bars = fetch_klines(code, count=args.count)
            if bars:
                cache.set(f'kline:{code}:d', bars)
                ok += 1
            else:
                logger.info(f"  [{idx}/{len(codes)}] {code}: -> 0 bars (skipped)")
                err += 1
        except Exception as e:
            logger.warning(f"  [{idx}/{len(codes)}] {code}: -> FAILED: {e}")
            err += 1
            time.sleep(0.2)
            continue

        if idx % 50 == 0:
            elapsed = time.time() - start_time
            rate = idx / elapsed if elapsed > 0 else 0
            logger.info(f"  [{idx}/{len(codes)}] progress: ok={ok} err={err} rate={rate:.1f}/s")

        time.sleep(0.15)  # 限速

    elapsed = time.time() - start_time
    all_keys = len(cache.keys())

    logger.info("=" * 50)
    logger.info(f"Done: {ok}/{len(codes)} seeded, {err} empty/failed")
    logger.info(f"Redis keys after seed: {all_keys}")
    logger.info(f"Time: {elapsed:.1f}s ({len(codes)/elapsed:.1f}/s)")


if __name__ == '__main__':
    main()