"""全市场 AI 选股 — 因子截面打分 + 硬过滤 + GLM 复核

职责:
  - 从全市场 ~5000 只股票的因子快照出发, 用 IC 加权做横截面打分
  - 硬过滤剔除 ST / 涨跌停 / 停牌 (复用 scan_strategies + backtest.engine)
  - GLM 对 Top 候选逐只给置信度 + 理由, 低于阈值剔除 (AI 仅把关, 不重排)
  - 结果写入 ai:screen:latest, 供 ai_loop → ai:decision:latest.candidate_pool → paper_trader

安全边界 (对齐项目惯例):
  - 打分由量化 IC 加权主导, AI 只做质量复核
  - 选股失败/数据过期返回空列表, 不阻断上游闭环
  - 不直接下单, 不修改策略配置

用法:
  python scripts/ai_stock_screener.py --run              # 跑一次全市场选股
  python scripts/ai_stock_screener.py --run --top 10     # 只取 Top 10
  python scripts/ai_stock_screener.py --status           # 读最近一次选股结果
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache
from quant.factor import FactorEngine

logger = logging.getLogger("ai_stock_screener")
cache = create_cache()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVAL_FILE = os.path.join(ROOT, 'data', 'factor_evaluation.json')
SCREEN_KEY = "ai:screen:latest"

# 强有效因子 (与 scan_strategies.STRONG_FACTORS 一致, IC 方向已由评估确定)
# 负 IC 因子: 值越小越好; 正 IC 因子: 值越大越好
STRONG_FACTORS = {
    'pvbeta_20': -1, 'volatility_20': -1, 'pvcorr_10': -1, 'range_pct': -1,
    'volatility_60': -1, 'ret_60': -1, 'volatility_5': -1,
    'gap_pct': 1, 'overnight_ret': 1, 'pvcorr_5': -1,
}

# AI 复核置信度阈值: 低于此值的候选剔除
CONFIDENCE_THRESHOLD = 0.5


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def _load_ic_weights() -> dict:
    """从 factor_evaluation.json 读 IC 强度作为权重 (绝对值, 不含方向)。

    返回 {factor: weight}, weight 已归一化且均为正, 仅表示因子"预测强度"。
    方向 (大值好/小值好) 由 cross_sectional_score 通过 STRONG_FACTORS 单独处理,
    避免方向符号被重复应用。
    """
    if not os.path.exists(EVAL_FILE):
        logger.warning(f"因子评估文件不存在: {EVAL_FILE}, 用等权兜底")
        n = len(STRONG_FACTORS)
        return {f: 1.0 / n for f in STRONG_FACTORS}

    raw = {}
    with open(EVAL_FILE, encoding='utf-8') as f:
        eval_data = json.load(f)
    for item in eval_data.get('factors', []):
        fn = item['factor']
        if fn in STRONG_FACTORS:
            # 用 |IC| 表示强度; ic × direction > 0 才说明 IC 与既定方向一致 (有效)
            ic_dir = item.get('ic_1d', 0) * STRONG_FACTORS[fn]
            if ic_dir > 0:
                raw[fn] = ic_dir  # 正值, 表示有效强度

    if not raw:
        # IC 与方向全不一致, 等权兜底
        n = len(STRONG_FACTORS)
        return {f: 1.0 / n for f in STRONG_FACTORS}

    total_w = sum(raw.values())
    return {k: v / total_w for k, v in raw.items()}


def _latest_factor_row(fdf: pd.DataFrame) -> pd.Series:
    """取一只股票最新一行的因子值 (先按 date 排序, 避免 iloc[-1] 不可靠)。"""
    if fdf is None or fdf.empty:
        return None
    df = fdf.sort_values('date')
    return df.iloc[-1]


def _is_halted(fdf: pd.DataFrame) -> bool:
    """停牌判定: 最新 bar volume==0 或 high==low (零成交/一字零振幅)。"""
    if fdf is None or fdf.empty:
        return True
    df = fdf.sort_values('date')
    last = df.iloc[-1]
    vol = pd.to_numeric(last.get('volume', 0), errors='coerce')
    high = pd.to_numeric(last.get('high', 0), errors='coerce')
    low = pd.to_numeric(last.get('low', 0), errors='coerce')
    if pd.isna(vol) or vol <= 0:
        return True
    if pd.notna(high) and pd.notna(low) and high > 0 and abs(high - low) < 0.01:
        return True
    return False


def _hard_filter(code: str, limit_map: dict, latest_date) -> tuple:
    """单股硬过滤。返回 (通过, 剔除原因)。

    - ST: 名字含 'ST' (复用 scan_strategies 范例, limit_ratio_for 内部也查此键)
    - 涨跌停: 复用 build_limit_map 的 flag, ==1 为涨停封板买不进
    """
    name = cache.get(f'stock:name:{code}') or ''
    if 'ST' in name:
        return False, 'ST'
    flag = limit_map.get(code, {}).get(latest_date, 0)
    if flag == 1:
        return False, '涨停封板'
    return True, ''


def cross_sectional_score(mf: dict, weights: dict) -> pd.DataFrame:
    """全市场横截面 z-score 加权打分。

    打分公式: score = Σ (|w_i| × direction_i × z_i)
      - direction=+1 (值越大越好): z 直接用, 大值得高分
      - direction=-1 (值越小越好): z 取负, 小值得高分
      - |w_i| 是 IC 强度 (权重已归一化)
    这样退市暴跌股 (ret_60 极小、volatility 极大) 不会因为"小值"被误判为高分。

    返回 DataFrame: index=code, columns=['score', 'date'], 按得分降序。
    """
    # 1. 收集每只股票最新一行的因子值 (横截面)
    rows = []
    for code, fdf in mf.items():
        row = _latest_factor_row(fdf)
        if row is None:
            continue
        rec = {'code': code, 'date': str(row.get('date', ''))}
        has_any = False
        for fn in weights:
            if fn in row.index:
                v = pd.to_numeric(row.get(fn), errors='coerce')
                rec[fn] = v
                if pd.notna(v):
                    has_any = True
        if has_any:
            rows.append(rec)

    if not rows:
        return pd.DataFrame(columns=['score', 'date'])

    df = pd.DataFrame(rows)
    df = df.set_index('code')

    # 2. 横截面 z-score × (IC权重 × 方向) 求和
    score = pd.Series(0.0, index=df.index)
    for fn, w in weights.items():
        if fn not in df.columns:
            continue
        direction = STRONG_FACTORS.get(fn, 1)  # +1 大值好, -1 小值好
        col = df[fn]
        mu = col.mean()
        sd = col.std()
        if sd == 0 or pd.isna(sd):
            continue
        z = ((col - mu) / sd).fillna(0)
        score = score + abs(w) * direction * z

    df['score'] = score
    return df[['score', 'date']].sort_values('score', ascending=False)


def ai_review(candidates: list, provider: str) -> dict:
    """GLM 对 Top 候选逐只复核: 给置信度 + 理由。

    策略 (应对 GLM-5.2 推理模型特性):
      - 单批最多复核 20 只 (按 score 降序取头部)
      - 用裸 chat + 直接要求 JSON 数组 (chat_json 的 JSON 指令会触发更多推理, 挤占 token)
      - max_tokens 提到 3000: 推理模型需足够空间走完推理再输出答案
      - 复核失败返回空 dict (保留量化打分, AI 不阻断)
    """
    if not candidates:
        return {}

    # 按 score 降序取头部 20 只 (最值得复核的)
    pool_sorted = sorted(candidates, key=lambda x: -x.get("score", 0))[:20]
    pool = [{
        "code": c["code"],
        "score": round(c["score"], 3),
        "close": c.get("close"),
        "chg5": c.get("chg5"),
    } for c in pool_sorted]

    # 直接给 JSON 数组范例, 不留推理空间; 判断维度明确
    system = (
        "对每只候选股输出买入置信度(0~1)和理由。"
        "直接输出JSON数组,格式[{\"code\":\"600000\",\"confidence\":0.7,\"reason\":\"理由\"}],"
        "不要任何分析、解释、思考过程。"
        "置信度>=0.7强烈推荐, 0.5~0.7可关注, <0.5不建议。"
    )
    user = "候选:" + json.dumps(pool, ensure_ascii=False, default=str)

    try:
        from scripts.llm_client import chat, _extract_json
        r = chat(provider, system, user, temperature=0.1, timeout=90,
                 max_tokens=3000, scene="screen")
        if not r.get("success"):
            logger.info(f"AI 复核降级 (LLM失败): {r.get('error', '')[:80]}")
            return {}
        data = _extract_json(r["text"])
        # 兼容两种返回: 直接 list, 或 {reviews:[...]}
        reviews = data if isinstance(data, list) else (
            data.get("reviews") if isinstance(data, dict) else None)
        if not isinstance(reviews, list):
            logger.info(f"AI 复核降级 (reviews 非列表): {str(r['text'])[:80]}")
            return {}
        out = {}
        for rv in reviews:
            if not isinstance(rv, dict):
                continue
            code = str(rv.get("code", "")).strip()
            if not code:
                continue
            try:
                conf = float(rv.get("confidence", 0))
            except (TypeError, ValueError):
                conf = 0
            conf = max(0.0, min(1.0, conf))  # 钳制到 [0,1]
            out[code] = {"confidence": conf, "reason": str(rv.get("reason", ""))[:100]}
        logger.info(f"AI 复核: 输入{len(pool)}只, 返回{len(out)}只点评")
        return out
    except Exception as e:
        logger.info(f"AI 复核降级 (异常): {str(e)[:80]}")
        return {}


def screen_market(top_n: int = 20, provider: str = "glm") -> dict:
    """全市场选股主流程。返回 {"success", "top", "stats", ...}。

    top: [{"code","score","close","chg5","confidence","reason"}]
    """
    started = _now()

    # 1. 数据新鲜度门禁 (复用统一入口)
    try:
        from scripts.data_freshness import is_data_stale, get_expected_date
        if is_data_stale():
            logger.warning("全市场数据过期, 选股中止 (返回空)")
            return {"success": False, "error": "数据过期", "top": [], "screened_at": started}
        expected_date = get_expected_date()
    except Exception as e:
        logger.warning(f"数据新鲜度检查失败, 保守中止: {e}")
        return {"success": False, "error": f"数据检查异常: {e}", "top": [], "screened_at": started}

    # 2. 加载因子快照 (复用 scan_strategies, 秒级加载 5000+ 只)
    from scripts.scan_strategies import load_factors_for_all, build_limit_map
    fe = FactorEngine(cache=None)
    mf = load_factors_for_all(cache, fe, use_snapshot=True)
    if not mf:
        return {"success": False, "error": "无因子快照, 请先跑 evaluate_factors",
                "top": [], "screened_at": started}
    logger.info(f"加载因子快照: {len(mf)} 只")

    # 3. IC 加权横截面打分
    weights = _load_ic_weights()
    scored = cross_sectional_score(mf, weights)
    if scored.empty:
        return {"success": False, "error": "打分失败 (无有效因子值)",
                "top": [], "screened_at": started}
    logger.info(f"打分完成: {len(scored)} 只, 权重={weights}")

    # 4. 硬过滤 (ST + 涨跌停 + 停牌)
    #    先取最新日期用于涨跌停判定; build_limit_map 需要 close/high/low, mf 里都有
    limit_map = build_limit_map(mf, cache)
    # 用打分最高的若干只的最新日期做兜底 (不同股票最新日可能不同, 取众数)
    latest_dates = [str(d) for d in scored['date'].head(100) if d]
    latest_date = max(set(latest_dates), key=latest_dates.count) if latest_dates else expected_date

    filtered = []
    stats = {"total": len(scored), "filtered_st": 0, "filtered_limit": 0,
             "filtered_halt": 0, "filtered_penny": 0, "filtered_crash": 0}
    # 异常股阈值: 仙股 (close<2元) / 近60日暴跌 (>50% 视为退市/崩盘尾态)
    PENNY_THRESHOLD = 2.0
    CRASH_THRESHOLD = -0.50
    for code, row in scored.iterrows():
        fdf = mf.get(code)
        if _is_halted(fdf):
            stats["filtered_halt"] += 1
            continue
        ok, reason = _hard_filter(code, limit_map, latest_date)
        if not ok:
            if reason == 'ST':
                stats["filtered_st"] += 1
            else:
                stats["filtered_limit"] += 1
            continue
        # 取最新 close / 近5日 / 近60日涨幅 (供异常过滤 + AI 复核 + 输出)
        close = chg5 = ret60 = None
        if fdf is not None and not fdf.empty:
            d = fdf.sort_values('date')
            c = pd.to_numeric(d['close'], errors='coerce').dropna()
            if len(c) >= 6:
                close = float(c.iloc[-1])
                chg5 = round(float((c.iloc[-1] / c.iloc[-6] - 1) * 100), 2)
            if len(c) >= 60:
                ret60 = float(c.iloc[-1] / c.iloc[-60] - 1)
            elif 'ret_60' in d.columns:
                # 因子快照里有 ret_60 因子, 直接用
                r = pd.to_numeric(d['ret_60'], errors='coerce').dropna()
                if not r.empty:
                    ret60 = float(r.iloc[-1])
        # 异常股过滤: 仙股 / 暴跌退市尾态 (兜底, 即使打分有偏差也不让垃圾股进候选)
        if close is not None and close < PENNY_THRESHOLD:
            stats["filtered_penny"] += 1
            continue
        if ret60 is not None and ret60 < CRASH_THRESHOLD:
            stats["filtered_crash"] += 1
            continue
        filtered.append({
            "code": code, "score": float(row['score']),
            "close": close, "chg5": chg5, "ret60": round(ret60 * 100, 2) if ret60 else None,
        })
        # 硬过滤后取 Top N*3 给 AI 复核 (留余量给置信度筛选)
        if len(filtered) >= top_n * 3:
            break

    logger.info(f"硬过滤后: {len(filtered)} 只 (剔除 ST={stats['filtered_st']} "
                f"涨停={stats['filtered_limit']} 停牌={stats['filtered_halt']} "
                f"仙股={stats['filtered_penny']} 暴跌={stats['filtered_crash']})")

    if not filtered:
        return {"success": False, "error": "硬过滤后无候选", "top": [],
                "stats": stats, "screened_at": started}

    # 5. GLM 复核 (AI 仅把关, 不重排)
    reviews = ai_review(filtered, provider)
    if reviews:
        # AI 复核生效: 没被点评的代码给保守值 (低于阈值, 剔除), 不默认通过
        # 安全边界: AI 没看过的票不应自动放行
        for c in filtered:
            rv = reviews.get(c["code"])
            if rv:
                c["confidence"] = rv.get("confidence", 0.0)
                c["reason"] = rv.get("reason", "")
            else:
                c["confidence"] = 0.0
                c["reason"] = "(AI未点评, 保守剔除)"
        # 剔除低置信度
        before = len(filtered)
        filtered = [c for c in filtered if c.get("confidence", 1.0) >= CONFIDENCE_THRESHOLD]
        stats["filtered_low_conf"] = before - len(filtered)
        logger.info(f"AI 复核: {len(reviews)} 只点评, 剔除低置信度 {stats['filtered_low_conf']} 只")
    else:
        # AI 降级: 全部保留, 置信度标记为 None
        for c in filtered:
            c["confidence"] = None
            c["reason"] = "(AI复核降级, 仅用量化打分)"

    # 6. 取 Top N (打分降序)
    top = sorted(filtered, key=lambda x: -x["score"])[:top_n]

    result = {
        "success": True,
        "screened_at": started,
        "finished_at": _now(),
        "provider": provider,
        "n_universe": len(mf),
        "weights": {k: round(v, 4) for k, v in weights.items()},
        "latest_date": latest_date,
        "stats": stats,
        "top": top,
    }
    cache.set(SCREEN_KEY, result)
    return result


def get_status() -> dict:
    return cache.get(SCREEN_KEY) or {"success": False, "error": "暂无选股记录", "top": []}


def main():
    parser = argparse.ArgumentParser(description="全市场 AI 选股")
    parser.add_argument("--run", action="store_true", help="跑一次全市场选股")
    parser.add_argument("--status", action="store_true", help="读最近一次选股结果")
    parser.add_argument("--provider", default="glm")
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.run:
        out = screen_market(top_n=args.top, provider=args.provider)
    else:
        out = get_status()
    print(json.dumps({"success": True, "data": out}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
