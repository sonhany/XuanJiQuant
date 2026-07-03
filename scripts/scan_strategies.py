"""全市场策略扫描 — 用评估出的有效因子做截面选股回测

基于 factor_evaluation.json 的结果，用 Top 因子做:
  1. 每个强有效因子单独的截面选股策略 (买因子值最优的20只)
  2. 多因子复合策略 (IC加权)
  3. 对比各策略的年化收益/夏普/回撤/胜率

输出: data/strategy_scan.json (+ _realistic.json) + Top股票池
用法:
  python scripts/scan_strategies.py              # 理想化 (无成本, 无涨跌停)
  python scripts/scan_strategies.py --realistic  # 真实约束 (涨跌停+交易成本)
耗时: 约15-25分钟
"""
import argparse
import json
import logging
import os
import pickle
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache
from quant.data.loader import load_kline_df
from quant.factor import FactorEngine
from quant.factor.price_volume import PRICE_VOLUME_FACTORS
from quant.factor.technical import TECHNICAL_FACTORS
from quant.backtest.engine import is_limit_bar

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("scan")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVAL_FILE = os.path.join(ROOT, 'data', 'factor_evaluation.json')
OUT_FILE = os.path.join(ROOT, 'data', 'strategy_scan.json')
OUT_FILE_REALISTIC = os.path.join(ROOT, 'data', 'strategy_scan_realistic.json')
SNAPSHOT_FILE = os.path.join(ROOT, 'data', 'factor_snapshot.pkl')  # 与 evaluate_factors 共用

# 真实回测约束参数
REALISTIC_COST = 0.0015  # 单边成本: 印花税0.05%(卖)+佣金0.03%+滑点0.05% ≈ 0.15%
LIMIT_TOLERANCE = 0.002  # 涨跌停判定容差

# 从因子评估选出的强有效因子 (IC方向已确定)
STRONG_FACTORS = {
    'pvbeta_20':     -1,   # 负IC: 值越小越好
    'volatility_20': -1,
    'pvcorr_10':     -1,
    'range_pct':     -1,
    'volatility_60': -1,
    'ret_60':        -1,
    'volatility_5':  -1,
    'gap_pct':        1,   # 正IC: 值越大越好
    'overnight_ret':  1,
    'pvcorr_5':      -1,
}
TOP_N = 20  # 每期选股数
HOLD_DAYS = 5


def load_factors_for_all(cache, fe, use_snapshot=True):
    """计算所有股票的因子，返回 {code: factor_df}。
    优先从 factor_snapshot.pkl 加载 (与 evaluate_factors 共用), 避免 ~9 分钟重算。
    """
    if use_snapshot and os.path.exists(SNAPSHOT_FILE):
        try:
            with open(SNAPSHOT_FILE, 'rb') as f:
                snap = pickle.load(f)
            logger.info(f"从快照加载因子: {len(snap['mf'])} 只 ({SNAPSHOT_FILE})")
            return snap['mf']
        except Exception as e:
            logger.warning(f"快照加载失败 ({e}), 重新计算")
    keys = cache.keys('kline:*:d')
    mf = {}
    t0 = time.time()
    for i, k in enumerate(keys, 1):
        bars = cache.get(k)
        if not bars:
            continue
        code = k.split(':')[1]
        try:
            df = load_kline_df(bars)
            mf[code] = fe.compute_all(df, code=None)
        except Exception:
            pass
        if i % 1000 == 0:
            logger.info(f"  因子计算 [{i}/{len(keys)}] ({i/(time.time()-t0):.1f}/s)")
    logger.info(f"因子计算完成: {len(mf)} 只, {time.time()-t0:.0f}s")
    return mf


