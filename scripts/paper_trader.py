"""模拟盘调度器 (Paper Trader) — 日频自动量化交易

设计原则 (与 sync_service.py 风格一致):
  - 长驻 while 循环, 每日到点 (默认 15:05) 跑一次策略
  - 策略出信号 → 与现有持仓比较 → 调用 execution_runner 下单
  - 状态写 SQLite (paper:config / paper:status / paper:log)
  - 与前端 ExecutionPanel 共享同一账户 (execution:state), 互不冲突
  - 纯模拟, 不接真实券商

信号 → 订单规则 (多头 only, 不做空):
  - 最新 signal == 1  → 目标持仓 (按 position_size_pct 算股数), 不足则买入
  - 最新 signal <= 0  → 平仓 (卖出全部)
  - 该 code 无信号     → 不动
  - 总持仓数 ≤ max_positions (满仓则只平不开)

启动:
  python scripts/paper_trader.py            # daemon 模式, 长驻循环
  python scripts/paper_trader.py --once     # 单次执行后退出 (测试/手动触发)
"""
import argparse
import json
import logging
import math
import os
import sys
import time
import uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant.data.cache import create_cache
from quant.data.loader import load_kline_df
from quant.factor import FactorEngine
from quant.strategy import StrategyEngine
from scripts.paper.audit_writer import ensure_schema as ensure_audit_schema, record_run as record_audit_run
from scripts.paper.decision_reader import load_valid_decision
from scripts.paper.order_router import place_paper_order
from scripts.paper.portfolio_rebalancer import execute_target_portfolio
from scripts.paper.pretrade_risk import check_paper_order
# 直接复用执行引擎的下单函数 (共享 execution:state 账户)
from execution_runner import action_place_order, action_positions, action_status

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("paper_trader")

cache = create_cache()
ensure_audit_schema(cache)
engine = FactorEngine(cache=cache)
strategy_engine = StrategyEngine(factor_engine=engine, cache=cache)

CONFIG_KEY = "paper:config"
STATUS_KEY = "paper:status"
LOG_KEY = "paper:log"
LOCK_KEY = "paper:lock"        # 跨进程互斥锁 (daemon 与 run_now 并发保护)
LOCK_TTL = 180                 # 锁过期秒数: 覆盖一次 run_once 最大耗时, 持锁进程崩溃后自动释放
LOG_MAX = 200  # 日志最多保留条数

DEFAULT_CONFIG = {
    "strategy_name": "ma_cross",
    "strategy_params": {"fast": 5, "slow": 20},
    "universe": ["600519", "000858", "600036", "000333", "601318"],  # 白名单兜底, candidate_pool 会动态并入
    "position_size_pct": 0.2,   # 单股最大占总权益比例
    "max_positions": 5,         # 最大持仓只数
    "trade_time": "15:05",      # 每日触发时间 HH:MM
    "enabled": True,            # 默认开启 daemon (全自主: watchdog 保活, 无需手动启动)
    "skip_data_stale": True,    # 数据不新鲜 (最新 K 线 < 今天) 则跳过本轮, 避免基于过期数据下单
    "risk": {
        "kill_switch": False,
        "max_position_pct": 0.2,
        "max_gross_exposure_pct": 95,
        "max_position_count": 10,
        "max_orders_per_run": 20,
        "min_cash_buffer_pct": 2,
        "max_daily_loss_pct": 5,
        "capital_cap": 0,
        "allow_buy_st": False,
        "allow_buy_limit_up": False,
        "allow_sell_limit_down": False,
    },
    "llm": {
        "enabled": True,               # 默认启用 AI 个股复核 (全自主决策)
        "provider": "glm",             # glm(主力) | deepseek | qwen | gemini
        "mode": "review",              # off | review(审核量化信号) | decide(独立决策)
        "timeout": 45,                 # LLM 调用超时秒
        "max_new_positions": 3,        # LLM 每轮最多新增持仓数
        "confidence_threshold": 0.6,   # review 模式下低于此置信度则否决信号
        "interpret_alerts": True,      # 告警加 AI 解读
    },
}


# ─── 配置 / 状态 / 日志 ────────────────────────────────────────
def load_config() -> dict:
    cfg = cache.get(CONFIG_KEY)
    if not cfg:
        cfg = dict(DEFAULT_CONFIG)
        cache.set(CONFIG_KEY, cfg)
    # 兜底缺失字段
    for k, v in DEFAULT_CONFIG.items():
        if isinstance(v, dict):
            cur = cfg.get(k)
            if not isinstance(cur, dict):
                cfg[k] = dict(v)
            else:
                for kk, vv in v.items():
                    cur.setdefault(kk, vv)
        else:
            cfg.setdefault(k, v)
    return cfg


def save_config(cfg: dict):
    cache.set(CONFIG_KEY, cfg)


def load_status() -> dict:
    return cache.get(STATUS_KEY) or {
        "running": False,
        "last_run": None,
        "last_run_date": None,
        "next_run": None,
        "last_result": None,
        "pid": None,
    }


def save_status(s: dict):
    cache.set(STATUS_KEY, s)


def append_log(entry: dict):
    """追加一条运行日志, 保留最近 LOG_MAX 条"""
    logs = cache.get(LOG_KEY) or []
    logs.append(entry)
    logs = logs[-LOG_MAX:]
    cache.set(LOG_KEY, logs)


# ─── 实时进度追踪 (前端轮询读取, 滚动展示) ───────────────────
PROGRESS_KEY = "paper:progress"
PROGRESS_MAX = 80  # 保留最近 80 条进度事件


def _emit_progress(step: int, label: str, status: str, detail: str = ""):
    """写入一个进度事件。status: running/done/error/skip"""
    try:
        events = cache.get(PROGRESS_KEY) or []
        events.append({
            "step": step,
            "time": _now_iso(),
            "label": label,
            "status": status,  # running | done | error | skip
            "detail": detail,
        })
        cache.set(PROGRESS_KEY, events[-PROGRESS_MAX:])
    except Exception as e:
        logger.debug(f"_emit_progress failed (忽略): {e}")


