"""AI 自我迭代闭环 — 五层自动调度 + 全球动态 + 经验学习

这是整个 AI 量化系统的「大脑循环」:
  1. 采集全球实时动态 → risk regime
  2. L1 数据层检查 → 是否可交易
  3. L2 因子工厂 → 自动挖掘+验证新因子
  4. L3 策略工厂 → 自动回测+对比候选策略
  5. L4 执行建议 → 生成今日操作建议
  6. L5 风控验证 → 判断是否允许交易
  7. AI Operator → 汇总五层生成总控计划
  8. 经验沉淀 → 写入 ai:memory:lessons
  9. (可选) 触发 paper_trader --once

安全边界:
  - 全球动态只影响 trade_policy, 不直接触发买入
  - 硬风控规则不可被 AI 覆盖
  - 所有层失败都降级为保守模式
  - 经验只用于上下文参考, 不覆盖硬规则

用法:
  python scripts/ai_loop.py --once        # 跑一轮完整闭环
  python scripts/ai_loop.py --daemon      # 调试/兼容守护模式；统一自主调度请使用 ai_scheduler.py
  python scripts/ai_loop.py --status      # 读取状态
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache

cache = create_cache()
LOOP_KEY = "ai:loop:latest"
LOOP_LOG_KEY = "ai:loop:log"
LOOP_LOCK_KEY = "ai:loop:lock"      # 跨进程互斥锁, 防止 scheduler/手动闭环并发
LOOP_LOCK_TTL = 900                  # 覆盖一轮完整闭环最大耗时, 崩溃后自动释放


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def _log_step(step: str, status: str, detail: str = ""):
    """写入闭环步骤日志。"""
    try:
        log = cache.get("ai:loop:progress") or []
        log.append({"step": step, "status": status, "detail": detail, "time": _now()})
        cache.set("ai:loop:progress", log[-50:])
    except Exception:
        pass


def _clear_progress():
    cache.set("ai:loop:progress", [])


def _lock_conn():
    """返回 cache 底层 sqlite 连接, 非 SqliteCache 返回 None。"""
    conn = getattr(cache, "_conn", None)
    db_path = getattr(cache, "_db_path", None)
    if conn is None or db_path is None:
        return None
    return conn


def acquire_loop_lock(source: str = "manual") -> bool:
    """抢占闭环锁。避免 scheduler daemon、run_once、手动闭环并发跑五层。"""
    conn = _lock_conn()
    if conn is None:
        return True
    now_ts = time.time()
    data = json.dumps({"pid": os.getpid(), "source": source, "time": _now(), "ts": now_ts}, ensure_ascii=False)
    try:
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("DELETE FROM kv WHERE key = ? AND exp IS NOT NULL AND exp < ?", (LOOP_LOCK_KEY, now_ts))
        cur = conn.execute(
            "INSERT OR IGNORE INTO kv (key, value, exp) VALUES (?, ?, ?)",
            (LOOP_LOCK_KEY, data, now_ts + LOOP_LOCK_TTL),
        )
        conn.commit()
        return cur.rowcount == 1
    except Exception:
        return True


def release_loop_lock():
    """释放当前进程持有的闭环锁。"""
    conn = _lock_conn()
    if conn is None:
        return
    try:
        conn.execute("PRAGMA busy_timeout = 5000")
        row = conn.execute("SELECT value FROM kv WHERE key = ?", (LOOP_LOCK_KEY,)).fetchone()
        if row:
            try:
                holder = json.loads(row[0])
                if isinstance(holder, dict) and holder.get("pid") == os.getpid():
                    conn.execute("DELETE FROM kv WHERE key = ?", (LOOP_LOCK_KEY,))
                    conn.commit()
            except (json.JSONDecodeError, TypeError):
                pass
    except Exception:
        pass


def run_loop(provider: str = "glm", trigger_paper: bool = False, source: str = "manual") -> dict:
    """运行一轮完整的 AI 五层闭环。"""
    if not acquire_loop_lock(source):
        result = {
            "started_at": _now(),
            "finished_at": _now(),
            "provider": provider,
            "source": source,
            "steps": {},
            "errors": [f"另一进程正在运行 AI 闭环 (锁 {LOOP_LOCK_KEY} 被占用), 本轮跳过"],
            "skipped": True,
            "skip_reason": "locked",
        }
        _log_step("AI闭环", "skip", "已有闭环在运行, 跳过本轮")
        return result

    _clear_progress()
    started = _now()
    results = {"started_at": started, "provider": provider, "source": source, "steps": {}, "errors": []}

    try:
        # ── Step 0: 全球实时动态 ──────────────────────
        _log_step("全球动态", "running", "采集全球指数/汇率/商品...")
        try:
            from scripts.global_context import collect_global_context
            global_ctx = collect_global_context()
            results["steps"]["global"] = {
                "risk_level": global_ctx.get("risk_level"),
                "trade_policy": global_ctx.get("trade_policy"),
                "risk_signals": global_ctx.get("risk_signals"),
            }
            _log_step("全球动态", "done", f"risk={global_ctx.get('risk_level')} policy={global_ctx.get('trade_policy')}")
        except Exception as e:
            results["errors"].append(f"全球动态失败: {e}")
            _log_step("全球动态", "error", str(e)[:80])

        # ── Step 1: L1 数据层 (检测到过期自动补数) ────
        _log_step("L1数据层", "running", "检查数据完整性...")
        try:
            from scripts.ai_data_agent import run_data_agent, check_data_integrity
            integrity = check_data_integrity()
            if integrity["summary"]["stale"] > 0 or integrity["summary"]["missing"] > 0:
                _log_step("L1数据层", "running", f"检测到过期/缺失, 自动补数 {integrity['summary']['stale']}只...")
                l1 = run_data_agent(provider, auto_fix=True)
                _log_step("L1数据层", "done",
                          f"补数完成 stale={l1.get('data_stale')} ok={l1.get('integrity',{}).get('summary',{}).get('ok',0)}")
            else:
                l1 = run_data_agent(provider, auto_fix=False)
                _log_step("L1数据层", "done", f"数据正常 ok={integrity['summary']['ok']}")
            results["steps"]["L1_data"] = {
                "data_stale": l1.get("data_stale"),
                "trade_allowed": l1.get("trade_allowed"),
                "integrity": l1.get("integrity", {}).get("summary"),
                "replenish_result": l1.get("replenish_result"),
            }
        except Exception as e:
            results["errors"].append(f"L1数据层失败: {e}")
            _log_step("L1数据层", "error", str(e)[:80])

        # ── Step 2: L2 因子工厂 ──────────────────────
        _log_step("L2因子工厂", "running", "GLM生成候选+IC验证...")
        try:
            from scripts.ai_factor_agent import run_factor_factory
            l2 = run_factor_factory(provider, n_candidates=3)
            results["steps"]["L2_factor"] = {
                "candidates": len(l2.get("candidates", [])),
                "approved": l2.get("approved_count"),
                "rejected": l2.get("rejected_count"),
            }
            _log_step("L2因子工厂", "done", f"候选{l2.get('approved_count',0)}通过")
        except Exception as e:
            results["errors"].append(f"L2因子工厂失败: {e}")
            _log_step("L2因子工厂", "error", str(e)[:80])

        # ── Step 3: L3 策略工厂 ──────────────────────
        _log_step("L3策略工厂", "running", "GLM生成策略+回测...")
        try:
            from scripts.ai_strategy_agent import run_strategy_factory
            l3 = run_strategy_factory(provider)
            results["steps"]["L3_strategy"] = {
                "candidates": len(l3.get("candidates", [])),
                "approved": l3.get("approved_count"),
                "baseline_strategy": l3.get("baseline_strategy"),
            }
            _log_step("L3策略工厂", "done", f"候选{len(l3.get('candidates',[]))} 基线={l3.get('baseline_strategy')}")
        except Exception as e:
            results["errors"].append(f"L3策略工厂失败: {e}")
            _log_step("L3策略工厂", "error", str(e)[:80])

        # ── Step 4: L4 执行建议 ──────────────────────
        _log_step("L4执行建议", "running", "生成执行建议+复盘...")
        try:
            from scripts.ai_execution_agent import generate_execution_advice, execution_review
            l4 = generate_execution_advice(provider)
            l4_review = execution_review(provider)
            results["steps"]["L4_execution"] = {
                "orders": l4.get("today_order_count"),
                "rejections": l4.get("risk_rejection_count"),
                "review_lessons": l4_review.get("total_lessons"),
            }
            _log_step("L4执行建议", "done", f"订单{l4.get('today_order_count',0)} 拒单{l4.get('risk_rejection_count',0)}")
        except Exception as e:
            results["errors"].append(f"L4执行失败: {e}")
            _log_step("L4执行建议", "error", str(e)[:80])

        # ── Step 5: L5 风控验证 ──────────────────────
        _log_step("L5风控验证", "running", "事前风控+自我验证...")
        try:
            from scripts.ai_risk_agent import run_risk_monitor
            l5 = run_risk_monitor(provider)
            results["steps"]["L5_risk"] = {
                "trade_allowed": l5.get("pre_trade", {}).get("trade_allowed"),
                "trade_policy": l5.get("pre_trade", {}).get("trade_policy"),
                "overall": l5.get("self_verification", {}).get("overall"),
                "block_reasons": l5.get("pre_trade", {}).get("block_reasons"),
            }
            _log_step("L5风控验证", "done", f"allowed={l5.get('pre_trade',{}).get('trade_allowed')}")
        except Exception as e:
            results["errors"].append(f"L5风控失败: {e}")
            _log_step("L5风控验证", "error", str(e)[:80])

        # ── Step 6: AI Operator 总控汇总 ─────────────
        _log_step("AI总控汇总", "running", "生成总控计划...")
        try:
            from scripts.ai_operator import run_operator
            operator = run_operator(provider)
            results["steps"]["operator"] = {
                "trade_policy": operator.get("trade_policy"),
                "actions": len(operator.get("actions", [])),
                "summary": (operator.get("summary") or "")[:200],
            }
            _log_step("AI总控汇总", "done", f"policy={operator.get('trade_policy')}")
        except Exception as e:
            results["errors"].append(f"AI总控失败: {e}")
            _log_step("AI总控汇总", "error", str(e)[:80])

        # ── Step 7: 综合判断 ─────────────────────────
        global_policy = results["steps"].get("global", {}).get("trade_policy", "normal")
        data_ok = not results["steps"].get("L1_data", {}).get("data_stale", True)
        risk_ok = results["steps"].get("L5_risk", {}).get("trade_allowed", False)
        operator_policy = results["steps"].get("operator", {}).get("trade_policy", "no_new_position")

        # 最保守策略胜出
        policies = [global_policy, operator_policy]
        if not data_ok:
            policies.append("no_new_position")
        if not risk_ok:
            policies.append("no_new_position")
        priority = {"normal": 0, "reduce_only": 1, "no_new_position": 2}
        final_policy = max(policies, key=lambda p: priority.get(p, 2))
        final_trade_allowed = final_policy == "normal" and data_ok and risk_ok

        results["final"] = {
            "trade_allowed": final_trade_allowed,
            "trade_policy": final_policy,
            "data_ok": data_ok,
            "risk_ok": risk_ok,
            "global_risk": results["steps"].get("global", {}).get("risk_level"),
        }

        # ── 写入决策层统一输出 ai:decision:latest (供执行层读取) ────
        # paper_trader 执行时读这个键, 避免决策层和执行层各判断各的。
        global_ctx = results["steps"].get("global", {})
        operator_plan = results["steps"].get("operator", {})
        cache.set("ai:decision:latest", {
            "trade_policy": final_policy,
            "trade_allowed": final_trade_allowed,
            "risk_level": global_ctx.get("risk_level", "low"),
            "global_risk_signals": global_ctx.get("risk_signals", []),
            "operator_summary": operator_plan.get("summary", ""),
            "operator_actions": operator_plan.get("actions", []),
            "data_ok": data_ok,
            "risk_ok": risk_ok,
            "generated_at": _now(),
            "date": _today(),
            "source": source,
        })

        # ── Step 8: 经验沉淀 ─────────────────────────
        try:
            lessons = cache.get("ai:memory:lessons") or []
            lessons.append({
                "date": _today(),
                "type": "ai_loop",
                "content": f"闭环完成: policy={final_policy} data_ok={data_ok} risk_ok={risk_ok} errors={len(results['errors'])}",
            })
            lessons = lessons[-50:]
            cache.set("ai:memory:lessons", lessons)
            results["total_lessons"] = len(lessons)
        except Exception:
            pass

        # ── Step 9: (可选) 触发模拟盘交易 ─────────────
        if trigger_paper and final_trade_allowed:
            paper_source = "scheduler" if source == "scheduler" else "ai_loop"
            _log_step("触发交易", "running", "调用 paper_trader --once...")
            try:
                import subprocess
                subprocess.run(
                    [sys.executable, os.path.join(os.path.dirname(__file__), "paper_trader.py"), "--once", "--source", paper_source],
                    cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    timeout=120, capture_output=True,
                )
                _log_step("触发交易", "done", f"paper_trader 已执行 source={paper_source}")
            except Exception as e:
                _log_step("触发交易", "error", str(e)[:80])
        else:
            _log_step("触发交易", "skip", f"policy={final_policy}, 不触发交易")

        results["finished_at"] = _now()
        results["progress"] = cache.get("ai:loop:progress") or []
        cache.set(LOOP_KEY, results)

        # 写入日志
        log = cache.get(LOOP_LOG_KEY) or []
        log.append({"started": started, "finished": results["finished_at"],
                    "policy": final_policy, "errors": len(results["errors"]), "source": source})
        cache.set(LOOP_LOG_KEY, log[-30:])

        return results
    finally:
        release_loop_lock()


def run_daemon(provider: str = "glm", interval: int = 300):
    """调试/兼容守护模式: 每 interval 秒跑一轮闭环。

    统一自主调度请使用 ai_scheduler.py；本入口不由 Node manager/watchdog 托管。
    """
    print(f"[AI Loop] daemon started for debug/compat only, interval={interval}s. Use ai_scheduler.py for autonomous scheduling.", flush=True)
    while True:
        try:
            print(f"[AI Loop] {datetime.now()} starting cycle...", flush=True)
            result = run_loop(provider, trigger_paper=False, source="ai_loop_daemon")
            final = result.get("final", {})
            print(f"[AI Loop] cycle done: policy={final.get('trade_policy')} errors={len(result.get('errors', []))}", flush=True)
        except Exception as e:
            print(f"[AI Loop] cycle error: {e}", flush=True)
        time.sleep(interval)


def get_status() -> dict:
    return {
        "latest": cache.get(LOOP_KEY),
        "progress": cache.get("ai:loop:progress") or [],
        "log": (cache.get(LOOP_LOG_KEY) or [])[-10:],
        "lessons": (cache.get("ai:memory:lessons") or [])[-5:],
        "global": cache.get("global:context:latest"),
    }


def main():
    parser = argparse.ArgumentParser(description="AI 自我迭代闭环")
    parser.add_argument("--once", action="store_true", help="跑一轮完整闭环")
    parser.add_argument("--daemon", action="store_true", help="调试/兼容守护模式；统一自主调度请使用 ai_scheduler.py")
    parser.add_argument("--status", action="store_true", help="读取状态")
    parser.add_argument("--trigger-paper", action="store_true", help="允许触发模拟盘交易")
    parser.add_argument("--provider", default="glm")
    parser.add_argument("--interval", type=int, default=300, help="daemon 间隔秒")
    parser.add_argument("--source", default="manual", help="触发来源: manual|scheduler|ai_loop_daemon")
    args = parser.parse_args()

    if args.daemon:
        run_daemon(args.provider, args.interval)
    elif args.once:
        out = run_loop(args.provider, args.trigger_paper, source=args.source)
    else:
        out = get_status()
    print(json.dumps({"success": True, "data": out}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