def build_limit_map(mf, cache):
    """预构建 {code: {date: limit_flag}} 用于真实回测涨跌停过滤。

    limit_flag: 1=涨停封板(买不进), -1=跌停封板(卖不出), 0=正常。
    向量化实现: 用 numpy 一次性算每个 code 的封板状态，避免逐行 Python 调用。
    """
    from quant.backtest.engine import limit_ratio_for
    limit_map = {}
    n_locked = 0
    # 预取所有股票名 (ST 检测)，一次性查缓存
    name_map = {}
    if cache is not None:
        for code in mf.keys():
            try:
                name_map[code] = cache.get(f'stock:name:{code}') or ''
            except Exception:
                name_map[code] = ''

    for code, fdf in mf.items():
        if fdf is None or fdf.empty:
            continue
        df = fdf.copy()
        for col in ('close', 'high', 'low'):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.sort_values('date').reset_index(drop=True)
        pc = df['close'].shift(1).to_numpy()
        high = df['high'].to_numpy()
        low = df['low'].to_numpy()
        close = df['close'].to_numpy()
        dates = df['date'].to_numpy()
        # 该 code 的涨跌停比例
        ratio = 0.05 if 'ST' in name_map.get(code, '') else limit_ratio_for(code, None)
        tol = LIMIT_TOLERANCE

        per_code = {}
        for i in range(len(df)):
            p, h, l, c = pc[i], high[i], low[i], close[i]
            if np.isnan(p) or p <= 0 or np.isnan(h) or h <= 0:
                per_code[dates[i]] = 0
                continue
            flag = 0
            # 一字板
            if not np.isnan(l) and l > 0 and abs(h - l) < 0.01:
                flag = 1 if c >= p else -1
            elif not np.isnan(c) and c > 0:
                if c >= p * (1 + ratio - tol):
                    flag = 1
                elif c <= p * (1 - ratio + tol):
                    flag = -1
            per_code[dates[i]] = flag
            if flag != 0:
                n_locked += 1
        limit_map[code] = per_code
    logger.info(f"涨跌停 map 构建完成: {len(limit_map)} 只, 封板 bar 数={n_locked}")
    return limit_map