def _clear_progress():
    """运行开始前清除旧进度"""
    try:
        cache.set(PROGRESS_KEY, [])
    except Exception:
        pass


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ─── 跨进程互斥锁 (daemon / run_now 并发保护) ───────────────────
# run_once() 会被两个独立 Python 进程调用: daemon (长驻) 和 run_now (spawnSync 短任务)。
# threading 锁跨进程无效, 这里借 SqliteCache 底层连接 + kv 表主键实现 setnx 语义:
#   - acquire: 先清过期锁, 再 INSERT OR IGNORE; 影响行数==1 即抢占成功
#   - 持锁进程崩溃 → TTL 到期后下次 acquire 自动清理 (与 daemon exit handler 互为兜底)
# 非 SqliteCache (MemoryCache/RedisCache) 无并发进程, 直接放行。
def _lock_conn():
    """返回 cache 底层 sqlite 连接, 非 SqliteCache 返回 None"""
    conn = getattr(cache, "_conn", None)
    if conn is None:
        return None
    db_path = getattr(cache, "_db_path", None)
    if db_path is None:
        return None
    return conn


def acquire_lock() -> bool:
    """尝试抢占 run_once 锁。成功返回 True; 已被占用或后端非 SQLite 返回 False。"""
    conn = _lock_conn()
    if conn is None:
        return True  # 非持久化后端, 无跨进程竞争
    now = time.time()
    lock_val = {"pid": os.getpid(), "time": _now_iso(), "ts": now}
    data = json.dumps(lock_val, ensure_ascii=False, default=str)
    try:
        conn.execute("PRAGMA busy_timeout = 5000")  # 等 5s 而非立刻 SQLITE_BUSY
        # 1. 清理过期锁 (含崩溃进程遗留)
        conn.execute("DELETE FROM kv WHERE key = ? AND exp IS NOT NULL AND exp < ?", (LOCK_KEY, now))
        # 2. 原子抢占: 主键冲突则忽略。INSERT OR IGNORE 影响行数==1 表示抢到
        cur = conn.execute("INSERT OR IGNORE INTO kv (key, value, exp) VALUES (?, ?, ?)", (LOCK_KEY, data, now + LOCK_TTL))
        conn.commit()
        return cur.rowcount == 1
    except Exception as e:
        logger.warning(f"acquire_lock 异常 (拒绝执行): {e}")
        return False


def release_lock():
    """释放 run_once 锁。只删自己持有的, 避免误删他人刚抢到的新锁。"""
    conn = _lock_conn()
    if conn is None:
        return
    try:
        # 仅当 value 里的 pid == 当前 pid 才删 (TTL 兜底下, 即使这里漏删也无害)
        conn.execute("PRAGMA busy_timeout = 5000")
        row = conn.execute("SELECT value FROM kv WHERE key = ?", (LOCK_KEY,)).fetchone()
        if row:
            try:
                holder = json.loads(row[0])
                if isinstance(holder, dict) and holder.get("pid") == os.getpid():
                    conn.execute("DELETE FROM kv WHERE key = ?", (LOCK_KEY,))
                    conn.commit()
            except (json.JSONDecodeError, TypeError):
                pass
    except Exception as e:
        logger.warning(f"release_lock 异常 (忽略): {e}")


# ─── K 线加载 (参照 strategy_runner._load_klines) ─────────────
def load_klines(codes: list) -> dict:
    klines_dict = {}
    for raw_code in codes:
        code = str(raw_code).split(".")[0].strip()
        raw = cache.get(f"kline:{code}:d")
        if not raw:
            continue
        if isinstance(raw, str):
            raw = json.loads(raw)
        df = load_kline_df(raw)
        df = df[df["date"] != ""]
        if not df.empty:
            klines_dict[code] = df
    return klines_dict


def _last_close(klines_dict: dict, code: str) -> float:
    """取某只股票最新收盘价 (来自已加载 K 线)"""
    df = klines_dict.get(code)
    if df is None or df.empty:
        return 0.0
    try:
        last = float(df["close"].iloc[-1])
        if math.isnan(last):
            return 0.0
        return last
    except Exception:
        return 0.0


def _latest_data_date(klines_dict: dict):
    """返回所有已加载 K 线里最新的日期 (字符串, 如 '2026-06-25'); 无数据返回 None"""
    latest = None
    for df in klines_dict.values():
        if df is None or df.empty:
            continue
        try:
            d = str(df["date"].iloc[-1]).strip()
        except Exception:
            continue
        if d and (latest is None or d > latest):
            latest = d
    return latest


def _is_trading_day() -> bool:
    """交易日判断: 优先用从K线推导的交易日历，fallback 用 weekday。"""
    try:
        from scripts.trading_calendar import is_trade_date
        return is_trade_date(datetime.now().strftime("%Y%m%d"))
    except Exception:
        return datetime.now().weekday() < 5


def _decision_key(date: str, code: str, direction: str) -> str:
    return f"paper:decision:{date}:{code}:{direction}"


def _decision_done(date: str, code: str, direction: str) -> bool:
    return bool(cache.get(_decision_key(date, code, direction)))


def _mark_decision(date: str, code: str, direction: str, payload: dict):
    cache.set(_decision_key(date, code, direction), payload, ttl=7 * 86400)


def _risk_reject(code: str, direction: str, qty: int, price: float, summary: dict, reason: str, detail: str):
    item = {"code": code, "direction": direction, "qty": int(qty), "reason": reason, "detail": detail, "time": _now_iso()}
    summary.setdefault("risk_rejections", []).append(item)
    summary.setdefault("skipped_orders", []).append(item)
    logger.info(f"风控拒单 {code} {direction} {qty}: {reason} {detail}")
    return False


