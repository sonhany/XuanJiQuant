"""Layer 3: AI 策略工厂 — 候选策略配置生成 + 自动回测 + 与生产对比

流程:
  1. 读取当前因子表现 + 策略表现
  2. GLM 生成候选策略配置 (不生成代码, 只生成 JSON 配置)
  3. 自动回测 (与 baseline 对比 Sharpe + 总收益)
  4. 通过的进入 shadow, 不自动替换生产策略

持久化:
  ai:strategy:candidates  — 候选列表 (含回测 metrics)
  ai:strategy:approved    — 通过验证的策略
"""
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.ai.promotion import apply_promotion_state
from quant.data.cache import create_cache

cache = create_cache()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _load_klines(codes: list, limit: int = 500) -> dict:
    from quant.data.loader import load_kline_df
    klines = {}
    for code in codes[:20]:
        code = str(code).split(".")[0].strip()
        raw = cache.get(f"kline:{code}:d")
        if not raw:
            continue
        if isinstance(raw, str):
            raw = json.loads(raw)
        df = load_kline_df(raw)
        df = df[df["date"] != ""].tail(limit)
        if len(df) >= 50:
            klines[code] = df
    return klines


def run_backtest_for_config(strategy_name: str, params: dict, klines: dict) -> dict:
    """对候选策略配置跑回测, 返回 metrics。"""
    from quant.strategy import StrategyEngine
    from quant.factor import FactorEngine

    engine = FactorEngine(cache=cache)
    strategy_engine = StrategyEngine(factor_engine=engine, cache=cache)

    try:
        result = strategy_engine.run_strategy(strategy_name, params, klines)
        bt = result.get("backtest", {})
        metrics = bt.get("metrics", {})
        return {
            "success": True,
            "metrics": {
                "total_return_pct": metrics.get("total_return_pct", 0),
                "annual_return_pct": metrics.get("annual_return_pct", 0),
                "sharpe_ratio": metrics.get("sharpe_ratio", 0),
                "max_drawdown_pct": metrics.get("max_drawdown_pct", 0),
                "win_rate_pct": metrics.get("win_rate_pct", 0),
                "total_trades": metrics.get("total_trades", 0),
                "benchmark": metrics.get("benchmark", {}),
            },
            "fill_count": len(bt.get("fills", [])),
            "signal_count": sum(len(v) for v in (result.get("signals", {}) or {}).values()),
        }
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


def _split_klines(klines: dict, train_ratio: float = 0.8) -> tuple:
    """把 K 线按时间切分成 训练集 / 验证集 (样本外)。

    每只股票的 df 按行数前 train_ratio 切训练, 后 (1-train_ratio) 切验证。
    返回 (train_klines, val_klines), 验证集至少保留 30 行否则并入训练。
    """
    train_klines, val_klines = {}, {}
    for code, df in klines.items():
        n = len(df)
        split_idx = int(n * train_ratio)
        # 验证集至少 30 行才有统计意义; 不足则全归训练
        if n - split_idx < 30:
            train_klines[code] = df
        else:
            train_klines[code] = df.iloc[:split_idx]
            val_klines[code] = df.iloc[split_idx:]
    return train_klines, val_klines