def cross_sectional_backtest(mf, factor_name, direction, top_n=TOP_N, hold=HOLD_DAYS,
                             realistic=False, limit_map=None):
    """单因子截面选股回测

    每 hold 天调仓一次: 按因子值排名选 top_n 只，等权持有 hold 天。
    direction: +1 选因子值大的, -1 选因子值小的

    realistic=True 时:
    - 涨停股当日买不进 (从选股池剔除)
    - 每次调仓扣单边交易成本 REALISTIC_COST

    向量化实现: 用 pivot 构建 (date × code) 的因子/收盘价矩阵，避免逐股 DataFrame 查找。
    """
    # 收集 (date, code, factor_value, close) 长表
    rows = []
    for code, fdf in mf.items():
        if factor_name not in fdf.columns:
            continue
        sub = fdf[['date', factor_name, 'close']].copy()
        sub[factor_name] = pd.to_numeric(sub[factor_name], errors='coerce')
        sub['close'] = pd.to_numeric(sub['close'], errors='coerce')
        sub = sub.dropna()
        sub['code'] = code
        rows.append(sub[['date', 'code', factor_name, 'close']])
    if not rows:
        return None
    long_df = pd.concat(rows, ignore_index=True).dropna()
    all_dates = sorted(long_df['date'].unique())
    if len(all_dates) < hold * 2:
        return None

    # pivot 成宽表 (date × code): 因子值和收盘价
    fac_wide = long_df.pivot(index='date', columns='code', values=factor_name).sort_index()
    cls_wide = long_df.pivot(index='date', columns='code', values='close').sort_index()
    # 未来 hold 天收益: close[next_d] / close[d] - 1
    fwd_ret_wide = cls_wide.shift(-hold) / cls_wide - 1.0
    rebalance_dates = list(fac_wide.index)[::hold]
    codes_arr = fac_wide.columns.to_numpy()

    portfolio_returns = []
    limit_skips = 0
    for i in range(len(rebalance_dates) - 1):
        d = rebalance_dates[i]
        if d not in fac_wide.index:
            continue
        fac_row = fac_wide.loc[d].dropna()
        n = len(fac_row)
        if n < top_n * 2:
            continue
        # 选股: 按 direction 排序取 top_n
        asc = (direction < 0)
        selected_codes = list(fac_row.sort_values(ascending=asc).head(top_n).index)
        # 真实模式: 涨停股当日买不进
        if realistic and limit_map:
            keep = []
            for c in selected_codes:
                if limit_map.get(c, {}).get(d, 0) != 1:
                    keep.append(c)
                else:
                    limit_skips += 1
            selected_codes = keep
        if not selected_codes:
            continue
        # 向量化取这些股票的未来收益
        try:
            rets = fwd_ret_wide.loc[d, selected_codes].dropna().to_numpy(dtype=float)
        except KeyError:
            continue
        if realistic and len(rets):
            rets = rets - REALISTIC_COST
        if len(rets):
            portfolio_returns.append({'date': d, 'ret': float(np.mean(rets)), 'n': len(rets)})

    if len(portfolio_returns) < 5:
        return None
    pr = pd.DataFrame(portfolio_returns).sort_values('date')

    # 计算绩效 (持有期收益 -> 年化)
    rets = pr['ret'].dropna()
    if len(rets) < 5:
        return None
    cumulative = (1 + rets).cumprod()
    total_ret = cumulative.iloc[-1] - 1
    n_rebalances = len(rets)
    # 年化: 每年调仓 252/hold 次
    rebalances_per_year = 252 / hold
    annual_ret = (1 + total_ret) ** (rebalances_per_year / n_rebalances) - 1 if n_rebalances > 0 else 0
    # 夏普: 基于每次调仓收益
    sharpe = (rets.mean() / rets.std() * np.sqrt(rebalances_per_year)) if rets.std() > 0 else 0
    peak = cumulative.cummax()
    dd = (cumulative - peak) / peak
    max_dd = dd.min()
    win_rate = (rets > 0).mean()

    result = {
        'factor': factor_name,
        'direction': '多(值大)' if direction > 0 else '空(值小)',
        'n_periods': len(rets),
        'total_return_pct': round(total_ret * 100, 2),
        'annual_return_pct': round(annual_ret * 100, 2),
        'sharpe': round(sharpe, 3),
        'max_drawdown_pct': round(max_dd * 100, 2),
        'win_rate_pct': round(win_rate * 100, 1),
    }
    if realistic:
        result['limit_skips'] = int(limit_skips)
        result['realistic'] = True
    return result


