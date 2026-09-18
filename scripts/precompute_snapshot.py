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
from quant.factor.input_contract import governed_daily_bars, load_factor_input_snapshot
from scripts.data_freshness import get_expected_date
from scripts.scan_strategies import latest_kline_date_from_cache

cache = create_cache()
input_snapshot = load_factor_input_snapshot(cache, expected_date=get_expected_date())
fe = FactorEngine(cache=cache)  # 传 cache 才能计算基本面因子
keys = [f"kline:{code}:d" for code in input_snapshot.eligible_codes]
print(f"预计算全市场截面因子 ({len(keys)} 只)...")

rows = []
t0 = time.time()
for i, k in enumerate(keys, 1):
    bars = governed_daily_bars(cache, k.split(':')[1], input_snapshot)
    if not bars or len(bars) < 30:
        continue
    code = k.split(':')[1]
    try:
        df = load_kline_df(bars)
        fdf = fe.compute_all(df, code=code)
        if fdf.empty:
            continue
        latest = fdf.iloc[-1]
        latest_date = str(latest.get('date') or '').replace('-', '')[:8]
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
        rows.append({'code': code, 'name': name, 'date': latest_date, 'close': round(close,2), 'change_pct': chg, 'factors': fvals})
    except Exception:
        pass
    if i % 1000 == 0:
        print(f"  [{i}/{len(keys)}] ({i/(time.time()-t0):.1f}/s)")

latest_kline_date = latest_kline_date_from_cache(cache)
snapshot = {
    'rows': rows,
    '_ts': time.time(),
    'n': len(rows),
    'source': 'precompute_snapshot',
    'latest_kline_date': latest_kline_date,
    **input_snapshot.metadata(),
}
cache.set('factor:snapshot', snapshot)
print(f"完成: {len(rows)} 只, {time.time()-t0:.0f}s")
print(f"缓存已写入 'factor:snapshot', factor_stocks API 将秒回")
