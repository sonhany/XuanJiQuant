"""全链路冒烟测试 — 验证系统各层在 SQLite 下正常工作

覆盖:
  1. 存储层: SqliteCache 读写/TTL/keys
  2. 数据层: 腾讯日K + AKShare财务 拉取并持久化
  3. 因子层: 47 因子计算 + IC 评估
  4. 策略层: 4 策略执行 + 回测
  5. 执行层: 模拟下单 + 持仓
  6. 风控层: 组合风险计算
  7. 引擎包导入完整性

用法: python scripts/smoke_test.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant.data.cache import create_cache, reset_cache, SqliteCache


def header(t):
    print(f"\n{'='*55}\n  {t}\n{'='*55}")


def run_all():
    results = []
    cache = create_cache()
    cache.clear()  # 干净起点

    # ── 1. 存储层 ──────────────────────────────
    header("1. 存储层 (SqliteCache)")
    assert type(cache).__name__ == 'SqliteCache', f"expected SqliteCache, got {type(cache).__name__}"
    cache.set('test:k', {'a': 1, 'b': [1, 2, 3]})
    assert cache.get('test:k')['b'] == [1, 2, 3], "set/get failed"
    cache.set('test:expire', 'v', ttl=1)
    time.sleep(1.1)
    assert cache.get('test:expire') is None, "TTL failed"
    cache.delete('test:k')
    cache.set('kline:600519:d', [{'date': '20260101'}])
    got = set(cache.keys('kline:*:d'))
    assert got == {'kline:600519:d'}, f"keys glob failed, got {got}"
    cache.clear()
    print("  [PASS] get/set/TTL/keys/clear")
    results.append(('存储层', True))

    # ── 2. 数据层 ──────────────────────────────
    header("2. 数据层 (腾讯日K + AKShare财务)")
    from quant.data.tencent_source import fetch_klines
    from quant.data.loader import load_kline_df

    klines = {}
    for code in ['600519', '000001', '300750']:
        bars = fetch_klines(code, count=120)
        assert bars and len(bars) > 50, f"{code} klines empty"
        klines[code] = load_kline_df(bars)
        cache.set(f'kline:{code}:d', bars)
    print(f"  [PASS] 腾讯日K: {len(klines)} 只股票, 每只 {len(bars)} 根")

    # 财务
    from quant.data.akshare_source import fetch_core_financials
    fin = fetch_core_financials('600519')
    assert not fin.empty and 'roe' in fin.columns, "financial empty"
    cache.set('fin:abstract:600519', fin.to_dict(orient='records'))
    print(f"  [PASS] AKShare财务: 600519 {fin.shape[0]} 季度 × {fin.shape[1]} 指标")
    results.append(('数据层', True))

    # ── 3. 因子层 ──────────────────────────────
    header("3. 因子层 (量价19 + 技术28 + 基本面11 = 58)")
    from quant.factor import FactorEngine
    fe = FactorEngine(cache=cache)
    factor_dfs = fe.compute_multi(klines)
    n_factors = len(fe.list_factors())
    assert n_factors == 58, f"expected 58 factors, got {n_factors}"
    for code, fdf in factor_dfs.items():
        assert fdf.shape[1] >= 7 + n_factors, f"{code} factor cols short"
    # 验证基本面因子有值 (600519 有财务数据，前向填充应非全空)
    fin_cols = ['roe', 'gross_margin', 'debt_ratio']
    if '600519' in factor_dfs:
        non_null = factor_dfs['600519']['roe'].notna().sum()
        assert non_null > 0, "基本面因子 roe 全空，前向填充未生效"
    print(f"  [PASS] {n_factors} 因子计算完成, {len(factor_dfs)} 只股票")
    print(f"         600519 基本面因子 roe 非空: {non_null}/121 交易日")
    results.append(('因子层', True))

    # ── 4. 策略层 + 回测 ───────────────────────
    header("4. 策略层 + 事件驱动回测")
    from quant.strategy import StrategyEngine
    se = StrategyEngine(factor_engine=FactorEngine(cache=None))
    strategies = ['factor_rank', 'multi_factor', 'ma_cross', 'bb_reversion']
    for sname in strategies:
        params = {'factors': 'rsi_6,macd_hist,bias_20', 'weights': '0.4,0.3,0.3'} if sname == 'multi_factor' else {}
        res = se.run_strategy(sname, params, klines)
        bt = res.get('backtest', {})
        assert 'metrics' in bt, f"{sname} no metrics"
    m = res['backtest']['metrics']
    print(f"  [PASS] 4 策略全部可执行")
    print(f"         末策略回测: trades={m.get('total_trades')}, "
          f"sharpe={m.get('sharpe_ratio')}, maxDD={m.get('max_drawdown_pct')}%")
    results.append(('策略层+回测', True))

    # ── 5. 执行层 ──────────────────────────────
    header("5. 执行层 (模拟交易)")
    from quant.execution import ExecutionEngine
    ee = ExecutionEngine(initial_capital=1_000_000)
    o = ee.place_order('600519', 'buy', 100, 'market')
    r = ee.fill_order(o['id'], 1800.0)
    assert r['success'], "fill failed"
    port = ee.get_portfolio()
    assert port['position_count'] == 1 and port['cash'] < 1_000_000
    print(f"  [PASS] 下单+成交+持仓: cash={port['cash']}, positions={port['position_count']}")
    results.append(('执行层', True))

    # ── 6. 风控层 ──────────────────────────────
    header("6. 风控层")
    from quant.risk import RiskEngine
    re = RiskEngine(cache=cache)
    state = {
        'cash': 820000, 'initial_capital': 1_000_000,
        'positions': {'600519': {'quantity': 100, 'avg_price': 1800, 'current_price': 1810}},
    }
    risk = re.portfolio_risk(state)
    assert 'concentration_pct' in risk and 'total_equity' in risk
    health = re.system_health()
    assert 'overall' in health
    print(f"  [PASS] 组合风险: equity={risk['total_equity']}, health={health['overall']}")
    results.append(('风控层', True))

    # ── 7. 引擎包导入完整性 ────────────────────
    header("7. 包导入完整性")
    # 仅验证数据层各导出符号存在 + 引擎包可导入
    from quant.data import (SqliteCache, RedisCache, MemoryCache,
                            fetch_quotes, validate_bar, validate_series)
    import quant.data as _qd
    for sym in ('create_cache', 'fetch_klines', 'fetch_core_financials', 'load_kline_df'):
        assert hasattr(_qd, sym), f"quant.data missing {sym}"
    from quant.factor import FactorEngine
    from quant.strategy import StrategyEngine
    from quant.backtest import BacktestSimulator
    from quant.execution import ExecutionEngine
    from quant.risk import RiskEngine
    print("  [PASS] 所有引擎包和数据层导出正常")
    results.append(('包导入', True))

    # ── 汇总 ──────────────────────────────────
    header("冒烟测试汇总")
    all_pass = all(ok for _, ok in results)
    for name, ok in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    print()
    if all_pass:
        print("  ✅ 全部通过 — 系统在 SQLite 下运行正常")
    else:
        print("  ❌ 有失败项，请检查")
    return all_pass


if __name__ == '__main__':
    ok = run_all()
    sys.exit(0 if ok else 1)
