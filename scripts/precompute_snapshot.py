"""预计算全市场最新截面因子值，缓存供 factor_stocks API 秒回

计算所有股票最新一天的因子值，存到 cache key 'factor:snapshot'。
前端点击因子查看多空选股时直接读这个缓存，无需实时计算。

用法: python scripts/precompute_snapshot.py  (约3-5分钟)
建议: 每日数据更新后运行一次，或加到 daily_update.bat
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache
from quant.data.loader import load_kline_df
from quant.factor import FactorEngine

cache = create_cache()
fe = FactorEngine(cache=None)
keys = cache.keys('kline:*:d')
print(f"预计算全市场截面因子 ({len(keys)} 只)...")

rows = []
t0 = time.time()
for i, k in enumerate(keys, 1):
    bars = cache.get(k)
    if not bars or len(bars) < 30:
        continue
    code = k.split(':')[1]
    try:
        df = load_kline_df(bars)
        fdf = fe.compute_all(df, code=code)
        if fdf.empty:
            continue
        latest = fdf.iloc[-1]
        close = float(latest.get('close', 0))
        prev_close = float(fdf.iloc[-2].get('close', close)) if len(fdf) >= 2 else close
        chg = round((close - prev_close) / prev_close * 100, 2) if prev_close else 0
        name = cache.get(f'stock:name:{code}') or code
        fvals = {}
        for col in fdf.columns:
            if col in ('date','open','high','low','close','volume','amount'):
                continue
            v = latest.get(col)
            if v is not None:
                try:
                    import math
                    fv = float(v)
                    if not math.isnan(fv):
                        fvals[col] = round(fv, 4)
                except (ValueError, TypeError):
                    pass
        rows.append({'code': code, 'name': name, 'close': round(close,2), 'change_pct': chg, 'factors': fvals})
    except Exception:
        pass
    if i % 1000 == 0:
        print(f"  [{i}/{len(keys)}] ({i/(time.time()-t0):.1f}/s)")

snapshot = {'rows': rows, '_ts': time.time(), 'n': len(rows)}
cache.set('factor:snapshot', snapshot)
print(f"完成: {len(rows)} 只, {time.time()-t0:.0f}s")
print(f"缓存已写入 'factor:snapshot', factor_stocks API 将秒回")