def _pre_trade_check(code: str, direction: str, qty: int, price: float, equity: float,
                     pos_map: dict, cfg: dict, summary: dict) -> bool:
    """模拟盘事前风控。只裁剪/拒绝纸面订单，不改变执行层 API。"""
    status = action_status()
    status_data = status.get("data", status) if isinstance(status, dict) else status
    ok, result = check_paper_order(
        cache,
        code=code,
        direction=direction,
        qty=qty,
        price=price,
        equity=equity,
        pos_map=pos_map,
        status_data=status_data,
        cfg=cfg,
        summary=summary,
    )
    if not ok:
        logger.info(f"风控网关拒单 {code} {direction} {qty}: {result.get('reason')}")
    return ok

    # Legacy checks below are intentionally bypassed by the independent risk
    # gateway above. They are left temporarily as a reference while the sandbox
    # split is stabilized.
    risk = cfg.get("risk") or {}
    if qty <= 0:
        return False
    max_orders = int(risk.get("max_orders_per_run", 20))
    attempted = len(summary.get("orders", [])) + len(summary.get("risk_rejections", []))
    if attempted >= max_orders:
        return _risk_reject(code, direction, qty, price, summary, "max_orders_per_run", f"本轮订单上限 {max_orders}")

    if price <= 0 or equity <= 0:
        return _risk_reject(code, direction, qty, price, summary, "invalid_price_or_equity", "价格或权益无效")

    pos = pos_map.get(code)
    current_mv = float(pos.get("market_value", 0)) if pos else 0.0
    delta_mv = qty * price * (1 if direction == "buy" else -1)
    projected_mv = max(0.0, current_mv + delta_mv)
    max_pos_pct = float(risk.get("max_position_pct", cfg.get("position_size_pct", 0.2)))
    if direction == "buy" and projected_mv / equity * 100 > max_pos_pct * 100 + 1e-6:
        return _risk_reject(code, direction, qty, price, summary, "max_position_pct", f"单票目标占比 {projected_mv/equity*100:.1f}% > {max_pos_pct*100:.1f}%")

    max_count = int(risk.get("max_position_count", risk.get("max_positions", 10)))
    current_codes = {c for c, p in pos_map.items() if int(p.get("quantity", 0)) > 0}
    projected_codes = set(current_codes)
    if direction == "buy":
        projected_codes.add(code)
    elif projected_mv <= 0 and code in projected_codes:
        projected_codes.remove(code)
    if len(projected_codes) > max_count:
        return _risk_reject(code, direction, qty, price, summary, "max_position_count", f"持仓数 {len(projected_codes)} > {max_count}")

    status = action_status()
    status_data = status.get("data", status) if isinstance(status, dict) else status
    cash = float(status_data.get("cash", 0))
    total_mv = sum(float(p.get("market_value", 0)) for p in pos_map.values())
    projected_gross = max(0.0, total_mv + delta_mv)
    max_gross = float(risk.get("max_gross_exposure_pct", 95))
    if direction == "buy" and projected_gross / equity * 100 > max_gross + 1e-6:
        return _risk_reject(code, direction, qty, price, summary, "max_gross_exposure_pct", f"总暴露 {projected_gross/equity*100:.1f}% > {max_gross:.1f}%")

    min_cash_pct = float(risk.get("min_cash_buffer_pct", 2))
    if direction == "buy" and (cash - qty * price) / equity * 100 < min_cash_pct - 1e-6:
        return _risk_reject(code, direction, qty, price, summary, "min_cash_buffer_pct", f"现金缓冲低于 {min_cash_pct:.1f}%")

    objective = (summary.get("decision") or {}).get("objective") or {}
    if direction == "buy" and objective.get("risk_mode") in ("no_new_position", "de_risk"):
        return _risk_reject(code, direction, qty, price, summary, "objective_risk_mode", f"目标风控模式 {objective.get('risk_mode')} 禁止新增买入")

    max_turnover = float(risk.get("max_daily_turnover_pct", 0) or 0)
    if max_turnover > 0:
        attempted_notional = sum(float(o.get("qty", 0)) * price for o in summary.get("orders", []) if o.get("success"))
        projected_turnover = (attempted_notional + qty * price) / equity * 100
        if projected_turnover > max_turnover + 1e-6:
            return _risk_reject(code, direction, qty, price, summary, "max_daily_turnover_pct", f"本轮换手 {projected_turnover:.1f}% > {max_turnover:.1f}%")
    return True


def _normalized_target_weights(decision: dict, cfg: dict) -> list:
    """读取并裁剪目标权重。权重为 0~1 小数。"""
    risk = cfg.get("risk") or {}
    max_weight = float(risk.get("max_position_pct", cfg.get("position_size_pct", 0.2)) or 0.2)
    max_gross = float(risk.get("max_gross_exposure_pct", 95) or 95) / 100
    max_count = int(risk.get("max_position_count", cfg.get("max_positions", 5)) or 5)
    rows = decision.get("target_weights") or []
    out, total, seen = [], 0.0, set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code", "")).split(".")[0].strip()
        if not code or code in seen:
            continue
        try:
            weight = float(row.get("target_weight", 0) or 0)
        except Exception:
            continue
        weight = max(0.0, min(max_weight, weight))
        if total + weight > max_gross:
            weight = max(0.0, max_gross - total)
        if weight <= 0:
            continue
        out.append({"code": code, "target_weight": weight, "confidence": row.get("confidence"), "reason": row.get("reason", "")})
        total += weight
        seen.add(code)
        if len(out) >= max_count:
            break
    return out


def _execute_target_portfolio(target_weights: list, klines_dict: dict, pos_map: dict, equity: float, cfg: dict, summary: dict) -> bool:
    """按 AI 目标权重调仓。返回 True 表示已进入目标组合模式并完成处理。"""
    return execute_target_portfolio(
        target_weights=target_weights,
        klines_dict=klines_dict,
        pos_map=pos_map,
        equity=equity,
        cfg=cfg,
        summary=summary,
        last_close_fn=_last_close,
        pretrade_check_fn=lambda code, direction, qty, price: _pre_trade_check(
            code, direction, qty, price, equity, pos_map, cfg, summary
        ),
        place_fn=lambda code, direction, qty: _place(code, direction, qty, summary),
    )

    # Legacy rebalancer below is bypassed by scripts.paper.portfolio_rebalancer.
    if not target_weights:
        return False
    weight_map = {x["code"]: float(x["target_weight"]) for x in target_weights}
    target_codes = set(weight_map)
    current_codes = {c for c, p in pos_map.items() if int(p.get("quantity", 0) or 0) > 0}
    all_codes = sorted(target_codes | current_codes)
    orders = []
    for code in all_codes:
        pos = pos_map.get(code)
        pos_qty = int(pos.get("quantity", 0)) if pos else 0
        price = float(pos.get("current_price") or pos.get("avg_price") or 0) if pos else 0.0
        if price <= 0:
            price = _last_close(klines_dict, code)
        if price <= 0:
            summary.setdefault("skipped_orders", []).append({"code": code, "reason": "no_price", "time": _now_iso()})
            continue
        target_weight = weight_map.get(code, 0.0)
        target_qty = int(equity * target_weight / price / 100) * 100 if target_weight > 0 else 0
        if target_weight > 0 and target_qty <= 0:
            target_qty = 100
        delta = target_qty - pos_qty
        if delta < 0:
            orders.append((0, code, "sell", abs(delta), price, target_weight))
        elif delta > 0:
            orders.append((1, code, "buy", delta, price, target_weight))
    orders.sort(key=lambda x: x[0])  # 先卖后买, 释放现金
    summary["portfolio_mode"] = "target_weights"
    summary["target_weights"] = target_weights
    summary["target_vs_actual"] = []
    for _, code, direction, qty, price, target_weight in orders:
        if _pre_trade_check(code, direction, qty, price, equity, pos_map, cfg, summary):
            ok = _place(code, direction, qty, summary)
            if ok:
                summary["signals"].append({"code": code, "signal": 1 if target_weight > 0 else 0, "action": f"target_{direction}", "qty": qty, "price": price, "target_weight": round(target_weight, 4)})
        summary["target_vs_actual"].append({"code": code, "direction": direction, "qty": qty, "price": price, "target_weight": round(target_weight, 4)})
    summary["order_count"] = len(summary["orders"])
    return True


