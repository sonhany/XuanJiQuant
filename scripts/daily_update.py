"""每日增量更新 — 用 baostock 增量刷新 K线 + 财务

设计:
  - K线增量: 只拉每只股票缓存里最后日期之后的新K线 (不重复拉全年)
  - 财务增量: 默认跳过 (季度更新)，--financial 时全量刷新
  - 股票池: 自动同步最新全A股清单 (新股上市/退市)
  - 适合收盘后运行 (15:30 后)，可加到 Windows 任务计划

用法:
  python scripts/daily_update.py              # 每日K线增量 (默认，约30分钟)
  python scripts/daily_update.py --financial  # 含财务刷新 (约5小时)
  python scripts/daily_update.py --limit 100  # 测试用，只更新100只

定时 (Windows 任务计划，每个交易日17:00运行):
  schtasks /create /tn "AlphaCouncil每日更新" /tr "python C:\\...\\scripts\\daily_update.py" /sc daily /st 17:00
"""
import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from typing import List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache
from quant.data.baostock_source import fetch_klines_range, logout

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s', handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("daily_update")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sync_universe() -> List[str]:
    """同步最新全A股清单 (新股上市/退市)"""
    try:
        import akshare as ak
        df = ak.stock_info_a_code_name()
        codes = [str(c) for c in df['code'].tolist() if len(str(c)) == 6 and str(c).isdigit()]
        cache = create_cache()
        cache.set('stock:universe', codes)
        # 补名称
        for _, row in df.iterrows():
            code = str(row['code'])
            name = str(row['name'])
            if name and name != 'nan':
                cache.set(f'stock:name:{code}', name)
        logger.info(f"股票池同步: {len(codes)} 只")
        return codes
    except Exception as e:
        logger.warning(f"股票池同步失败，用缓存: {e}")
        cache = create_cache()
        return cache.get('stock:universe') or []


def incremental_klines(codes: List[str], cache) -> dict:
    """增量更新K线 — 只拉每只股票最后日期之后的新数据"""
    from quant.data.baostock_source import _ensure_login
    _ensure_login()
    import baostock as bs

    today = datetime.now().strftime('%Y-%m-%d')
    today_compact = today.replace('-', '')
    ok = skip = err = total_new = 0
    t0 = time.time()

    for i, code in enumerate(codes, 1):
        code = str(code).split('.')[0]
        key = f'kline:{code}:d'
        existing = cache.get(key) or []

        # 确定起始日期: 缓存最后日期 + 1天
        if existing:
            last_date = existing[-1].get('date', '')
            if last_date:
                # 如果最后日期就是今天，跳过
                if last_date >= today_compact:
                    skip += 1
                    continue
                start = f"{last_date[:4]}-{last_date[4:6]}-{last_date[6:8]}"
            else:
                start = (datetime.now().replace(year=datetime.now().year - 1)).strftime('%Y-%m-%d')
        else:
            # 无缓存，拉近1年
            start = (datetime.now().replace(year=datetime.now().year - 1)).strftime('%Y-%m-%d')

        try:
            fetched = fetch_klines_range(code, start, today)
        except Exception:
            fetched = []

        if fetched:
            if existing:
                existing_dates = {b['date'] for b in existing}
                to_add = [b for b in fetched if b['date'] not in existing_dates]
                if to_add:
                    merged = existing + to_add
                    merged.sort(key=lambda x: x['date'])
                    merged = merged[-300:]
                    cache.set(key, merged)
                    total_new += len(to_add)
                    ok += 1
                else:
                    skip += 1
            else:
                cache.set(key, fetched[-300:])
                total_new += len(fetched)
                ok += 1
        else:
            skip += 1

        if i % 500 == 0:
            elapsed = time.time() - t0
            logger.info(f"  K线增量 [{i}/{len(codes)}] ok={ok} skip={skip} err={err} "
                        f"新增{total_new}根 ({i/elapsed:.1f}/s)")
        time.sleep(0.05)

    logout()
    elapsed = time.time() - t0
    logger.info(f"K线增量完成: ok={ok} skip={skip} err={err}, 新增{total_new}根, {elapsed/60:.1f}分")
    return {'ok': ok, 'skip': skip, 'err': err, 'new_bars': total_new}


def refresh_financials(codes: List[str], cache) -> dict:
    """全量刷新财务 (季度任务，较慢)"""
    from quant.data.akshare_source import fetch_financial_abstract
    ok = err = 0
    t0 = time.time()
    for i, code in enumerate(codes, 1):
        try:
            df = fetch_financial_abstract(code)
            if df is not None and not df.empty:
                cache.set(f'fin:abstract:{code}', df.to_dict(orient='records'))
                ok += 1
            else:
                err += 1
        except Exception:
            err += 1
        if i % 100 == 0:
            elapsed = time.time() - t0
            logger.info(f"  财务 [{i}/{len(codes)}] ok={ok} err={err} ({i/elapsed:.2f}/s)")
        time.sleep(0.3)
    elapsed = time.time() - t0
    logger.info(f"财务刷新完成: ok={ok} err={err}, {elapsed/60:.1f}分")
    return {'ok': ok, 'err': err}


def main():
    ap = argparse.ArgumentParser(description='每日增量更新 (K线+财务)')
    ap.add_argument('--financial', action='store_true', help='同时刷新财务 (慢，约5小时)')
    ap.add_argument('--limit', type=int, default=0, help='限制数量(测试用)')
    args = ap.parse_args()

    logger.info("=" * 55)
    logger.info(f"每日增量更新 @ {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    logger.info("=" * 55)

    # 1. 同步股票池
    codes = sync_universe()
    if args.limit > 0:
        codes = codes[:args.limit]

    cache = create_cache()

    # 2. K线增量 (快)
    results = {}
    results['kline'] = incremental_klines(codes, cache)

    # 3. 财务全量 (可选，慢)
    if args.financial:
        results['financial'] = refresh_financials(codes, cache)

    # 4. 汇总
    kline_count = len(cache.keys('kline:*:d'))
    logger.info("=" * 55)
    logger.info("更新完成!")
    logger.info(f"  K线股票: {kline_count}")
    logger.info(f"  新增K线: {results['kline']['new_bars']} 根")
    if 'financial' in results:
        logger.info(f"  财务刷新: ok={results['financial']['ok']}")
    logger.info("=" * 55)


if __name__ == '__main__':
    main()
