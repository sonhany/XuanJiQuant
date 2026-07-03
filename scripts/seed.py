"""一键数据初始化脚本 — 灌入 SQLite (腾讯日K + AKShare 财务)

用法:
  首次全量:  python scripts/seed.py
  指定股票:  python scripts/seed.py --codes 600519,000001
  少量测试:  python scripts/seed.py --limit 20
  仅刷新K线(不碰财务): python scripts/seed.py --no-financial
  财务全量:  python scripts/seed.py --klines-count 640 --all-financial

默认行为 (无参数):
  1. 用内置股票池 (沪深300+创业板+科创板精选, ~400 只)
  2. 拉每只 640 根前复权日 K (腾讯源) -> kline:<code>:d
  3. 拉每只核心财务指标 (akshare 源)  -> fin:abstract:<code>
  4. 写入股票池 -> stock:universe / stock:name:<code>

预计耗时: ~400 只 × (0.3s K线 + 4s 财务) ≈ 30 分钟 (财务是瓶颈)
仅 K 线: ~400 只 × 0.3s ≈ 2 分钟
"""
import argparse
import logging
import os
import sys
import time
from typing import List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache
from quant.data.tencent_source import fetch_klines, fetch_quotes, load_universe, normalize_code

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("seed")


def seed_klines(codes: List[str], cache, count: int = 640) -> dict:
    """阶段 1: 腾讯前复权日 K -> kline:<code>:d"""
    logger.info(f"=== 阶段1: 拉取日K线 ({len(codes)} 只 × {count} 根) ===")
    ok = err = 0
    t0 = time.time()
    for idx, code in enumerate(codes, 1):
        try:
            bars = fetch_klines(code, count=count)
            if bars:
                cache.set(f'kline:{code}:d', bars)
                ok += 1
            else:
                err += 1
        except Exception as e:
            logger.warning(f"  [{idx}/{len(codes)}] {code}: {e}")
            err += 1
            time.sleep(0.2)
            continue
        if idx % 50 == 0:
            elapsed = time.time() - t0
            logger.info(f"  [{idx}/{len(codes)}] K线 ok={ok} err={err} ({idx/elapsed:.1f}/s)")
        time.sleep(0.15)  # 限速
    elapsed = time.time() - t0
    logger.info(f"阶段1完成: ok={ok} err={err}, {elapsed:.0f}s")
    return {'ok': ok, 'err': err}


def seed_financials(codes: List[str], cache) -> dict:
    """阶段 2: AKShare 核心财务指标 -> fin:abstract:<code>"""
    try:
        from quant.data.akshare_source import seed_financials as _seed
    except ImportError as e:
        logger.warning(f"akshare 不可用，跳过财务阶段: {e}")
        return {'ok': 0, 'err': 0, 'skip': len(codes)}
    logger.info(f"=== 阶段2: 拉取财务指标 ({len(codes)} 只) ===")
    return _seed(codes, cache)


def seed_realtime_names(codes: List[str], cache) -> dict:
    """阶段 3: 拉实时行情获取股票名称 -> stock:name:<code>"""
    logger.info(f"=== 阶段3: 拉取股票名称 ({len(codes)} 只) ===")
    try:
        quotes = fetch_quotes(codes)
        ok = 0
        for code, q in quotes.items():
            name = q.get('name', '')
            if name:
                cache.set(f'stock:name:{code}', name)
                ok += 1
        logger.info(f"阶段3完成: {ok}/{len(codes)} 个名称")
        return {'ok': ok}
    except Exception as e:
        logger.warning(f"阶段3失败 (非致命): {e}")
        return {'ok': 0}


def main():
    parser = argparse.ArgumentParser(description='一键初始化数据 (腾讯日K + AKShare财务)')
    parser.add_argument('--codes', type=str, default='', help='逗号分隔代码列表，不传则用内置股票池')
    parser.add_argument('--limit', type=int, default=0, help='只处理前 N 只 (0=全部)')
    parser.add_argument('--klines-count', type=int, default=640, help='每只拉取 K 线根数 (默认 640)')
    parser.add_argument('--no-financial', action='store_true', help='跳过财务阶段 (快速)')
    parser.add_argument('--all-financial', action='store_true', help='财务阶段拉全部股票 (默认只拉前 200)')
    parser.add_argument('--no-clear', action='store_true', help='不清空已有数据 (增量)')
    args = parser.parse_args()

    # 1. 确定股票池
    if args.codes:
        codes = [normalize_code(c.strip()) for c in args.codes.split(',') if c.strip()]
        codes = [c for c in codes if len(c) == 6 and c.isdigit()]
    else:
        codes = load_universe()
    if args.limit > 0:
        codes = codes[:args.limit]
    logger.info(f"股票池: {len(codes)} 只")

    cache = create_cache()

    # 2. 清空 (除非 --no-clear)
    if not args.no_clear:
        before = cache.size()
        logger.info(f"清空已有数据 ({before} keys)...")
        cache.clear()

    # 3. 写入股票池
    cache.set('stock:universe', codes)
    logger.info(f"股票池写入: {len(codes)} -> stock:universe")

    # 4. 阶段执行
    summary = {'klines': None, 'financials': None, 'names': None}
    summary['klines'] = seed_klines(codes, cache, count=args.klines_count)

    if not args.no_financial:
        # 财务阶段默认只拉前 200 只 (耗时大)，--all-financial 拉全部
        fin_codes = codes if args.all_financial else codes[:200]
        if fin_codes:
            summary['financials'] = seed_financials(fin_codes, cache)

    summary['names'] = seed_realtime_names(codes, cache)

    # 5. 汇总
    total_keys = cache.size()
    kline_keys = len(cache.keys('kline:*:d'))
    fin_keys = len(cache.keys('fin:abstract:*'))
    logger.info("=" * 55)
    logger.info(f"初始化完成!")
    logger.info(f"  K 线: {kline_keys} 只 (kline:*:d)")
    logger.info(f"  财务: {fin_keys} 只 (fin:abstract:*)")
    logger.info(f"  总缓存键: {total_keys}")
    logger.info("=" * 55)


if __name__ == '__main__':
    main()