def multi_factor_backtest(mf, factor_weights, top_n=TOP_N, hold=HOLD_DAYS,
                          realistic=False, limit_map=None):
    """多因子IC加权复合策略 (向量化实现)"""
    # 1. 收集每个因子的 (date × code) 宽表 + 收盘价宽表
    factor_wide = {}
    for fname in factor_weights:
        rows = []
        for code, fdf in mf.items():
            if fname not in fdf.columns:
                continue
            sub = fdf[['date', fname]].copy()
            sub[fname] = pd.to_numeric(sub[fname], errors='coerce')
            sub['code'] = code
            rows.append(sub)
        if not rows:
            continue
        factor_wide[fname] = pd.concat(rows, ignore_index=True).pivot(
            index='date', columns='code', values=fname).sort_index()

    close_rows = []
    for code, fdf in mf.items():
        sub = fdf[['date', 'close']].copy()
        sub['close'] = pd.to_numeric(sub['close'], errors='coerce')
        sub['code'] = code
        close_rows.append(sub)
    cls_wide = pd.concat(close_rows, ignore_index=True).pivot(
        index='date', columns='code', values='close').sort_index()
    # 未来 hold 天收益: close.shift(-hold)/close - 1 (修正原版的双 shift bug)
    fwd_ret_wide = cls_wide.shift(-hold) / cls_wide - 1.0

    # 2. 横截面 z-score 加权打分 (向量化: 按行)
    # 对齐所有因子宽表到同一行列
    common_idx = cls_wide.index
    common_cols = cls_wide.columns
    score = pd.DataFrame(0.0, index=common_idx, columns=common_cols)
    for fname, w in factor_weights.items():
        if fname not in factor_wide:
            continue
        fw = factor_wide[fname].reindex(index=common_idx, columns=common_cols)
        mu = fw.mean(axis=1)
        sd = fw.std(axis=1)
        z = fw.sub(mu, axis=0).div(sd.replace(0, np.nan), axis=0).fillna(0)
        score = score.add(w * z, fill_value=0)

    # 3. 每日选 top_n (向量化: 用 rank)
    # 标记无效 (NaN fwd_ret) 为 -inf 使其不被选
    selectable = score.where(fwd_ret_wide.notna(), -np.inf)
    # 按行取 top_n 的掩码
    top_n_mask = pd.DataFrame(False, index=common_idx, columns=common_cols)
    for date in common_idx:
        row = selectable.loc[date]
        valid_cnt = (row > -np.inf).sum()
        if valid_cnt < top_n * 2:
            continue
        top_codes = row.nlargest(top_n).index
        top_n_mask.loc[date, top_codes] = True

    # 4. 计算每日期间的组合收益 = 选中股票 fwd_ret 均值
    portfolio_returns = []
    limit_skips = 0
    for date in common_idx:
        if not top_n_mask.loc[date].any():
            continue
        sel_codes = top_n_mask.columns[top_n_mask.loc[date]].tolist()
        # 真实模式: 涨停股买不进
        if realistic and limit_map:
            keep = []
            for c in sel_codes:
                if limit_map.get(c, {}).get(date, 0) != 1:
                    keep.append(c)
                else:
                    limit_skips += 1
            sel_codes = keep
        if not sel_codes:
            continue
        rets = fwd_ret_wide.loc[date, sel_codes].dropna()
        if len(rets) == 0:
            continue
        r = float(rets.mean())
        if realistic:
            r -= REALISTIC_COST
        portfolio_returns.append({'date': date, 'ret': r})
    if not portfolio_returns:
        return None
    pr = pd.DataFrame(portfolio_returns).sort_values('date')
    rets = pr['ret'].dropna()
    if len(rets) < 10:
        return None
    cumulative = (1 + rets).cumprod()
    total_ret = cumulative.iloc[-1] - 1
    n_days = len(rets)
    annual_ret = (1 + total_ret) ** (252 / n_days) - 1 if n_days > 0 else 0
    sharpe = (rets.mean() / rets.std() * np.sqrt(252 / hold)) if rets.std() > 0 else 0
    peak = cumulative.cummax()
    max_dd = ((cumulative - peak) / peak).min()
    win_rate = (rets > 0).mean()
    result = {
        'factor': '多因子复合(IC加权)',
        'direction': f'{len(factor_weights)}因子',
        'n_periods': len(rets),
        'total_return_pct': round(total_ret * 100, 2),
        'annual_return_pct': round(annual_ret * 100, 2),
        'sharpe': round(sharpe, 3),
        'max_drawdown_pct': round(max_dd * 100, 2),
        'win_rate_pct': round(win_rate * 100, 1),
    }
    if realistic:
        result['limit_skips'] = int(limit_skips)
        result['realistic'] = True
    return result


