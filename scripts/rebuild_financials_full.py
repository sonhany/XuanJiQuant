"""全市场历史多期财报采集 — 用 fetch_core_financials 覆盖 fin:abstract

为什么需要:
  批量重建 (rebuild_financials_bulk) 产出的嵌套格式每只股票只有最新 1 期财报,
  导致 train/valid 分段的因子值为空。本脚本逐股调用 stock_financial_abstract
  (80项指标), 获取完整历史多期 (约 100+ 季度) 并以平铺格式存储,
  使所有 11 个基本面因子在完整时间轴上都有值。

产出:
  fin:abstract:<code> = [{report_date, code, roe, roa, ...}] (平铺格式, 多期)

用法:
  python scripts/rebuild_financials_full.py              # 全市场
  python scripts/rebuild_financials_full.py --limit 50   # 只跑前50只 (调试)
  python scripts/rebuild_financials_full.py --workers 6  # 并发数

注意: 逐股采集较慢 (~1-2 只/秒), 全市场约 1-2 小时。建议离线运行。
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache
from quant.data.akshare_source import fetch_core_financials

cache = create_cache()


def main():
    ap = argparse.ArgumentParser(description='全市场历史多期财报采集')
    ap.add_argument('--workers', type=int, default=6, help='并发线程数')
    ap.add_argument('--limit', type=int, default=0, help='只处理前N只 (0=不限)')
    args = ap.parse_args()

    # 获取所有需要处理的股票 (有 K 线数据的)
    kline_keys = cache.keys('kline:*:d')
    all_codes = []
    for k in kline_keys:
        code = k.split(':')[1]
        all_codes.append(code)
    print(f"待采集: {len(all_codes)} 只股票", flush=True)
    if args.limit > 0:
        all_codes = all_codes[:args.limit]
        print(f"限制为前 {args.limit} 只", flush=True)

    from concurrent.futures import ThreadPoolExecutor, as_completed

    ok = skip = err = 0
    multi_period = 0
    t0 = time.time()

    def fetch_one(code):
        try:
            df = fetch_core_financials(code)
            if df.empty:
                return code, None, 0
            records = df.to_dict(orient='records')
            return code, records, len(records)
        except Exception as e:
            return code, None, 0

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(fetch_one, c): c for c in all_codes}
        for i, fut in enumerate(as_completed(futures), 1):
            code, records, n_periods = fut.result()
            if records:
                cache.set(f'fin:abstract:{code}', records)
                ok += 1
                if n_periods > 5:
                    multi_period += 1
            elif records is None:
                skip += 1
            if i % 200 == 0:
                elapsed = time.time() - t0
                rate = i / elapsed
                eta = (len(all_codes) - i) / rate if rate > 0 else 0
                print(f"  [{i}/{len(all_codes)}] ok={ok} skip={skip} err={err} "
                      f"多期={multi_period} ({rate:.1f}/s, ETA={eta:.0f}s)", flush=True)

    err = len(all_codes) - ok - skip
    elapsed = time.time() - t0
    print(f"\n完成: ok={ok} skip={skip} err={err} / total={len(all_codes)}", flush=True)
    print(f"多期财报 (≥5期): {multi_period} 只", flush=True)
    print(f"耗时: {elapsed:.0f}s ({elapsed/60:.1f}min)", flush=True)
    print(f"数据已写入 fin:abstract:<code> (平铺格式, 多期)", flush=True)


if __name__ == '__main__':
    main()