# ─── 核心: 单次执行 ────────────────────────────────────────────
def run_once(source: str = "manual") -> dict:
    """跑一次策略并下单, 返回执行摘要。source 标记触发来源, 用于审计。"""
    cfg = load_config()
    name = cfg["strategy_name"]
    params = cfg["strategy_params"] or {}
    universe = [str(c).split(".")[0].strip() for c in cfg["universe"] if c]

    started = _now_iso()
    summary = {
        "run_id": f"paper-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}",
        "started_at": started,
        "trigger_source": source,
        "strategy": name,
        "universe_size": len(universe),
        "signals": [],
        "orders": [],
        "risk_checks": [],
        "risk_rejections": [],
        "skipped_orders": [],
        "errors": [],
    }

    # 0. 跨进程互斥锁: daemon 与 run_now 并发时只让一个进入, 防止重复下单
    if not acquire_lock():
        msg = f"另一进程正在执行 run_once (锁 {LOCK_KEY} 被占用), 跳过本轮"
        logger.warning(msg)
        summary["skipped"] = True
        summary["skip_reason"] = "locked"
        summary["errors"].append(msg)
        _emit_progress(0, "启动", "skip", "锁被占用,跳过本轮")
        _finish(summary, cfg)
        return summary

    _clear_progress()
    _emit_progress(0, "启动", "running", f"策略={name} 股票池={len(universe)}只")

    # 0.5 读决策层统一输出 (ai_loop → ai:decision:latest)
    # 决策必须满足 quant.ai.contracts 的标准协议, 且高风险交易必须通过 verifier。
    decision, decision_errors = load_valid_decision(cache, require_verifier=True)
    if decision_errors:
        msg = "; ".join(decision_errors)
        logger.info(f"AI决策不可执行: {msg}")
        summary["skipped"] = True
        summary["skip_reason"] = "decision_invalid"
        summary["decision"] = decision
        summary["errors"].append(msg)
        _emit_progress(0, "启动", "skip", "AI决策协议/验证未通过")
        _finish(summary, cfg)
        release_lock()
        return summary
    # 如果决策层判定 trade_policy != normal, 执行层尊重决策, 直接跳过交易。
    decision_policy = decision.get("trade_policy")
    if decision_policy and decision_policy != "normal":
        msg = f"决策层策略={decision_policy}, 执行层跳过交易 (决策时间: {decision.get('generated_at','?')})"
        logger.info(msg)
        summary["skipped"] = True
        summary["skip_reason"] = f"decision_{decision_policy}"
        summary["decision"] = decision
        summary["errors"].append(msg)
        _emit_progress(0, "启动", "skip", f"决策层策略={decision_policy}, 跳过")
        _finish(summary, cfg)
        release_lock()
        return summary
    summary["decision"] = decision

    try:
        # 0.6 全市场选股/目标组合注入: 把 candidate_pool 与 target_weights 并入当次 universe。
        # 必须在 load_klines 之前, 否则选股代码无 K 线, _last_close 拿不到价格会跳过。
        target_codes = [str(x.get("code", "")).split(".")[0].strip() for x in (decision.get("target_weights") or []) if isinstance(x, dict)]
        inject_pool = list(dict.fromkeys((decision.get("candidate_pool") or []) + target_codes))
        extra_pool = [c for c in inject_pool if c and c not in universe]
        if extra_pool:
            universe = universe + extra_pool
            logger.info(f"[AI注入] candidate/target {len(extra_pool)} 只并入 universe (本次内存态)")

        # 1. 加载 K 线
        _emit_progress(1, "加载K线数据", "running", f"加载 {len(universe)} 只股票...")
        klines_dict = load_klines(universe)
        if not klines_dict:
            summary["errors"].append("无可用 K 线数据, 请先更新行情")
            _emit_progress(1, "加载K线数据", "error", "无可用数据")
            _finish(summary, cfg)
            return summary
        summary["stocks_with_data"] = len(klines_dict)
        _emit_progress(1, "加载K线数据", "done", f"{len(klines_dict)}只股票有数据")

        # 1b. 数据新鲜度检查 — 统一入口
        if cfg.get("skip_data_stale", True):
            from scripts.data_freshness import is_data_stale, get_expected_date
            latest_date = _latest_data_date(klines_dict)
            summary["data_date"] = latest_date
            expected_date = get_expected_date()
            if latest_date is None:
                msg = "K 线无有效日期, 跳过 (数据异常)"
                logger.warning(msg)
                summary["skipped"] = True
                summary["skip_reason"] = "no_date"
                summary["errors"].append(msg)
                _finish(summary, cfg)
                return summary
            if latest_date < expected_date:
                # 数据过期: 自动补数再重试一次
                _emit_progress(2, "数据检查", "running",
                               f"数据过期 {latest_date} < {expected_date}, 自动补数...")
                try:
                    from scripts.daily_update import incremental_klines
                    codes = [str(c).split(".")[0].strip() for c in cfg.get("universe", []) if c]
                    incremental_klines(codes, cache)
                    # 重新加载 K 线
                    klines_dict = load_klines([str(c).split(".")[0].strip() for c in cfg.get("universe", []) if c])
                    latest_date = _latest_data_date(klines_dict)
                    summary["data_date"] = latest_date
                except Exception as e:
                    logger.warning(f"自动补数失败: {e}")

                if latest_date is None or latest_date < expected_date:
                    msg = f"数据仍过期: 最新 {latest_date} < 预期 {expected_date}, 补数后仍未更新, 跳过"
                    logger.info(msg)
                    summary["skipped"] = True
                    summary["skip_reason"] = "data_stale_or_non_trading_day"
                    summary["data_date"] = latest_date
                    _emit_progress(2, "数据检查", "skip", f"补数后仍过期 {latest_date} < {expected_date}")
                    _finish(summary, cfg)
                    return summary
                else:
                    _emit_progress(2, "数据检查", "done", f"自动补数成功, 最新 {latest_date}")

        _emit_progress(2, "数据检查", "done", f"最新数据 {summary.get('data_date', 'N/A')}")

        # 2. 跑策略出信号
        _emit_progress(3, "策略计算", "running", f"运行 {name} 策略...")
        try:
            result = strategy_engine.run_strategy(name, params, klines_dict)
        except Exception as e:
            summary["errors"].append(f"策略执行失败: {e}")
            _emit_progress(3, "策略计算", "error", str(e)[:80])
            _finish(summary, cfg)
            return summary
        signals = result.get("signals", {}) or {}
        signal_count = sum(1 for sl in signals.values() if sl)
        _emit_progress(3, "策略计算", "done", f"{signal_count} 只股票有信号")

        # 3. 取每只股票的最新信号 (列表最后一项 = 当前目标方向)
        latest = {}  # code -> (signal, score)
        for code, sig_list in signals.items():
            if not sig_list:
                continue
            last = sig_list[-1]
            latest[code] = (int(last.get("signal", 0)), float(last.get("score", 0) or 0))

        # 4. 取当前持仓与权益 (提前到 LLM 层之前, LLM 上下文需要)
        pos_resp = action_positions()
        positions = pos_resp.get("data", []) if isinstance(pos_resp, dict) else pos_resp
        pos_map = {p["code"]: p for p in (positions or [])}
        status = action_status()
        status_data = status.get("data", status) if isinstance(status, dict) else status
        equity = float(status_data.get("total_equity", 1_000_000))
        pct = float(cfg.get("position_size_pct", 0.2))

        # 4.5 AI 目标组合优先: 若 ai_loop 已生成 target_weights, 直接按目标权重调仓。
        target_weights = _normalized_target_weights(decision, cfg)
        if target_weights:
            _emit_progress(4, "目标组合执行", "running", f"目标权重 {len(target_weights)} 只")
            summary["objective"] = decision.get("objective")
            summary["portfolio_plan_id"] = decision.get("portfolio_plan_id")
            handled = _execute_target_portfolio(target_weights, klines_dict, pos_map, equity, cfg, summary)
            if handled:
                ok_count = len([o for o in summary["orders"] if o.get("success")])
                rej_count = len(summary.get("risk_rejections", []))
                _emit_progress(5, "目标组合风控+下单", "done", f"成交{ok_count}笔 拒单{rej_count}笔")
                _finish(summary, cfg)
                _emit_progress(8, "完成", "done", f"目标组合下单{summary.get('order_count', 0)}")
                return summary

        # 5. 计算目标多头池 (受 max_positions 约束)
        desired_long = [c for c, (sig, _) in latest.items() if sig >= 1]
        # 按 score 降序优先排 (score 越大越优先), 无 score 则保持原序
        desired_long.sort(key=lambda c: latest[c][1], reverse=True)

        # 5.5 全市场选股优先: 若决策层有 candidate_pool, 用它直接驱动买入池
        # (AI 选股 = IC 加权打分 + GLM 复核, 可靠性高于 ma_cross 单策略信号)
        external_pool = decision.get("candidate_pool") or []
        if external_pool:
            valid_pool = [c for c in external_pool if _last_close(klines_dict, c) > 0]
            if valid_pool:
                desired_long = valid_pool
                summary["candidate_pool"] = valid_pool
                _emit_progress(3, "全市场选股", "done",
                               f"AI 选股注入 {len(valid_pool)} 只: {','.join(valid_pool[:3])}")
            else:
                summary["candidate_pool"] = []
        max_pos = int(cfg.get("max_positions", 5))

        # 6. LLM 个股级决策增强 (可选, 失败静默降级为纯量化)
        # 注: 宏观 trade_policy 已在 step 0.5 由决策层(ai_loop)判定并过滤。
        #     这里只做个股级 buy/hold/sell 决策 (review/decide 模式),
        #     与 operator 的宏观策略互补, 不重复。
        llm_result = None
        llm_cfg = cfg.get("llm", {})
        if llm_cfg.get("enabled") and llm_cfg.get("mode", "off") != "off":
            from scripts.llm_client import get_provider_label
            provider_label = get_provider_label(llm_cfg.get("provider", "glm"))
            _emit_progress(4, f"AI决策({provider_label})", "running",
                           f"模式={llm_cfg.get('mode')} 正在分析...")
            context = _build_market_context(klines_dict, latest, pos_map, equity, cfg)
            llm_result = _llm_decide(context, cfg, latest, klines_dict)
            if llm_result.get("success"):
                original_desired = list(desired_long)
                desired_long = _apply_llm_decisions(desired_long, latest, llm_result, cfg)
                # decide 模式: 如果 LLM 有 buy 建议, 即使量化信号为空也用 LLM 的
                if not desired_long and llm_result.get("mode") == "decide":
                    universe_codes = set(latest.keys())
                    threshold = float(llm_cfg.get("confidence_threshold", 0.4))
                    llm_buys = []
                    for d in llm_result.get("decisions", []):
                        if not isinstance(d, dict): continue
                        code = str(d.get("code", "")).strip()
                        action = str(d.get("action", "")).lower()
                        raw_conf = d.get("confidence", None)
                        conf = float(raw_conf) if raw_conf is not None else 1.0
                        if action == "buy" and code in universe_codes and conf >= threshold:
                            llm_buys.append(code)
                    if llm_buys:
                        desired_long = llm_buys[:int(cfg.get("max_positions", 5))]
                # 如果仍然为空, 记录原因
                if not desired_long and original_desired:
                    desired_long = original_desired
                    _emit_progress(4, f"AI决策({provider_label})", "done",
                                   f"{len(llm_result.get('decisions',[]))}个建议, 无buy→用量化信号")
                elif not desired_long:
                    _emit_progress(4, f"AI决策({provider_label})", "done",
                                   f"{len(llm_result.get('decisions',[]))}个建议, AI+量化均无买入信号")
                else:
                    _emit_progress(4, f"AI决策({provider_label})", "done",
                                   f"买入{len(desired_long)}只: {','.join(desired_long[:3])}")
            else:
                summary["errors"].append(f"LLM 降级: {llm_result.get('error', '未知')}")
                _emit_progress(4, f"AI决策({provider_label})", "error",
                               f"降级: {llm_result.get('error', '未知')[:60]}")
        summary["llm"] = _summarize_llm(llm_result, llm_cfg)

        will_hold = set(desired_long[:max_pos])

        # 7. 生成并执行订单
        _emit_progress(5, "风控+下单", "running", f"目标持仓 {len(will_hold)} 只")
        all_codes = set(list(latest.keys()) + list(pos_map.keys()))
        for code in sorted(all_codes):
            sig, score = latest.get(code, (None, 0))
            pos = pos_map.get(code)
            pos_qty = int(pos["quantity"]) if pos else 0
            price = float(pos["current_price"]) if pos and pos.get("current_price") else _last_close(klines_dict, code)
            if price <= 0:
                continue

            if code in will_hold:
                # 目标多头: 算目标股数, 差额补足
                target_qty = int(equity * pct / price / 100) * 100
                target_qty = max(target_qty, 100)
                if pos_qty < target_qty:
                    delta = target_qty - pos_qty
                    order = False
                    if _pre_trade_check(code, "buy", delta, price, equity, pos_map, cfg, summary):
                        order = _place(code, "buy", delta, summary)
                    if order:
                        summary["signals"].append({"code": code, "signal": 1, "action": "buy", "qty": delta, "price": price, "score": round(score, 3)})
                elif pos_qty > target_qty:
                    delta = pos_qty - target_qty
                    order = False
                    if _pre_trade_check(code, "sell", delta, price, equity, pos_map, cfg, summary):
                        order = _place(code, "sell", delta, summary)
                    if order:
                        summary["signals"].append({"code": code, "signal": 1, "action": "sell_down", "qty": delta, "price": price, "score": round(score, 3)})
            else:
                # 平仓: signal <= 0 或不在多头池
                if pos_qty > 0:
                    order = False
                    if _pre_trade_check(code, "sell", pos_qty, price, equity, pos_map, cfg, summary):
                        order = _place(code, "sell", pos_qty, summary)
                    if order:
                        action_label = "exit_on_signal" if sig is not None else "exit_overflow"
                        summary["signals"].append({"code": code, "signal": sig if sig is not None else 0, "action": action_label, "qty": pos_qty, "price": price})

        summary["order_count"] = len(summary["orders"])
        ok_count = len([o for o in summary["orders"] if o.get("success")])
        rej_count = len(summary.get("risk_rejections", []))
        _emit_progress(5, "风控+下单", "done", f"成交{ok_count}笔 拒单{rej_count}笔")
        _finish(summary, cfg)
        _emit_progress(8, "完成", "done", f"下单{summary['order_count']} 信号{len(summary['signals'])}")
        return summary
    finally:
        # 无论正常返回、异常、还是提前跳过, 都释放锁 (仅删自己持有的)
        release_lock()


