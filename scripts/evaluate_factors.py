"""全市场因子批量评估 — 用 5207 只股票筛选有效因子

输出:
  1. 每个因子的 IC 均值/IR/正占比 (1日和5日持有期)
  2. 按 |IC| 排序的有效因子榜单
  3. 保存结果到 data/factor_evaluation.json

用法:
  python scripts/evaluate_factors.py              # 原始 IC
  python scripts/evaluate_factors.py --neutralize # 行业+市值中性化 IC
耗时: 约30分钟 (5207只 × 47因子 × 2周期)
"""
import argparse
import json
import logging
import os
import pickle
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache
from quant.data.loader import load_kline_df
from quant.factor import FactorEngine
from quant.factor.technical import TECHNICAL_FACTORS
from quant.factor.price_volume import PRICE_VOLUME_FACTORS

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("eval_factors")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_FILE = os.path.join(ROOT, 'data', 'factor_evaluation.json')
OUT_FILE_NEUTRAL = os.path.join(ROOT, 'data', 'factor_evaluation_neutral.json')
# 因子快照缓存: 避免每次评估都重算 5207 只 × 47 因子 (~9分钟)
SNAPSHOT_FILE = os.path.join(ROOT, 'data', 'factor_snapshot.pkl')


def main():
    ap = argparse.ArgumentParser(description='全市场因子批量评估')
    ap.add_argument('--neutralize', action='store_true',
                    help='启用行业+市值中性化后再计算 IC (区分因子纯粹 Alpha)')
    ap.add_argument('--no-cache', action='store_true',
                    help='忽略因子快照，强制重新计算 (数据更新后用)')
    args = ap.parse_args()

    cache = create_cache()
    n_stocks = len(cache.keys('kline:*:d'))
    logger.info(f"=== 全市场因子评估 ({n_stocks} 只股票) ===")
    logger.info(f"中性化: {'启用 (行业+市值)' if args.neutralize else '关闭'}")

    # 1. 计算所有股票的因子 (有快照则直接加载，避免 ~9 分钟重算)
    fe = FactorEngine(cache=cache if args.neutralize else None)
    mf = {}
    mk = {}
    use_snapshot = not args.no_cache and os.path.exists(SNAPSHOT_FILE)
    if use_snapshot:
        t0 = time.time()
        try:
            with open(SNAPSHOT_FILE, 'rb') as f:
                snap = pickle.load(f)
            mf = snap['mf']
            mk = snap['mk']
            logger.info(f"从快照加载因子: {len(mf)} 只, {time.time()-t0:.1f}s ({SNAPSHOT_FILE})")
        except Exception as e:
            logger.warning(f"快照加载失败 ({e}), 重新计算")
            use_snapshot = False
    if not use_snapshot:
        keys = cache.keys('kline:*:d')
        t0 = time.time()
        for i, k in enumerate(keys, 1):
            bars = cache.get(k)
            if not bars:
                continue
            code = k.split(':')[1]
            try:
                df = load_kline_df(bars)
                mf[code] = fe.compute_all(df, code=None)  # 跳过基本面(财务字段名待统一)
                mk[code] = df
            except Exception as e:
                logger.debug(f"[{code}] 因子计算失败: {e}")
            if i % 500 == 0:
                elapsed = time.time() - t0
                logger.info(f"  因子计算 [{i}/{len(keys)}] ({i/elapsed:.1f}/s)")
        logger.info(f"因子计算完成: {len(mf)} 只, {time.time()-t0:.0f}s")
        # 保存快照供后续评估/扫描复用
        try:
            with open(SNAPSHOT_FILE, 'wb') as f:
                pickle.dump({'mf': mf, 'mk': mk, 'saved_at': time.time()}, f, protocol=pickle.HIGHEST_PROTOCOL)
            logger.info(f"因子快照已保存: {SNAPSHOT_FILE}")
        except Exception as e:
            logger.warning(f"快照保存失败: {e}")

    # 2. IC 评估 (47个量价+技术因子, 1日和5日持有期)
    factors = TECHNICAL_FACTORS + PRICE_VOLUME_FACTORS
    logger.info(f"开始 IC 评估: {len(factors)} 因子 × 2 周期...")
    t0 = time.time()
    result = fe.evaluate_all(mf, mk, factor_names=factors, fwd_horizons=[1, 5],
                             neutralize=args.neutralize)
    logger.info(f"IC 评估完成: {len(result)} 因子, {time.time()-t0:.0f}s")

    # 3. 整理结果
    out = []
    for item in result:
        fname = item.get('factor_name', '')
        summary = item.get('summary') or {}
        decay = item.get('decay') or {}
        fwd1 = decay.get('1d', {})
        fwd5 = decay.get('5d', {})
        out.append({
            'factor': fname,
            'ic_1d': round(summary.get('mean', 0), 4),
            'ir_1d': round(summary.get('ir', 0), 4),
            'positive_1d': round(summary.get('positive_ratio', 0), 3),
            'n_periods': summary.get('n_periods', 0),
            'ic_5d': round(fwd5.get('mean', 0), 4),
            'ir_5d': round(fwd5.get('ir', 0), 4),
            'abs_ic_1d': round(abs(summary.get('mean', 0)), 4),
            'abs_ic_5d': round(abs(fwd5.get('mean', 0)), 4),
        })

    # 按 |IC 1d| 降序
    out.sort(key=lambda x: x['abs_ic_1d'], reverse=True)

    # 4. 保存
    out_file = OUT_FILE_NEUTRAL if args.neutralize else OUT_FILE
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump({'evaluated_at': time.strftime('%Y-%m-%d %H:%M'),
                   'neutralized': args.neutralize,
                   'n_stocks': len(mf), 'factors': out}, f, ensure_ascii=False, indent=2)
    logger.info(f"结果已保存: {out_file}")

    # 5. 打印 Top 15 有效因子
    print("\n" + "=" * 65)
    print(f"  全市场因子有效性 Top 15 (共评估 {len(mf)} 只股票)")
    print("=" * 65)
    print(f"{'因子':<22} {'IC_1d':>8} {'IR_1d':>8} {'正占比':>7} {'IC_5d':>8} {'IR_5d':>8}")
    print("-" * 65)
    for r in out[:15]:
        star = ' ★' if r['abs_ic_1d'] >= 0.03 else (' ●' if r['abs_ic_1d'] >= 0.02 else '')
        print(f"{r['factor']:<22} {r['ic_1d']:+8.4f} {r['ir_1d']:+8.4f} {r['positive_1d']:>6.1%} "
              f"{r['ic_5d']:+8.4f} {r['ir_5d']:+8.4f}{star}")

    # 6. 统计
    effective = [r for r in out if r['abs_ic_1d'] >= 0.03]
    moderate = [r for r in out if 0.02 <= r['abs_ic_1d'] < 0.03]
    print(f"\n  ★ 强有效 (|IC|≥0.03): {len(effective)} 个")
    print(f"  ● 中等有效 (0.02≤|IC|<0.03): {len(moderate)} 个")
    print(f"  弱/无效 (|IC|<0.02): {len(out)-len(effective)-len(moderate)} 个")
    print("=" * 65)
    print("  ★=强有效  ●=中等有效  (IC: 信息系数, IR: 信息比率)")


if __name__ == '__main__':
    main()