def main():
    ap = argparse.ArgumentParser(description='全市场策略扫描')
    ap.add_argument('--realistic', action='store_true',
                    help='启用真实回测约束 (涨跌停拒绝+交易成本)')
    ap.add_argument('--no-cache', action='store_true',
                    help='忽略因子快照，强制重新计算')
    args = ap.parse_args()

    cache = create_cache()
    fe = FactorEngine(cache=None)
    out_file = OUT_FILE_REALISTIC if args.realistic else OUT_FILE

    logger.info("=== 全市场策略扫描 ===")
    logger.info(f"回测模式: {'真实 (涨跌停+成本)' if args.realistic else '理想化'}")
    # 1. 计算因子
    mf = load_factors_for_all(cache, fe, use_snapshot=not args.no_cache)

    # 真实模式: 预构建涨跌停 map
    limit_map = None
    if args.realistic:
        logger.info("构建涨跌停封板 map...")
        limit_map = build_limit_map(mf, cache)

    # 2. 单因子策略回测
    logger.info(f"单因子截面选股回测 (Top{TOP_N}, 持有{HOLD_DAYS}天)...")
    results = []
    for fname, direction in STRONG_FACTORS.items():
        t0 = time.time()
        r = cross_sectional_backtest(mf, fname, direction,
                                     realistic=args.realistic, limit_map=limit_map)
        if r:
            results.append(r)
            logger.info(f"  {fname:18s}: 年化{r['annual_return_pct']:+.1f}% 夏普{r['sharpe']:+.2f} "
                        f"回撤{r['max_drawdown_pct']:.1f}% 胜率{r['win_rate_pct']:.0f}% ({time.time()-t0:.0f}s)")

    # 3. 多因子复合策略 (IC加权: 用IC作为权重)
    logger.info("多因子复合策略...")
    # 读取IC评估结果作权重
    weights = {}
    if os.path.exists(EVAL_FILE):
        with open(EVAL_FILE, encoding='utf-8') as f:
            eval_data = json.load(f)
        for item in eval_data.get('factors', []):
            fn = item['factor']
            if fn in STRONG_FACTORS:
                # 权重 = IC值 * 方向符号 (让所有因子贡献为正)
                weights[fn] = item['ic_1d'] * STRONG_FACTORS[fn]
                weights[fn] = max(weights[fn], 0)  # 负贡献的不用
    # 归一化
    total_w = sum(abs(v) for v in weights.values())
    if total_w > 0:
        weights = {k: v / total_w for k, v in weights.items()}
        logger.info(f"  复合权重: {weights}")
        mf_result = multi_factor_backtest(mf, weights,
                                          realistic=args.realistic, limit_map=limit_map)
        if mf_result:
            results.append(mf_result)

    # 4. 排序 + 保存
    results.sort(key=lambda x: x['sharpe'], reverse=True)
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump({'scanned_at': time.strftime('%Y-%m-%d %H:%M'),
                   'realistic': args.realistic,
                   'n_stocks': len(mf), 'top_n': TOP_N, 'hold_days': HOLD_DAYS,
                   'strategies': results}, f, ensure_ascii=False, indent=2)
    logger.info(f"结果已保存: {out_file}")

    # 5. 打印
    mode_label = '真实约束' if args.realistic else '理想化'
    print("\n" + "=" * 75)
    print(f"  全市场策略扫描结果 [{mode_label}] ({len(mf)} 只, Top{TOP_N}选股, 持有{HOLD_DAYS}天)")
    print("=" * 75)
    print(f"{'策略':<24} {'方向':<12} {'年化%':>8} {'夏普':>7} {'回撤%':>7} {'胜率%':>6}")
    print("-" * 75)
    for r in results:
        star = ' ★' if r['sharpe'] > 0.5 else (' ●' if r['sharpe'] > 0 else '')
        print(f"{r['factor']:<24} {r['direction']:<12} {r['annual_return_pct']:+8.1f} "
              f"{r['sharpe']:+7.2f} {r['max_drawdown_pct']:>7.1f} {r['win_rate_pct']:>5.0f}{star}")
    print("=" * 75)
    n_profit = sum(1 for r in results if r['annual_return_pct'] > 0)
    print(f"  盈利策略: {n_profit}/{len(results)}")
    best = results[0] if results else None
    if best:
        print(f"  最佳: {best['factor']} (年化{best['annual_return_pct']:+.1f}%, 夏普{best['sharpe']})")
    if args.realistic and results:
        total_skips = sum(r.get('limit_skips', 0) for r in results)
        print(f"  涨停拒绝次数: {total_skips} (单边成本 {REALISTIC_COST*100:.2f}%/调仓)")
    print("=" * 75)


if __name__ == '__main__':
    main()