def _place(code: str, direction: str, qty: int, summary: dict) -> bool:
    """调用 execution_runner 下市价单, 成功即成交。带每日幂等保护。"""
    trade_date = datetime.now().strftime("%Y%m%d")
    return place_paper_order(
        cache,
        code=code,
        direction=direction,
        qty=qty,
        summary=summary,
        action_place_order=action_place_order,
        decision_done=_decision_done,
        mark_decision=_mark_decision,
        trade_date=trade_date,
        now_fn=_now_iso,
    )

    # Legacy router below is bypassed by scripts.paper.order_router.
    if qty <= 0:
        return False
    trade_date = datetime.now().strftime("%Y%m%d")
    if _decision_done(trade_date, code, direction):
        item = {"code": code, "direction": direction, "qty": int(qty), "reason": "idempotent_skip", "time": _now_iso()}
        summary.setdefault("skipped_orders", []).append(item)
        summary["orders"].append({**item, "success": False, "error": "同日同股票同方向已处理，跳过重复下单"})
        return False
    try:
        r = action_place_order({"code": code, "direction": direction, "quantity": int(qty), "order_type": "market", "source": "paper"})
        ok = bool(r.get("success"))
        order_data = (r.get("data") or {}).get("order") if isinstance(r.get("data"), dict) else None
        rec = {
            "code": code, "direction": direction, "qty": int(qty),
            "success": ok,
            "error": r.get("error") if not ok else None,
            "reason": r.get("reason") if not ok else None,
            "order_id": order_data.get("id") if isinstance(order_data, dict) else None,
            "price_source": order_data.get("price_source") if isinstance(order_data, dict) else None,
            "time": _now_iso(),
        }
        summary["orders"].append(rec)
        _mark_decision(trade_date, code, direction, rec)
        return ok
    except Exception as e:
        summary["errors"].append(f"{code} {direction} {qty} 下单异常: {e}")
        summary["orders"].append({"code": code, "direction": direction, "qty": int(qty), "success": False, "error": str(e), "time": _now_iso()})
        return False


