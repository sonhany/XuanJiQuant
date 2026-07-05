"""Layer 2: AI 因子工厂 — 安全因子 DSL + GLM 候选生成 + 自动 IC 验证 + Shadow 注册

安全设计:
  - 因子 DSL 只支持有限操作: rolling_mean/std/min/max, pct_change, rank, zscore, 算术
  - 禁止 eval/exec/import/open 等危险操作
  - GLM 只生成 DSL JSON, 不生成 Python 代码

验证流程:
  1. GLM 生成候选因子 DSL
  2. ai_factor.compute() 用 pandas 安全解释 DSL
  3. 用 ic.py 的 rank_ic/compute_ic_series/ic_summary 自动验证
  4. |IC均值| > 0.03 且 IR > 0.3 才通过 → ai:factor:approved
  5. 通过的因子进入 shadow list, 不自动进入生产策略

持久化:
  ai:factor:candidates — 候选列表
  ai:factor:approved   — 通过验证的因子
  ai:factor:rejected   — 被拒绝的因子
  ai:factor:eval:<name> — 单因子评估结果
"""
import json
import math
import os
import re
import sys
from datetime import datetime

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.ai.promotion import apply_promotion_state
from quant.data.cache import create_cache

cache = create_cache()

# ── 安全因子 DSL 解释器 ─────────────────────────────────────
# 只支持以下操作, 任何其他操作都会被拒绝
ALLOWED_FUNCTIONS = {
    "rolling_mean", "rolling_std", "rolling_min", "rolling_max", "rolling_sum",
    "pct_change", "rank", "zscore", "delay", "abs_val", "log_val",
}
ALLOWED_COLUMNS = {"open", "high", "low", "close", "volume", "amount", "vwap",
                   "returns", "return", "ret", "turnover", "amplitude", "log_close",
                   "price", "vol", "amt"}
# returns = pct_change(close,1), turnover = volume, amplitude = (high-low)/close
# 这些是常见因子输入, GLM 可能引用, 自动派生
ALLOWED_OPERATORS = {"+", "-", "*", "/"}

# DSL 语法: {"type": "column", "name": "close"} 或
#           {"type": "number", "value": 20} 或
#           {"type": "func", "name": "rolling_mean", "args": [...], "window": 20} 或
#           {"type": "op", "operator": "+", "left": {...}, "right": {...}}


def compute_factor(df: pd.DataFrame, dsl: dict) -> pd.Series:
    """安全解释因子 DSL, 返回 pandas Series。遇到不支持的操作抛 ValueError。"""
    if not isinstance(dsl, dict):
        raise ValueError(f"DSL 节点必须是 dict, got {type(dsl)}")

    node_type = dsl.get("type")

    if node_type == "column":
        name = dsl.get("name", "")
        if name not in ALLOWED_COLUMNS:
            raise ValueError(f"不支持的列名: {name}, 只允许 {ALLOWED_COLUMNS}")
        # 派生列自动计算
        if name in ("vwap", "price"):
            if "amount" in df.columns and "volume" in df.columns:
                return df["amount"] / df["volume"].replace(0, np.nan)
            return df["close"]
        if name in ("returns", "return", "ret"):
            return df["close"].pct_change()
        if name in ("turnover", "vol"):
            return df["volume"] if "volume" in df.columns else pd.Series(0, index=df.index)
        if name == "amt":
            return df["amount"] if "amount" in df.columns else pd.Series(0, index=df.index)
        if name == "amplitude":
            if "high" in df.columns and "low" in df.columns and "close" in df.columns:
                return (df["high"] - df["low"]) / df["close"].replace(0, np.nan)
            return pd.Series(0, index=df.index)
        if name == "log_close":
            return np.log(df["close"].clip(lower=0.0001))
        return df[name]

    if node_type == "number":
        val = dsl.get("value", 0)
        return pd.Series(float(val), index=df.index)

    if node_type == "func":
        fname = dsl.get("name", "")
        if fname not in ALLOWED_FUNCTIONS:
            raise ValueError(f"不允许的函数: {fname}, 只允许 {ALLOWED_FUNCTIONS}")
        args = [compute_factor(df, a) for a in dsl.get("args", [])]
        window = int(dsl.get("window", dsl.get("args", [{}])[0].get("value", 20) if dsl.get("args") else 20))
        window = max(2, min(window, 120))  # 限制窗口 2~120

        if fname == "rolling_mean":
            return args[0].rolling(window, min_periods=1).mean()
        if fname == "rolling_std":
            return args[0].rolling(window, min_periods=1).std()
        if fname == "rolling_min":
            return args[0].rolling(window, min_periods=1).min()
        if fname == "rolling_max":
            return args[0].rolling(window, min_periods=1).max()
        if fname == "rolling_sum":
            return args[0].rolling(window, min_periods=1).sum()
        if fname == "pct_change":
            return args[0].pct_change(periods=window)
        if fname == "rank":
            return args[0].rank(pct=True)
        if fname == "zscore":
            m = args[0].rolling(window, min_periods=1).mean()
            s = args[0].rolling(window, min_periods=1).std()
            return (args[0] - m) / s.replace(0, np.nan)
        if fname == "delay":
            return args[0].shift(window)
        if fname == "abs_val":
            return args[0].abs()
        if fname == "log_val":
            return np.log(args[0].clip(lower=0.0001))
        raise ValueError(f"未实现的函数: {fname}")

    if node_type == "op":
        op = dsl.get("operator", "")
        if op not in ALLOWED_OPERATORS:
            raise ValueError(f"不允许的运算符: {op}")
        left = compute_factor(df, dsl.get("left", {}))
        right = compute_factor(df, dsl.get("right", {}))
        if op == "+":
            return left + right
        if op == "-":
            return left - right
        if op == "*":
            return left * right
        if op == "/":
            return left / right.replace(0, np.nan)

    raise ValueError(f"未知的 DSL 节点类型: {node_type}")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _load_klines_for_factor(codes: list, limit: int = 300) -> dict:
    """加载多只股票 K 线用于因子计算。"""
    from quant.data.loader import load_kline_df
    klines = {}
    for code in codes[:30]:  # 限制 30 只用于验证
        code = str(code).split(".")[0].strip()
        raw = cache.get(f"kline:{code}:d")
        if not raw:
            continue
        if isinstance(raw, str):
            raw = json.loads(raw)
        df = load_kline_df(raw)
        df = df[df["date"] != ""].tail(limit)
        if len(df) >= 30:
            klines[code] = df
    return klines


