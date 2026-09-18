"""补充 current_ratio 数据源 — 从 stock_financial_abstract (80项指标) 逐股采集

批量采集的东财快报表 (stock_yjbb_em/zcfz_em) 没有流动比率字段，
而 stock_financial_abstract 的 80 项指标里有"流动比率"。
本脚本逐股采集该指标，存到 fin:supplement:<code>，
供 compute_fundamental 在嵌套格式下补齐 current_ratio。

用法:
  python scripts/supplement_current_ratio.py              # 全市场
  python scripts/supplement_current_ratio.py --limit 100  # 只补前100只 (调试)
  python scripts/supplement_current_ratio.py --codes 600519,000858

注意: 逐股采集较慢 (~2-3 只/秒)，全市场约 30-40 分钟。
建议在数据更新后离线运行一次。
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache
from quant.data.akshare_source import fetch_financial_abstract

cache = create_cache()
SUPPLEMENT_KEY = 'fin:supplement:{code}'


def fetch_current_ratio_series(code: str) -> dict:
    """从 stock_financial_abstract 提取 流动比率 时序。

    Returns:
        {report_date(YYYYMMDD): current_ratio_value} 或 {}
    """
    df = fetch_financial_abstract(code)
    if df.empty:
        return {}
    out = {}
    for _, row in df.iterrows():
        rd = str(row.get('report_date') or '')
        if len(rd) != 8:
            continue
        v = row.get('流动比率')
        if v is None:
            continue
        try:
            f = float(v)
            if f == f:  # 非 NaN
                out[rd] = f
        except (TypeError, ValueError):
            continue
    return out


def main():
    ap = argparse.ArgumentParser(description='补充 current_ratio 数据源')
    ap.add_argument('--codes', default='', help='指定股票代码 (逗号分隔), 不指定则全市场')
    ap.add_argument('--limit', type=int, default=0, help='只处理前 N 只 (0=不限)')
    args = ap.parse_args()

    # 确定待处理股票: 只补嵌套格式的 (平铺格式已有 current_ratio 字段)
    if args.codes:
        target = [c.strip() for c in args.codes.split(',') if c.strip()]
    else:
        all_keys = cache.keys('fin:abstract:*')
        target = []
        for k in all_keys:
            raw = cache.get(k)
            if not raw:
                continue
            code = k.split(':')[2]
            # 只处理嵌套格式 (无 report_date 顶层字段)
            if isinstance(raw, list) and raw and 'tables' in (raw[0] or {}):
                target.append(code)

    if args.limit > 0:
        target = target[:args.limit]

    print(f"待补充 current_ratio: {len(target)} 只股票")
    if not target:
        print("无嵌套格式财务记录，无需补充")
        return

    ok = err = skip = 0
    t0 = time.time()
    for i, code in enumerate(target, 1):
        try:
            series = fetch_current_ratio_series(code)
            if series:
                # 按 period 降序存, 取最近若干期
                sorted_series = dict(sorted(series.items(), key=lambda x: x[0], reverse=True)[:20])
                cache.set(SUPPLEMENT_KEY.format(code=code), sorted_series)
                ok += 1
            else:
                skip += 1
        except Exception as e:
            err += 1
            if err <= 5:
                print(f"  [{code}] 失败: {e}")

        if i % 100 == 0:
            elapsed = time.time() - t0
            print(f"  [{i}/{len(target)}] ok={ok} skip={skip} err={err} "
                  f"({i/elapsed:.1f}/s, 预计剩余 {(len(target)-i)/(i/elapsed):.0f}s)")
            time.sleep(0.3)  # 礼貌限速

    elapsed = time.time() - t0
    print(f"\n完成: ok={ok} skip={skip} err={err} / total={len(target)}, {elapsed:.0f}s")
    print(f"补充数据已写入 fin:supplement:<code>, compute_fundamental 会自动读取")


if __name__ == '__main__':
    main()