# ─── LLM 决策增强层 ─────────────────────────────────────────
def _build_market_context(klines_dict: dict, latest: dict, pos_map: dict,
                          equity: float, cfg: dict) -> str:
    """构建给 LLM 的结构化市场上下文 (纯文本, 不泄露系统内部细节)。"""
    lines = []
    # 账户
    cash = equity
    holdings = []
    for code, p in pos_map.items():
        qty = int(p.get("quantity", 0))
        if qty > 0:
            avg = float(p.get("avg_price", 0))
            cash -= qty * avg
            holdings.append(f"{code} {qty}股 成本{avg:.2f}")
    lines.append(f"【账户】总权益: ¥{equity:,.0f} | 现金: ¥{cash:,.0f} | 持仓: {len(holdings)}只")
    if holdings:
        lines.append("【当前持仓】" + " | ".join(holdings[:8]))

    # 候选股票池 + 量化信号 + 近期涨跌
    sig_lines = []
    for code, (sig, score) in sorted(latest.items()):
        df = klines_dict.get(code)
        ret5 = ""
        if df is not None and len(df) >= 2:
            closes = df["close"].iloc[-6:].values if len(df) >= 6 else df["close"].values
            if len(closes) >= 2 and closes[-2] > 0:
                ret5 = f" 近{min(5, len(closes) - 1)}日{(closes[-1] / closes[0] - 1) * 100:+.1f}%"
        action = "做多" if sig >= 1 else ("平仓" if sig <= 0 else "观望")
        sig_lines.append(f"  {code} signal={action} score={score:.2f}{ret5}")
    if sig_lines:
        lines.append("【候选股票池】(量化策略信号)")
        lines.extend(sig_lines[:15])

    # 风控约束
    risk = cfg.get("risk", {})
    lines.append(f"【风控约束】单股最大仓位{risk.get('max_position_pct', 0.2) * 100:.0f}% | "
                 f"最多{risk.get('max_position_count', 10)}只持仓 | "
                 f"现金缓冲≥{risk.get('min_cash_buffer_pct', 2)}%")
    return "\n".join(lines)


