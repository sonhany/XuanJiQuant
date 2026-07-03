"""AI 智能时段调度器 — 自主驱动五层闭环巡检

这是整个 AI 量化系统的"心跳"。根据当前时段自动决定本轮工作量:
  - 盘中 (交易日 09:30-15:00): 轻量巡检, 每 10 分钟一轮
      → 只跑全球动态 + L1 数据新鲜度检查 + L5 风控 (省 token, 盘中不重算因子/策略)
  - 盘后 (交易日 15:00-23:59): 重巡检, 每 30 分钟一轮
      → 跑完整 9 步 ai_loop.run_loop(trigger_paper=True), 刷新数据/因子/策略, 到点触发模拟盘
  - 非交易日 / 夜间: 每 2 小时一次全球动态 + 数据检查

设计原则:
  - 单例 daemon (ai_loop_manager.mjs 管理), 同一时刻只跑一个
  - 每轮失败不退出, 记录到 errors, 继续下一轮 (容错)
  - 状态实时写入 ai:scheduler:latest, 供驾驶舱/watchdog 监控
  - 默认 provider 从 paper:config.llm.provider 读, 兜底 glm

用法:
  python scripts/ai_scheduler.py --daemon            # 守护进程
  python scripts/ai_scheduler.py --status            # 读状态
  python scripts/ai_scheduler.py --once              # 跑当前时段对应的一轮
"""
import argparse
import json
import logging
import os
import sys
import time
import traceback
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache

logger = logging.getLogger("ai_scheduler")
cache = create_cache()

SCHED_KEY = "ai:scheduler:latest"
SCHED_CFG_KEY = "ai:scheduler:config"
SCHED_LOG_KEY = "ai:scheduler:log"

# ── 时段定义 ──────────────────────────────────────────────
MORNING_START = (9, 30)   # 盘中开始
CLOSE = (15, 0)           # 收盘
EVENING_END = (23, 59)    # 盘后窗口结束
# 夜间 (00:00-09:30) 和非交易日走 idle 模式


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def _hm(now: datetime) -> int:
    """当前时间转分钟数 (hour*60+minute)。"""
    return now.hour * 60 + now.minute


def _is_trading_day() -> bool:
    """今天是否为 A股交易日 (复用统一交易日历)。"""
    try:
        from scripts.trading_calendar import is_trade_date
        return bool(is_trade_date(_today()))
    except Exception:
        # 兜底: 周末非交易日
        return datetime.now().weekday() < 5


def determine_mode(now: datetime = None) -> str:
    """根据当前时间判断调度模式。

    返回:
      "intraday"  盘中轻量 (交易日 09:30-15:00)
      "postclose" 盘后重巡检 (交易日 15:00-23:59)
      "idle"      夜间 / 非交易日
    """
    now = now or datetime.now()
    hm = _hm(now)
    morning = MORNING_START[0] * 60 + MORNING_START[1]
    close = CLOSE[0] * 60 + CLOSE[1]
    evening = EVENING_END[0] * 60 + EVENING_END[1]

    if _is_trading_day():
        if morning <= hm < close:
            return "intraday"
        if close <= hm <= evening:
            return "postclose"
    return "idle"


def _interval_for_mode(mode: str) -> int:
    """各模式对应的轮询间隔 (秒)。"""
    return {"intraday": 600, "postclose": 1800, "idle": 7200}.get(mode, 1800)


def _default_provider() -> str:
    """从 paper:config 读 provider, 兜底 glm。"""
    try:
        cfg = cache.get("paper:config") or {}
        return (cfg.get("llm") or {}).get("provider") or "glm"
    except Exception:
        return "glm"


def _read_cfg() -> dict:
    """读调度器配置 (可被前端覆盖)。"""
    return cache.get(SCHED_CFG_KEY) or {"enabled": False, "provider": "glm"}


# ── 轻量巡检 (盘中) ──────────────────────────────────────
def _run_light_cycle(provider: str) -> dict:
    """盘中轻量: 全球动态 + L1 数据检查 + L5 风控。不触发交易。"""
    steps, errors = {}, []
    started = _now()

    # 全球动态
    try:
        from scripts.global_context import collect_global_context
        steps["global"] = collect_global_context()
    except Exception as e:
        errors.append(f"global: {str(e)[:120]}")

    # L1 数据新鲜度
    try:
        from scripts.data_freshness import is_data_stale, check_integrity
        steps["data"] = {
            "stale": bool(is_data_stale()),
            "integrity": check_integrity(),
        }
    except Exception as e:
        errors.append(f"data: {str(e)[:120]}")

    # L5 风控
    try:
        from scripts.ai_risk_agent import run_risk_monitor
        steps["risk"] = run_risk_monitor(provider)
    except Exception as e:
        errors.append(f"risk: {str(e)[:120]}")

    return {
        "mode": "intraday",
        "started_at": started,
        "finished_at": _now(),
        "steps": steps,
        "errors": errors,
    }