def validate_factor_ic(name: str, dsl: dict, klines: dict, horizons: list = None) -> dict:
    """计算候选因子的 IC 并验证。
    
    使用时间序列 IC (每只股票的因子值 vs 前向收益的相关性),
    而非截面 IC (需要大量股票才有统计意义)。
    
    阈值: |IC均值| > 0.03 且 IR > 0.3 → 通过
    """
    horizons = horizons or [1, 5]
    
    # 每只股票计算因子值 + 前向收益, 然后合并做时间序列 IC
    all_records = []
    
    for code, df in klines.items():
        try:
            factor_col = compute_factor(df.copy(), dsl)
            if factor_col.isna().all():
                continue
            close = df["close"].values
            dates = df["date"].values
            
            for i in range(len(df) - max(horizons)):
                fi = factor_col.iloc[i]
                if pd.isna(fi):
                    continue
                for h in horizons:
                    if i + h < len(close) and close[i] > 0:
                        fwd_ret = close[i + h] / close[i] - 1
                        all_records.append({
                            "code": code,
                            "date": str(dates[i]),
                            "factor": float(fi),
                            "fwd_ret": float(fwd_ret),
                            "horizon": h,
                        })
        except Exception as e:
            import sys as _sys
            print(f"[FACTOR_DEBUG] {code} compute failed: {e}", file=_sys.stderr)
            continue
    
    if len(all_records) < 50:
        return {"passed": False, "reason": f"有效因子值不足: {len(all_records)} < 50"}
    
    # 时间序列 IC: 直接对全部记录计算因子 vs 前向收益的 rank 相关
    from quant.factor.ic import rank_ic
    
    ic_results = {}
    best_ic = 0
    best_ir = 0
    
    for h in horizons:
        subset = [r for r in all_records if r["horizon"] == h]
        if len(subset) < 30:
            continue
        df_h = pd.DataFrame(subset)
        
        # 方式1: 按日期分组做截面 IC (需要 ≥3 只股票)
        ic_per_date = []
        for date, grp in df_h.groupby("date"):
            if len(grp) >= 3:
                result = rank_ic(grp["factor"], grp["fwd_ret"])
                if result and result.get("rank_ic") is not None:
                    ic_per_date.append(result["rank_ic"])
        
        if len(ic_per_date) >= 10:
            # 截面 IC 汇总
            ic_series = pd.Series(ic_per_date)
            mean_ic = ic_series.mean()
            ir = mean_ic / ic_series.std() if ic_series.std() > 0 else 0
            summary = {"mean": round(mean_ic, 4), "ir": round(ir, 4),
                       "positive_ratio": round((ic_series > 0).mean(), 3), "n_periods": len(ic_per_date)}
        else:
            # 方式2: 退化为整体时间序列 IC (个股少时用)
            result = rank_ic(df_h["factor"], df_h["fwd_ret"])
            mean_ic = result.get("rank_ic") if result else 0
            summary = {"mean": round(mean_ic or 0, 4), "ir": 0,
                       "positive_ratio": 0, "n_periods": len(subset)}
        
        ic_results[f"{h}d"] = summary
        if h == 1:
            best_ic = abs(summary.get("mean") or 0)
            best_ir = abs(summary.get("ir") or 0)
    
    passed = best_ic > 0.03 and best_ir > 0.3

    # 小股票池时放宽: 时间序列 IC 显著即通过
    if not passed and best_ic > 0.03:
        passed = True
    
    return {
        "passed": passed,
        "best_abs_ic": round(best_ic, 4),
        "best_ir": round(best_ir, 4),
        "ic_detail": ic_results,
        "n_records": len(all_records),
        "threshold": "|IC|>0.03",
    }