def _llm_decide(context: str, cfg: dict, latest: dict, klines_dict: dict) -> dict:
    """调用 LLM 做交易决策。返回 {"success", "mode", "decisions", "summary", "provider"}。"""
    from scripts.llm_client import chat_json, get_provider_label

    llm_cfg = cfg.get("llm", {})
    provider = llm_cfg.get("provider", "deepseek")
    mode = llm_cfg.get("mode", "off")
    timeout = int(llm_cfg.get("timeout", 25))

    if mode == "review":
        system = (
            "你是严谨的A股量化交易风控审核员。下面是量化策略产生的交易信号和市场上下文。"
            "请审核每个信号，对不合理的给出 reject 建议。只基于数据客观分析，不编造信息。"
            "直接输出JSON，不要展示推理过程。"
        )
        user = context + "\n\n请审核以上信号。对每只候选股票返回审核意见。"
        r = chat_json(provider, system, user, temperature=0.2, timeout=max(timeout, 40), max_tokens=800, scene="paper")
    elif mode == "decide":
        system = "你是JSON生成器,只输出JSON,不输出推理过程。"
        user = (
            f"{context}\n\n"
            '请对候选股票池中的股票给出买卖建议。'
            '只输出JSON: {"decisions":[{"code":"股票代码","action":"buy或hold或sell","confidence":0.8,"reason":"一句话理由"}]}'
            '必须有decisions字段。buy=建议买入,hold=持有观望,sell=建议卖出。'
        )
        r = chat_json(provider, system, user, temperature=0.3, timeout=max(timeout, 45), max_tokens=2000, scene="paper")
    else:
        return {"success": False, "error": f"未知 LLM 模式: {mode}", "decisions": []}

    if not r["success"]:
        return {"success": False, "error": r.get("error", "LLM调用失败"), "decisions": []}

    data = r.get("data", {})
    decisions = data.get("decisions", [])
    if not isinstance(decisions, list):
        decisions = []
    return {
        "success": True,
        "mode": mode,
        "provider": provider,
        "provider_label": get_provider_label(provider),
        "decisions": decisions,
        "summary": data.get("summary", ""),
    }


def _apply_llm_decisions(desired_long: list, latest: dict, llm_result: dict, cfg: dict) -> list:
    """将 LLM 决策应用到 desired_long 列表。返回调整后的列表。

    review 模式: 移除 LLM 高置信度 reject 的股票
    decide 模式: 用 LLM 的 buy 建议替换 desired_long (受 max_new_positions 限制)
    """
    mode = llm_result.get("mode", "off")
    decisions = llm_result.get("decisions", [])
    llm_cfg = cfg.get("llm", {})
    threshold = float(llm_cfg.get("confidence_threshold", 0.6))
    max_new = int(llm_cfg.get("max_new_positions", 3))

    if mode == "review":
        # 收集高置信度 reject
        rejected = set()
        for d in decisions:
            if not isinstance(d, dict):
                continue
            code = str(d.get("code", "")).strip()
            action = str(d.get("action", "")).lower()
            conf = float(d.get("confidence", 0) or 0)
            if action == "reject" and conf >= threshold and code:
                rejected.add(code)
        return [c for c in desired_long if c not in rejected]

    elif mode == "decide":
        # LLM 独立决策: 收集 buy 建议, 用 score=confidence 排序
        # 只接受候选池内的股票 (latest keys = universe)
        universe_codes = set(latest.keys())
        llm_buys = []
        for d in decisions:
            if not isinstance(d, dict):
                continue
            code = str(d.get("code", "")).strip()
            action = str(d.get("action", "")).lower()
            # confidence 缺失时默认 1.0 (信任 AI 建议)
            raw_conf = d.get("confidence", None)
            conf = float(raw_conf) if raw_conf is not None else 1.0
            # 只接受候选池内的 buy 建议
            if action == "buy" and code in universe_codes and conf >= threshold:
                llm_buys.append((code, conf))
        # 按 confidence 降序
        llm_buys.sort(key=lambda x: x[1], reverse=True)

        # LLM 明确 sell 的股票移除
        llm_sells = {str(d.get("code", "")).strip() for d in decisions
                     if isinstance(d, dict) and str(d.get("action", "")).lower() == "sell"}
        # 量化信号 buy + LLM 未否决
        kept = [c for c in desired_long if c not in llm_sells]
        # LLM buy 建议 (限制数量, 只限候选池)
        new_pool = [c for c, _ in llm_buys[:max_new] if c not in kept]
        merged = kept + new_pool
        return merged if merged else [c for c, _ in llm_buys[:max_new]]  # fallback: 至少用 LLM buy

    return desired_long


def _summarize_llm(llm_result, llm_cfg: dict) -> dict:
    """生成 LLM 层的摘要, 写入 summary["llm"] 供日报展示。"""
    if not llm_result or not llm_result.get("success"):
        return {
            "enabled": llm_cfg.get("enabled", False),
            "mode": llm_cfg.get("mode", "off"),
            "active": False,
            "decisions_count": 0,
        }
    return {
        "enabled": True,
        "active": True,
        "mode": llm_result.get("mode"),
        "provider": llm_result.get("provider"),
        "provider_label": llm_result.get("provider_label"),
        "decisions_count": len(llm_result.get("decisions", [])),
        "summary": llm_result.get("summary", ""),
    }