# ── 重巡检 (盘后) ────────────────────────────────────────
def _run_heavy_cycle(provider: str) -> dict:
    """盘后重巡检: 完整 9 步闭环, 可能触发模拟盘交易。"""
    from scripts.ai_loop import run_loop
    started = _now()
    try:
        result = run_loop(provider, trigger_paper=True, source="scheduler")
        result["mode"] = "postclose"
        result["started_at"] = started
        return result
    except Exception as e:
        return {
            "mode": "postclose",
            "started_at": started,
            "finished_at": _now(),
            "errors": [f"loop: {str(e)[:200]}", traceback.format_exc()[-300:]],
            "steps": {},
        }


# ── 空闲巡检 (夜间/非交易日) ────────────────────────────
def _run_idle_cycle(provider: str) -> dict:
    """夜间/非交易日: 只采全球动态 + 数据新鲜度。"""
    steps, errors = {}, []
    started = _now()
    try:
        from scripts.global_context import collect_global_context
        steps["global"] = collect_global_context()
    except Exception as e:
        errors.append(f"global: {str(e)[:120]}")
    try:
        from scripts.data_freshness import is_data_stale
        steps["data"] = {"stale": bool(is_data_stale())}
    except Exception as e:
        errors.append(f"data: {str(e)[:120]}")
    return {
        "mode": "idle",
        "started_at": started,
        "finished_at": _now(),
        "steps": steps,
        "errors": errors,
    }


def run_one_cycle(provider: str = None) -> dict:
    """跑当前时段对应的一轮巡检。"""
    provider = provider or _default_provider()
    mode = determine_mode()
    if mode == "intraday":
        result = _run_light_cycle(provider)
    elif mode == "postclose":
        result = _run_heavy_cycle(provider)
    else:
        result = _run_idle_cycle(provider)

    # 写入最新状态
    now = datetime.now()
    interval = _interval_for_mode(mode)
    next_cycle = (now.timestamp() + interval)
    status = {
        "running": True,
        "mode": mode,
        "provider": provider,
        "last_cycle": result,
        "last_cycle_at": _now(),
        "next_cycle_at": datetime.fromtimestamp(next_cycle).strftime("%Y-%m-%d %H:%M:%S"),
        "interval_sec": interval,
        "cycles_count": int((cache.get(SCHED_KEY) or {}).get("cycles_count", 0)) + 1,
        "updated_at": _now(),
    }
    cache.set(SCHED_KEY, status)

    # 追加运行日志 (保留最近 30 条)
    log = cache.get(SCHED_LOG_KEY) or []
    log.append({
        "time": _now(), "mode": mode, "errors": len(result.get("errors", [])),
        "started_at": result.get("started_at"), "finished_at": result.get("finished_at"),
    })
    cache.set(SCHED_LOG_KEY, log[-30:])

    return status


def get_status() -> dict:
    """读调度器状态。"""
    s = cache.get(SCHED_KEY) or {}
    s["current_mode"] = determine_mode()
    s["is_trading_day"] = _is_trading_day()
    s["config"] = cache.get(SCHED_CFG_KEY) or {"enabled": False, "provider": "glm"}
    return s


def run_daemon(provider: str = None):
    """守护进程: 根据时段自动巡检。"""
    provider = provider or _default_provider()
    # 标记 daemon 启动
    cache.set(SCHED_KEY, {
        "running": True,
        "pid": os.getpid(),
        "started_at": _now(),
        "mode": determine_mode(),
        "provider": provider,
        "cycles_count": 0,
    })
    cache.set(SCHED_CFG_KEY, {"enabled": True, "provider": provider})
    print(f"[AI Scheduler] daemon started pid={os.getpid()} provider={provider}", flush=True)

    while True:
        try:
            # 每轮重新读 provider (允许前端热切换)
            provider = _default_provider()
            mode = determine_mode()
            result = run_one_cycle(provider)
            print(f"[AI Scheduler] {result['last_cycle_at']} mode={mode} errors={len(result['last_cycle'].get('errors', []))}", flush=True)
        except Exception as e:
            print(f"[AI Scheduler] cycle error: {e}", flush=True)
            traceback.print_exc()
        # 按当前时段 sleep
        time.sleep(_interval_for_mode(determine_mode()))


def main():
    parser = argparse.ArgumentParser(description="AI 智能时段调度器")
    parser.add_argument("--daemon", action="store_true", help="守护进程模式")
    parser.add_argument("--once", action="store_true", help="跑当前时段对应的一轮")
    parser.add_argument("--status", action="store_true", help="读状态")
    parser.add_argument("--provider", default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.daemon:
        run_daemon(args.provider)
    elif args.once:
        out = run_one_cycle(args.provider)
    else:
        out = get_status()
    print(json.dumps({"success": True, "data": out}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