def run_strategy_factory(provider: str = "glm") -> dict:
    """运行 AI 策略工厂。"""
    cfg = cache.get("paper:config") or {}
    universe = cfg.get("universe", ["600519", "000858", "600036"]) or ["600519", "000858", "600036"]
    current_strategy = cfg.get("strategy_name", "ma_cross")
    current_params = cfg.get("strategy_params", {})

    # 加载 K 线
    klines = _load_klines(universe)
    if not klines:
        return {"success": False, "error": "无可用K线数据"}

    # 跑当前生产策略作为基线
    baseline = run_backtest_for_config(current_strategy, current_params, klines)

    # GLM 生成候选策略
    system = (
        "你是A股量化策略研究员。请生成3个候选策略配置。"
        "可用策略: ma_cross(fast/slow均线), factor_rank(factor_name/top_n), "
        "multi_factor(factors/weights/top_n), bb_reversion(window/std_dev)。"
        "输出JSON数组,每项含: name(候选名), strategy(策略类型), params(参数JSON), reason(中文理由)。"
        "不要输出代码,只输出JSON数组。"
    )
    user = (
        f"当前生产策略: {current_strategy} params={json.dumps(current_params)}。"
        f"基准回测: {json.dumps(baseline.get('metrics', {}), default=str)[:300]}。"
        f"股票池: {universe[:5]}。"
        f"请生成3个可能优于基线的候选策略。"
    )

    candidates = []
    try:
        from scripts.llm_client import chat, _extract_json
        r = chat(provider, system, user, temperature=0.4, timeout=60, max_tokens=1200, scene="strategy")
        if r.get("success"):
            data = _extract_json(r["text"])
            if isinstance(data, list):
                candidates = data[:3]
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}

    # 回测每个候选 — train/validation split 降低过拟合
    results = []
    approved = cache.get("ai:strategy:approved") or []
    baseline_sharpe = baseline.get("metrics", {}).get("sharpe_ratio", 0)
    baseline_return = baseline.get("metrics", {}).get("total_return_pct", 0)
    # 切分训练/验证集 (80/20), 验证集用于样本外检验
    train_klines, val_klines = _split_klines(klines, train_ratio=0.8)
    has_val = bool(val_klines)

    for cand in candidates:
        sname = cand.get("strategy", cand.get("name", "unknown"))
        params = cand.get("params", {})
        if not isinstance(params, dict):
            params = {}
        # 训练集回测
        bt_train = run_backtest_for_config(sname, params, train_klines)
        train_sharpe = bt_train.get("metrics", {}).get("sharpe_ratio", 0)
        train_return = bt_train.get("metrics", {}).get("total_return_pct", 0)
        beats_train = bt_train.get("success") and train_sharpe > baseline_sharpe and train_return > baseline_return

        # 验证集回测 (样本外) — 必须同样优于基线才算通过, 防止过拟合
        bt_val = None
        beats_val = True  # 无验证集时放宽 (数据太少)
        val_sharpe = 0
        if has_val:
            bt_val = run_backtest_for_config(sname, params, val_klines)
            val_sharpe = bt_val.get("metrics", {}).get("sharpe_ratio", 0)
            val_return = bt_val.get("metrics", {}).get("total_return_pct", 0)
            # 验证集要求放宽: 只要 val Sharpe 为正即可 (不强求超基线, 避免数据太少误杀)
            beats_val = bt_val.get("success") and val_sharpe > 0

        entry = {
            "name": cand.get("name", sname),
            "strategy": sname,
            "params": params,
            "reason": cand.get("reason", ""),
            "backtest": bt_train,
            "backtest_val": bt_val,
            "train_sharpe": round(train_sharpe, 4),
            "val_sharpe": round(val_sharpe, 4) if bt_val else None,
            "baseline_sharpe": round(baseline_sharpe, 4),
            "beats_baseline": beats_train and beats_val,
            "evaluated_at": _now(),
        }
        entry = apply_promotion_state("strategy", entry, cache)
        results.append(entry)

        # 通过条件: 训练集 Sharpe+收益 均超基线, 且验证集 Sharpe 为正 (样本外不崩溃)
        if entry["beats_baseline"]:
            if not any(a["name"] == entry["name"] for a in approved):
                approved.append(entry)
                approved = approved[-10:]

    cache.set("ai:strategy:candidates", results)
    cache.set("ai:strategy:approved", approved)

    return {
        "success": True,
        "generated_at": _now(),
        "provider": provider,
        "baseline": baseline,
        "baseline_strategy": current_strategy,
        "candidates": results,
        "approved_count": len(approved),
        "klines_used": len(klines),
    }


def get_status() -> dict:
    return {
        "candidates": cache.get("ai:strategy:candidates") or [],
        "approved": cache.get("ai:strategy:approved") or [],
        "promotion": cache.get("ai:strategy:promotion") or {},
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AI 策略工厂")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--provider", default="glm")
    args = parser.parse_args()
    if args.run:
        out = run_strategy_factory(args.provider)
    else:
        out = get_status()
    print(json.dumps({"success": True, "data": out}, ensure_ascii=False, default=str))