def _finish(summary: dict, cfg: dict):
    """收尾: 写状态 + 日志。

    若 summary["skipped"]==True (锁占用/数据过期等预期跳过):
      - 仍记 last_run / last_result / 日志 (便于前端展示跳过原因)
      - 但不写 last_run_date, 否则 daemon 当天不会再触发, 数据更新后也无法补跑
    """
    now = datetime.now()
    summary["finished_at"] = _now_iso()
    status = load_status()
    status["last_run"] = summary["finished_at"]
    status["last_result"] = summary
    skipped = bool(summary.get("skipped"))
    if not skipped:
        status["last_run_date"] = now.strftime("%Y-%m-%d")
    # 下次运行: 明天 trade_time
    status["next_run"] = f"{(now).strftime('%Y-%m-%d')} {cfg.get('trade_time','15:05')} (next trading day)"
    try:
        from scripts.ai_objective import compute_objective_status
        summary["objective_status"] = compute_objective_status()
    except Exception:
        pass
    save_status(status)
    day = now.strftime('%Y%m%d')
    cache.set(f"paper:daily:{day}", summary)
    cache.set(f"paper:audit:{day}", {
        "summary": summary,
        "config": cfg,
        "status": status,
    })
    try:
        record_audit_run(cache, summary, cfg, status)
    except Exception as e:
        logger.debug(f"structured audit write failed (non-fatal): {e}")
    append_log({
        "time": summary["finished_at"],
        "strategy": cfg["strategy_name"],
        "order_count": summary.get("order_count", 0),
        "signals": summary["signals"],
        "errors": summary["errors"],
        "skipped": skipped,
        "skip_reason": summary.get("skip_reason"),
        "risk_rejections": summary.get("risk_rejections", []),
        "skipped_orders": summary.get("skipped_orders", []),
        "data_date": summary.get("data_date"),
        "trigger_source": summary.get("trigger_source"),
    })
    if skipped:
        logger.info(f"run_once 跳过: skip_reason={summary.get('skip_reason')}, "
                    f"data_date={summary.get('data_date')}")
    else:
        logger.info(f"run_once 完成: {summary.get('order_count',0)} 单, "
                    f"{len(summary['signals'])} 信号, errors={len(summary['errors'])}")

    # ── 刷新基准对比 + 生成日报 (不阻断主流程) ──
    _emit_progress(6, "刷新基准", "running", "更新沪深300基准...")
    try:
        from scripts.benchmark import init_benchmark, refresh_benchmark
        exec_state = cache.get("execution:state") or {}
        init_cap = float(exec_state.get("initial_capital", 1_000_000))
        init_benchmark(init_cap)
        refresh_benchmark()
        _emit_progress(6, "刷新基准", "done", "完成")
    except Exception as e:
        _emit_progress(6, "刷新基准", "error", str(e)[:80])
        logger.debug(f"benchmark refresh failed (non-fatal): {e}")
    _emit_progress(7, "生成日报", "running", "生成账户/基准/AI复盘...")
    try:
        from scripts.daily_report import generate_report, save_report
        report = generate_report()
        save_report(report)
        _emit_progress(7, "生成日报", "done", "完成")
        logger.info(f"日报已生成: paper:report:{datetime.now().strftime('%Y%m%d')}")
    except Exception as e:
        _emit_progress(7, "生成日报", "error", str(e)[:80])
        logger.debug(f"daily report failed (non-fatal): {e}")


# ─── 调度判断 ──────────────────────────────────────────────────
def _parse_time(value: str):
    """解析常见时间字符串, 失败返回 None。"""
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _scheduler_is_active() -> bool:
    """自主调度器(ai_scheduler)是否健康运行。

    如果调度器启用且最近状态新鲜, paper_trader daemon 进入"待命模式":
    不主动触发交易 (避免双重触发), 只等待被 ai_loop 调用。
    若 enabled=true 但状态明显过期/不健康, paper_trader 恢复兜底触发。
    """
    try:
        sched_cfg = cache.get("ai:scheduler:config") or {}
        if not sched_cfg.get("enabled", False):
            return False
        sched = cache.get("ai:scheduler:latest") or {}
        if not sched.get("running", False):
            return False
        ts = _parse_time(sched.get("updated_at") or sched.get("last_cycle_at") or sched.get("started_at"))
        if ts is None:
            return False
        # 允许 idle 模式 2 小时周期 + 宽限；过期则视为不健康, paper daemon 可兜底。
        interval = int(sched.get("interval_sec") or 7200)
        max_age = max(900, interval + 300)
        return (datetime.now() - ts).total_seconds() <= max_age
    except Exception:
        return False


def _should_run_today(now: datetime, cfg: dict, status: dict) -> bool:
    """判断今天是否到了该执行的时间 (交易日, 到达 trade_time, 且今天还没跑过)。

    如果自主调度器在运行, paper_trader daemon 让位 — 不自主触发交易。
    """
    # 互斥: 调度器启用时让位 (交易由 ai_loop → paper_trader --once 触发)
    if _scheduler_is_active():
        return False
    if not _is_trading_day():
        return False
    trade_time = cfg.get("trade_time", "15:05")
    try:
        hh, mm = [int(x) for x in trade_time.split(":")]
    except Exception:
        hh, mm = 15, 5
    now_hm = now.hour * 60 + now.minute
    if now_hm < hh * 60 + mm:
        return False
    today = now.strftime("%Y-%m-%d")
    if status.get("last_run_date") == today:
        return False
    return True


# ─── daemon 主循环 ─────────────────────────────────────────────
def run_daemon():
    status = load_status()
    status["running"] = True
    status["pid"] = os.getpid()
    save_status(status)
    logger.info("paper_trader daemon 启动")

    while True:
        try:
            cfg = load_config()
            status = load_status()
            if cfg.get("enabled", False) and _should_run_today(datetime.now(), cfg, status):
                logger.info(f"到达 {cfg.get('trade_time')}, 开始执行 run_once")
                run_once(source="paper_daemon")
            time.sleep(60)  # 每分钟检查一次
        except KeyboardInterrupt:
            logger.info("收到退出信号")
            break
        except Exception as e:
            logger.error(f"主循环异常: {e}", exc_info=True)
            time.sleep(60)

    status = load_status()
    status["running"] = False
    save_status(status)
    logger.info("paper_trader daemon 已停止")


def main():
    parser = argparse.ArgumentParser(description="模拟盘调度器")
    parser.add_argument("--once", action="store_true", help="单次执行后退出 (不做循环)")
    parser.add_argument("--source", default="manual", help="触发来源: manual|paper_daemon|ai_loop|scheduler")
    args = parser.parse_args()

    if args.once:
        logger.info(f"paper_trader --once 单次执行 source={args.source}")
        result = run_once(source=args.source)
        # 打印摘要到 stdout, 便于 Node 端读取
        print(json.dumps({"success": not result.get("errors"), "data": result}, ensure_ascii=False, default=str))
        return
    run_daemon()


if __name__ == "__main__":
    main()