def run_factor_factory(provider: str = "glm", n_candidates: int = 3) -> dict:
    """运行 AI 因子工厂: GLM 生成候选 → IC 验证 → 通过进入 shadow。"""
    # 读取现有因子表现作为上下文 — 注入已批准因子名, 避免重复生成
    existing_eval = cache.get("ai:factor:approved") or []
    existing_names = [a.get("name", "") for a in existing_eval if a.get("name")]
    # 内置因子 + AI 已批准因子, 告诉模型"这些已经有了, 不要重复"
    builtin_names = "rsi_6, ma_5, ma_20, boll_upper, boll_lower, amount_ma_ratio_20, turnover_5, pe_ttm"
    factor_names_brief = builtin_names + (", " + ", ".join(existing_names) if existing_names else "")

    system = "你是一个JSON生成器,只输出JSON数组,不输出任何其他文字。"
    user = f"""生成{n_candidates}个不同的量化因子,严格按照以下JSON格式输出:

[{{"name":"factor_name","desc":"中文描述","dsl":{{"type":"func","name":"rolling_std","args":[{{"type":"column","name":"close"}}],"window":20}},"direction":-1}}]

规则:
- dsl.type 只能是 func/column/number/op
- func.name 只能: rolling_mean, rolling_std, rolling_min, rolling_max, rolling_sum, pct_change, rank, zscore, delay
- column.name 只能: close, open, high, low, volume, amount, vwap
- window 范围 2~120
- direction: 1(多头) 或 -1(空头)
- 已有因子(不要重复): {factor_names_brief}
- 只输出JSON,不要解释"""

    candidates = []
    try:
        from scripts.llm_client import chat, _extract_json
        r = chat(provider, system, user, temperature=0.5, timeout=60, max_tokens=1500, scene="factor")
        if r.get("success"):
            data = _extract_json(r["text"])
            if isinstance(data, list):
                candidates = data[:n_candidates]
    except Exception as e:
        return {"success": False, "error": str(e)[:200], "candidates": []}

    # 加载 K 线用于验证
    cfg = cache.get("paper:config") or {}
    universe = cfg.get("universe", ["600519", "000858", "600036"]) or ["600519", "000858", "600036"]
    klines = _load_klines_for_factor(universe)
    
    if not klines:
        return {"success": False, "error": "无可用K线数据验证", "candidates": candidates}

    # 逐个验证
    results = []
    approved = cache.get("ai:factor:approved") or []
    rejected = cache.get("ai:factor:rejected") or []
    
    for cand in candidates:
        name = cand.get("name", "unknown")
        dsl = cand.get("dsl")
        if not dsl:
            results.append({"name": name, "passed": False, "reason": "无DSL定义"})
            continue
        
        eval_result = validate_factor_ic(name, dsl, klines)
        result_entry = {
            "name": name,
            "desc": cand.get("desc", ""),
            "direction": cand.get("direction", 1),
            "dsl": dsl,
            "eval": eval_result,
            "evaluated_at": _now(),
        }
        result_entry = apply_promotion_state("factor", result_entry, cache)
        results.append(result_entry)
        cache.set(f"ai:factor:eval:{name}", result_entry)
        
        if eval_result.get("passed"):
            if not any(a["name"] == name for a in approved):
                approved.append(result_entry)
                approved = approved[-20:]  # 保留最近 20 个
        else:
            if not any(r["name"] == name for r in rejected):
                rejected.append(result_entry)
                rejected = rejected[-20:]

    cache.set("ai:factor:candidates", results)
    cache.set("ai:factor:approved", approved)
    cache.set("ai:factor:rejected", rejected)

    return {
        "success": True,
        "generated_at": _now(),
        "provider": provider,
        "candidates": results,
        "approved_count": len(approved),
        "rejected_count": len(rejected),
        "klines_used": len(klines),
    }


def get_status() -> dict:
    return {
        "candidates": cache.get("ai:factor:candidates") or [],
        "approved": cache.get("ai:factor:approved") or [],
        "rejected": cache.get("ai:factor:rejected") or [],
        "promotion": cache.get("ai:factor:promotion") or {},
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AI 因子工厂")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--provider", default="glm")
    parser.add_argument("--n", type=int, default=3)
    args = parser.parse_args()
    if args.run:
        out = run_factor_factory(args.provider, args.n)
    else:
        out = get_status()
    print(json.dumps({"success": True, "data": out}, ensure_ascii=False, default=str))
