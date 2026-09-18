"""全市场因子批量评估 — 用 5207 只股票筛选有效因子

输出:
  1. 每个因子的 IC 均值/IR/正占比 (1日和5日持有期)
  2. 按 |IC| 排序的有效因子榜单
  3. 保存结果到 data/factor_evaluation.json

用法:
  python scripts/evaluate_factors.py              # 原始 IC
  python scripts/evaluate_factors.py --neutralize # 行业+市值中性化 IC
耗时: 约30分钟 (5207只 × 58因子 × 4周期)
"""
import argparse
import json
import logging
import os
import pickle
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache
from quant.data.loader import load_kline_df
from quant.factor import FactorEngine
from quant.factor.technical import TECHNICAL_FACTORS
from quant.factor.price_volume import PRICE_VOLUME_FACTORS
from quant.factor.fundamental import FUNDAMENTAL_FACTORS
from quant.factor.evaluation import (
    build_evaluation_metadata,
    build_factor_forward_frame,
    factor_correlation_top,
    group_and_long_short_returns,
)
from quant.factor.input_contract import governed_daily_bars, load_factor_input_snapshot
from scripts.data_freshness import get_expected_date

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("eval_factors")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_FILE = os.path.join(ROOT, 'data', 'factor_evaluation.json')
OUT_FILE_NEUTRAL = os.path.join(ROOT, 'data', 'factor_evaluation_neutral.json')
# 因子快照缓存: 避免每次评估都重算 5207 只 × 58 因子 (~11分钟)
SNAPSHOT_FILE = os.path.join(ROOT, 'data', 'factor_snapshot.pkl')


def _atomic_pickle(path: str | Path, payload: object) -> None:
    destination = Path(path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f"{destination.name}.{os.getpid()}.{time.time_ns()}.tmp"
    )
    try:
        with temporary.open("wb") as handle:
            pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_json(path: str | Path, payload: dict) -> None:
    destination = Path(path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f"{destination.name}.{os.getpid()}.{time.time_ns()}.tmp"
    )
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def _resolve_output_paths(
    *,
    neutralized: bool,
    generation_dir: str | Path | None = None,
    snapshot_output: str | Path | None = None,
    projection_output: str | Path | None = None,
    evaluation_output: str | Path | None = None,
) -> tuple[Path, Path, Path, bool]:
    configured_generation = generation_dir or os.environ.get(
        "XUANJI_RESEARCH_GENERATION_DIR"
    )
    staging = bool(configured_generation)
    base = Path(configured_generation).resolve() if staging else None
    snapshot = (
        Path(snapshot_output).resolve()
        if snapshot_output is not None
        else base / "factor_snapshot.pkl"
        if base is not None
        else Path(SNAPSHOT_FILE).resolve()
    )
    projection = (
        Path(projection_output).resolve()
        if projection_output is not None
        else base / "factor_snapshot_latest.json"
        if base is not None
        else Path(ROOT, "data", "factor_snapshot_latest.json").resolve()
    )
    evaluation = (
        Path(evaluation_output).resolve()
        if evaluation_output is not None
        else base / "factor_evaluation.json"
        if base is not None
        else Path(OUT_FILE_NEUTRAL if neutralized else OUT_FILE).resolve()
    )
    return snapshot, projection, evaluation, staging


def build_factor_engine(cache):
    """Full-market evaluation must retain the cache used by fundamental factors."""
    return FactorEngine(cache=cache)


def snapshot_has_usable_fundamentals(snapshot: dict) -> bool:
    """Reject date-fresh pickle snapshots that silently omit fundamentals."""
    for frame in (snapshot.get('mf') or {}).values():
        if frame is None or getattr(frame, 'empty', True):
            continue
        for factor in FUNDAMENTAL_FACTORS:
            if factor in frame.columns and frame[factor].notna().any():
                return True
    return False


def snapshot_matches_input(snapshot: dict, input_snapshot) -> bool:
    """A reusable factor artifact is valid only for its exact governed input."""
    return bool(
        snapshot.get("snapshot_id") == input_snapshot.snapshot_id
        and snapshot.get("data_version") == input_snapshot.data_version
        and snapshot.get("universe_version") == input_snapshot.universe_version
    )


