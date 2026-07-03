"""构建因子快照: 计算 5207 只股票的因子 + K线，pickle 保存。
供 evaluate_factors.py 和 scan_strategies.py 复用，避免每次 ~9 分钟重算。

用法: python scripts/build_snapshot.py
"""
import os
import pickle
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache
from quant.data.loader import load_kline_df
from quant.factor import FactorEngine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'factor_snapshot.pkl')


def main():
    cache = create_cache()
    keys = cache.keys('kline:*:d')
    print(f"=== 构建因子快照 ({len(keys)} 只股票) ===")
    fe = FactorEngine(cache=None)
    mf, mk = {}, {}
    t0 = time.time()
    for i, k in enumerate(keys, 1):
        bars = cache.get(k)
        if not bars:
            continue
        code = k.split(':')[1]
        try:
            df = load_kline_df(bars)
            mf[code] = fe.compute_all(df, code=None)
            mk[code] = df
        except Exception:
            pass
        if i % 500 == 0:
            el = time.time() - t0
            print(f"  [{i}/{len(keys)}] ({i/el:.1f}/s)", flush=True)
    el = time.time() - t0
    print(f"因子计算完成: {len(mf)} 只, {el:.0f}s")
    with open(OUT, 'wb') as f:
        pickle.dump({'mf': mf, 'mk': mk, 'saved_at': time.time()},
                    f, protocol=pickle.HIGHEST_PROTOCOL)
    size_mb = os.path.getsize(OUT) / 1e6
    print(f"快照已保存: {OUT} ({size_mb:.1f} MB)")


if __name__ == '__main__':
    main()