def row_snapshot_fundamental_coverage(snapshot: dict) -> dict[str, int]:
    rows = snapshot.get('rows') or []
    return {
        factor: sum(
            1
            for row in rows
            if row.get('factors', {}).get(factor) is not None
        )
        for factor in FUNDAMENTAL_FACTORS
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description='全市场因子批量评估')
    ap.add_argument('--neutralize', action='store_true',
                    help='启用行业+市值中性化后再计算 IC (区分因子纯粹 Alpha)')
    ap.add_argument('--no-cache', action='store_true',
                    help='忽略因子快照，强制重新计算 (数据更新后用)')
    ap.add_argument('--generation-dir', help='研究 generation 暂存目录')
    ap.add_argument('--snapshot-output', help='因子 pickle 快照输出路径')
    ap.add_argument('--projection-output', help='因子轻量截面输出路径')
    ap.add_argument('--evaluation-output', help='因子评估 JSON 输出路径')
    args = ap.parse_args(argv)
    snapshot_path, projection_path, evaluation_path, staging = _resolve_output_paths(
        neutralized=args.neutralize,
        generation_dir=args.generation_dir,
        snapshot_output=args.snapshot_output,
        projection_output=args.projection_output,
        evaluation_output=args.evaluation_output,
    )

    cache = create_cache()
    input_snapshot = load_factor_input_snapshot(
        cache,
        expected_date=get_expected_date(),
        publish_cache=not staging,
    )
    input_metadata = input_snapshot.metadata()
    n_stocks = len(input_snapshot.eligible_codes)
    logger.info(f"=== 全市场因子评估 ({n_stocks} 只股票) ===")
    logger.info(f"中性化: {'启用 (行业+市值)' if args.neutralize else '关闭'}")

    # 1. 计算所有股票的因子 (有快照则直接加载，避免 ~9 分钟重算)
    fe = build_factor_engine(cache)
    mf = {}
    mk = {}
    use_snapshot = not args.no_cache and snapshot_path.exists()
    if use_snapshot:
        t0 = time.time()
        try:
            with snapshot_path.open('rb') as f:
                snap = pickle.load(f)
            if not snapshot_matches_input(snap, input_snapshot):
                raise ValueError("factor snapshot input version mismatch")
            from scripts.scan_strategies import latest_kline_date_from_cache, snapshot_is_fresh
            latest_date = latest_kline_date_from_cache(cache)
            if not snapshot_is_fresh(snap, latest_date):
                raise ValueError(f"stale factor snapshot: snapshot={snap.get('latest_kline_date')} latest={latest_date}")
            if cache.keys('fin:abstract:*') and not snapshot_has_usable_fundamentals(snap):
                raise ValueError("factor snapshot has no usable fundamental values")
            mf = snap['mf']
            mk = snap['mk']
            logger.info(f"从快照加载因子: {len(mf)} 只, {time.time()-t0:.1f}s ({snapshot_path})")
        except Exception as e:
            logger.warning(f"快照加载失败 ({e}), 重新计算")
            use_snapshot = False
    if not use_snapshot:
        keys = [f"kline:{code}:d" for code in input_snapshot.eligible_codes]
        t0 = time.time()
        for i, k in enumerate(keys, 1):
            bars = governed_daily_bars(cache, k.split(':')[1], input_snapshot)
            if not bars:
                continue
            code = k.split(':')[1]
            try:
                df = load_kline_df(bars)
                mf[code] = fe.compute_all(df, code=code)  # 传 code 计算基本面因子
                mk[code] = df
            except Exception as e:
                logger.debug(f"[{code}] 因子计算失败: {e}")
            if i % 500 == 0:
                elapsed = time.time() - t0
                logger.info(f"  因子计算 [{i}/{len(keys)}] ({i/elapsed:.1f}/s)")
        logger.info(f"因子计算完成: {len(mf)} 只, {time.time()-t0:.0f}s")
        # 保存快照供后续评估/扫描复用
        try:
            from scripts.scan_strategies import latest_kline_date_from_cache
            _atomic_pickle(snapshot_path, {
                'mf': mf,
                'mk': mk,
                'saved_at': time.time(),
                'latest_kline_date': latest_kline_date_from_cache(cache),
                'kline_key_count': len(keys),
                **input_metadata,
            })
            logger.info(f"因子快照已保存: {snapshot_path}")
        except Exception as e:
            if staging:
                raise
            logger.warning(f"快照保存失败: {e}")

    # factor_stocks/strategy market scan read the lightweight JSON projection.
    # Keep it coupled to every successful full snapshot load/rebuild so the UI
    # cannot silently fall back to an older cross section.
    try:
        from scripts.gpu_worker import build_factor_snapshot_latest
        projection = build_factor_snapshot_latest(
            source_path=snapshot_path,
            output_path=projection_path,
            update_global_cache=False if staging else None,
        )
        if projection.get("success"):
            logger.info(
                "因子轻量截面已刷新: %s rows, %.2fs",
                projection.get("rows"),
                projection.get("elapsed_seconds", 0),
            )
        else:
            logger.warning("因子轻量截面刷新失败: %s", projection.get("error"))
            if staging:
                raise RuntimeError(
                    f"factor_projection_failed:{projection.get('error') or 'unknown'}"
                )
    except Exception as e:
        if staging:
            raise
        logger.warning("因子轻量截面刷新失败: %s", e)

    # 2. IC 评估 (技术+量价+基本面因子, 1/5/10/20日持有期)
    factors = TECHNICAL_FACTORS + PRICE_VOLUME_FACTORS + FUNDAMENTAL_FACTORS
    fwd_horizons = [1, 5, 10, 20]
    logger.info(f"开始 IC 评估: {len(factors)} 因子 × {len(fwd_horizons)} 周期...")
    t0 = time.time()
    result = fe.evaluate_all(mf, mk, factor_names=factors, fwd_horizons=[1, 5, 10, 20],
                             neutralize=args.neutralize)
    logger.info(f"IC 评估完成: {len(result)} 因子, {time.time()-t0:.0f}s")

    # 3. 整理结果
    out = []
    eval_meta = build_evaluation_metadata(mk, lookback_bars=300, fwd_horizons=fwd_horizons)
    enhanced_window_bars = 20
    logger.info("开始增强指标计算: 窗口=%s bars", enhanced_window_bars)
    forward_frame = build_factor_forward_frame(
        mf,
        mk,
        factors,
        [1],
        tail_rows_per_stock=enhanced_window_bars,
    )
    logger.info("增强指标收益表完成: rows=%s", len(forward_frame))
    corr_top = factor_correlation_top(
        mf,
        factors,
        top_n=3,
        tail_rows_per_stock=1,
    )
    logger.info("增强指标相关性矩阵完成: corr_window=latest")
    for idx, item in enumerate(result, 1):
        fname = item.get('factor_name', '')
        summary = item.get('summary') or {}
        decay = item.get('decay') or {}
        fwd1 = decay.get('1d', {})
        fwd5 = decay.get('5d', {})
        fwd10 = decay.get('10d', {})
        fwd20 = decay.get('20d', {})
        group_metrics = group_and_long_short_returns(
            forward_frame,
            fname,
            horizon=1,
            n_groups=5,
            cost_bps=20.0,
        )
        out.append({
            'factor': fname,
            'ic_1d': round(summary.get('mean', 0), 4),
            'ir_1d': round(summary.get('ir', 0), 4),
            'positive_1d': round(summary.get('positive_ratio', 0), 3),
            'n_periods': summary.get('n_periods', 0),
            'ic_5d': round(fwd5.get('mean', 0), 4),
            'ir_5d': round(fwd5.get('ir', 0), 4),
            'positive_5d': round(fwd5.get('positive_ratio', 0), 3),
            'ic_10d': round(fwd10.get('mean', 0), 4),
            'ir_10d': round(fwd10.get('ir', 0), 4),
            'positive_10d': round(fwd10.get('positive_ratio', 0), 3),
            'ic_20d': round(fwd20.get('mean', 0), 4),
            'ir_20d': round(fwd20.get('ir', 0), 4),
            'positive_20d': round(fwd20.get('positive_ratio', 0), 3),
            'abs_ic_1d': round(abs(summary.get('mean', 0)), 4),
            'abs_ic_5d': round(abs(fwd5.get('mean', 0)), 4),
            'abs_ic_10d': round(abs(fwd10.get('mean', 0)), 4),
            'abs_ic_20d': round(abs(fwd20.get('mean', 0)), 4),
            'group_return': group_metrics.get('groups', {}),
            'long_short': group_metrics.get('long_short', {}),
            'long_short_after_cost': group_metrics.get('long_short_after_cost', {}),
            'turnover': group_metrics.get('turnover', 0),
            'corr_top': corr_top.get(fname, []),
        })
        if idx % 10 == 0:
            logger.info("增强指标进度: %s/%s", idx, len(result))

    # 按 |IC 1d| 降序
    out.sort(key=lambda x: x['abs_ic_1d'], reverse=True)

    # 4. 保存
    _atomic_json(evaluation_path, {
        'evaluated_at': time.strftime('%Y-%m-%d %H:%M'),
        'neutralized': args.neutralize,
        'n_stocks': len(mf),
        'data_start_date': eval_meta.get('data_start_date'),
        'data_end_date': eval_meta.get('data_end_date'),
        'latest_kline_date': eval_meta.get('latest_kline_date'),
        'lookback_bars': eval_meta.get('lookback_bars'),
        'fwd_horizons': eval_meta.get('fwd_horizons'),
        'min_bars_per_stock': eval_meta.get('min_bars_per_stock'),
        'max_bars_per_stock': eval_meta.get('max_bars_per_stock'),
        'cost_model': {'cost_bps': 20.0, 'commission_slippage_estimate': True},
        'enhanced_metrics_window_bars': enhanced_window_bars,
        'correlation_method': 'spearman',
        **input_metadata,
        'factors': out,
    })
    logger.info(f"结果已保存: {evaluation_path}")

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
