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
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.ai.contracts import normalize_ai_decision
from quant.data.audit import write_ai_decision
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
        try:
            holder = cache.get(LOOP_LOCK_KEY) or {}
            if holder and time.time() - float(holder.get("ts", 0) or 0) < LOOP_LOCK_TTL:
                return False
            cache.set(LOOP_LOCK_KEY, {"pid": os.getpid(), "source": source, "time": _now(), "ts": time.time()}, ttl=LOOP_LOCK_TTL)
            return True
        except Exception:
            return False
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
        return False


def release_loop_lock():
    """释放当前进程持有的闭环锁。"""
    conn = _lock_conn()
    if conn is None:
        try:
            holder = cache.get(LOOP_LOCK_KEY) or {}
            if isinstance(holder, dict) and holder.get("pid") == os.getpid():
                cache.delete(LOOP_LOCK_KEY)
        except Exception:
            pass
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
                "paper_trade_allowed": bool(operator.get("paper_trade_allowed", False)),
                "actions": operator.get("actions", []),
                "action_count": len(operator.get("actions", [])),
                "summary": (operator.get("summary") or "")[:200],
            }
            _log_step("AI总控汇总", "done", f"policy={operator.get('trade_policy')}")
        except Exception as e:
            results["errors"].append(f"AI总控失败: {e}")
            _log_step("AI总控汇总", "error", str(e)[:80])

        # ── Step 6.5: 全市场 AI 选股 ─────────────────
        # 用 IC 加权打分 + GLM 复核, 从全市场筛出 Top 候选股。
        # 失败静默降级 (返回空池), 不阻断闭环; 仅在重巡检触发, 盘中轻量巡检不跑。
        candidate_pool = []
        _log_step("全市场选股", "running", "因子打分+AI复核...")
        try:
            from scripts.ai_stock_screener import screen_market
            screened = screen_market(top_n=20, provider=provider)
            candidate_pool = [s["code"] for s in screened.get("top", [])]
            results["steps"]["screen"] = {
                "candidates": len(candidate_pool),
                "stats": screened.get("stats", {}),
            }
            _log_step("全市场选股", "done", f"选出 {len(candidate_pool)} 只候选")
        except Exception as e:
            results["errors"].append(f"全市场选股失败: {str(e)[:120]}")
            _log_step("全市场选股", "error", str(e)[:80])

        # ── Step 6.6: candidate_pool 持久化为动态选股池 ─────
        # 把选出的 Top 代码并入 paper:config.universe (只增不减 + 上限50)
        # 解决断点 G: 让 paper_trader daemon 兜底路径也能拿到选股结果
        if candidate_pool:
            try:
                _cfg = cache.get("paper:config") or {}
                old_universe = set(str(c) for c in (_cfg.get("universe") or []))
                new_universe = list(old_universe | set(candidate_pool))[:50]
                if len(new_universe) != len(old_universe):
                    _cfg["universe"] = new_universe
                    cache.set("paper:config", _cfg)
                    _log_step("全市场选股", "done", f"universe 更新为 {len(new_universe)} 只")
            except Exception as e:
                _log_step("全市场选股", "error", f"universe 持久化失败: {str(e)[:60]}")

        # ── Step 6.7: 全局目标组合规划 ─────────────────
        objective_status = None
        portfolio_plan = None
        autonomous_cfg = {}
        try:
            from scripts.ai_objective import compute_objective_status, load_autonomous_config
            autonomous_cfg = load_autonomous_config()
            objective_status = compute_objective_status(autonomous_cfg)
            results["steps"]["objective"] = {
                "target_equity": objective_status.get("target_equity"),
                "current_equity": objective_status.get("current_equity"),
                "progress_pct": objective_status.get("progress_pct"),
                "risk_mode": objective_status.get("risk_mode"),
                "pressure": objective_status.get("objective_pressure"),
            }
            _log_step("目标进度", "done", f"进度{objective_status.get('progress_pct', 0):.2f}% 需年化{objective_status.get('required_annualized_return_pct', 0):.1f}%")
            if autonomous_cfg.get("enabled") and autonomous_cfg.get("mode") == "target_portfolio":
                _log_step("目标组合委员会", "running", "多角色委员会生成目标权重...")
                from scripts.ai_portfolio_planner import run_portfolio_committee
                portfolio_plan = run_portfolio_committee(provider, candidate_pool=candidate_pool, objective=objective_status, loop_results=results)
                results["steps"]["portfolio"] = {
                    "trade_policy": portfolio_plan.get("trade_policy"),
                    "targets": len(portfolio_plan.get("target_weights", [])),
                    "cash_target_pct": portfolio_plan.get("cash_target_pct"),
                    "summary": (portfolio_plan.get("summary") or "")[:200],
                }
                _log_step("目标组合委员会", "done", f"目标{len(portfolio_plan.get('target_weights', []))}只 policy={portfolio_plan.get('trade_policy')}")
        except Exception as e:
            results["errors"].append(f"目标组合规划失败: {str(e)[:160]}")
            _log_step("目标组合委员会", "error", str(e)[:80])

        # ── Step 7: 综合判断 ─────────────────────────
        global_ok = "global" in results["steps"]
        global_policy = results["steps"].get("global", {}).get("trade_policy", "reduce_only")
        data_ok = not results["steps"].get("L1_data", {}).get("data_stale", True)
        risk_ok = results["steps"].get("L5_risk", {}).get("trade_allowed", False)
        operator_step = results["steps"].get("operator", {})
        operator_policy = operator_step.get("trade_policy", "no_new_position")
        operator_allowed = bool(operator_step.get("paper_trade_allowed", False))

        # 最保守策略胜出。Operator 的显式禁止交易也必须进入最终门禁。
        portfolio_policy = (portfolio_plan or {}).get("trade_policy")
        policies = [global_policy, operator_policy]
        if portfolio_policy:
            policies.append(portfolio_policy)
        if objective_status and objective_status.get("risk_mode") == "no_new_position":
            policies.append("no_new_position")
        if not global_ok:
            policies.append("reduce_only")
        if not data_ok:
            policies.append("no_new_position")
        if not risk_ok:
            policies.append("no_new_position")
        if not operator_allowed:
            policies.append("no_new_position")
        priority = {"normal": 0, "reduce_only": 1, "no_new_position": 2}
        final_policy = max(policies, key=lambda p: priority.get(p, 2))
        final_trade_allowed = final_policy == "normal" and data_ok and risk_ok and operator_allowed

        results["final"] = {
            "trade_allowed": final_trade_allowed,
            "trade_policy": final_policy,
            "data_ok": data_ok,
            "risk_ok": risk_ok,
            "operator_allowed": operator_allowed,
            "global_ok": global_ok,
            "global_risk": results["steps"].get("global", {}).get("risk_level"),
            "portfolio_policy": portfolio_policy,
            "objective_pressure": (objective_status or {}).get("objective_pressure"),
        }

        # ── 写入决策层统一输出 ai:decision:latest (供执行层读取) ────
        # paper_trader 执行时读这个键, 避免决策层和执行层各判断各的。
        global_ctx = results["steps"].get("global", {})
        operator_plan = results["steps"].get("operator", {})
        decision_payload = {
            "trade_policy": final_policy,
            "trade_allowed": final_trade_allowed,
            "risk_level": global_ctx.get("risk_level", "low"),
            "global_risk_signals": global_ctx.get("risk_signals", []),
            "operator_summary": operator_plan.get("summary", ""),
            "operator_actions": operator_plan.get("actions", []),
            "operator_allowed": operator_allowed,
            "candidate_pool": candidate_pool,
            "target_weights": [],
            "rebalance_plan": [],
            "data_ok": data_ok,
            "risk_ok": risk_ok,
            "generated_at": _now(),
            "valid_until": (datetime.now() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S"),
            "date": _today(),
            "source": source,
            "risk_budget": {
                "max_position_pct": ((autonomous_cfg.get("risk") or {}).get("max_position_pct", 0.2)),
                "max_gross_exposure_pct": ((autonomous_cfg.get("risk") or {}).get("max_gross_exposure_pct", 95)),
                "max_position_count": ((autonomous_cfg.get("risk") or {}).get("max_position_count", 10)),
                "max_daily_turnover_pct": ((autonomous_cfg.get("risk") or {}).get("max_daily_turnover_pct", 35)),
            },
            "confidence": 0.8 if final_trade_allowed else 0.45,
            "model_version": provider,
            "prompt_version": "ai_loop.v1",
            "reason_codes": [
                f"policy:{final_policy}",
                f"data_ok:{data_ok}",
                f"risk_ok:{risk_ok}",
                f"operator_allowed:{operator_allowed}",
            ],
        }
        if objective_status:
            decision_payload["objective"] = objective_status
        if portfolio_plan:
            decision_payload.update({
                "portfolio_plan_id": portfolio_plan.get("plan_id"),
                "target_weights": portfolio_plan.get("target_weights", []),
                "rebalance_plan": portfolio_plan.get("rebalance_plan", []),
                "cash_target_pct": portfolio_plan.get("cash_target_pct"),
                "committee_summary": portfolio_plan.get("committee_summary", []),
                "portfolio_summary": portfolio_plan.get("summary", ""),
            })
        decision_payload = normalize_ai_decision(decision_payload)
        cache.set("ai:decision:latest", decision_payload)
        try:
            write_ai_decision(cache, decision_payload, source="ai_loop")
        except Exception:
            pass

        # ── Step 7.5: 统一自我验证 ───────────────────
        _log_step("自我验证", "running", "校验决策一致性+工具白名单...")
        verifier = None
        verifier_ok = False
        try:
            from scripts.ai_verifier import run_verifier
            verifier = run_verifier("quick")
            verifier_ok = verifier.get("overall") == "pass"
            results["steps"]["verifier"] = {
                "overall": verifier.get("overall"),
                "failed": verifier.get("failed", []),
                "checks": len(verifier.get("checks", [])),
            }
            _log_step("自我验证", "done" if verifier_ok else "error", f"overall={verifier.get('overall')}")
        except Exception as e:
            results["errors"].append(f"自我验证失败: {e}")
            verifier = {"success": False, "overall": "fail", "date": _today(), "generated_at": _now(), "failed": ["verifier_exception"], "error": str(e)[:200]}
            cache.set("ai:verifier:latest", verifier)
            results["steps"]["verifier"] = {"overall": "fail", "failed": ["verifier_exception"], "checks": 0}
            _log_step("自我验证", "error", str(e)[:80])

        # 本轮 verifier 必须通过才允许后续高风险工具。失败时同步收紧统一决策输出。
        decision_after_verify = cache.get("ai:decision:latest") or {}
        decision_after_verify["verifier_ok"] = verifier_ok
        if not verifier_ok:
            decision_after_verify["trade_allowed"] = False
            decision_after_verify["trade_policy"] = "no_new_position"
            decision_after_verify.setdefault("reason_codes", []).append("verifier_failed")
            results["final"]["trade_allowed"] = False
        decision_after_verify = normalize_ai_decision(decision_after_verify)
        cache.set("ai:decision:latest", decision_after_verify)
        try:
            write_ai_decision(cache, decision_after_verify, source="ai_loop_verifier")
        except Exception:
            pass

        # ── Step 8: 经验沉淀 ─────────────────────────
        try:
            from scripts.ai_memory import append_memory, summarize_memory
            mem = append_memory(
                "ai_loop",
                f"闭环完成: policy={final_policy} data_ok={data_ok} risk_ok={risk_ok} verifier={(verifier or {}).get('overall')} errors={len(results['errors'])}",
                source="ai_loop",
                importance="high" if results["errors"] or (verifier and verifier.get("overall") != "pass") else "medium",
                meta={"source": source, "final": results.get("final"), "verifier_failed": (verifier or {}).get("failed", [])},
            )
            summary = summarize_memory()
            results["memory"] = {"total": mem.get("stats", {}).get("total"), "summary_at": summary.get("generated_at")}
        except Exception:
            pass

        # ── Step 9: (可选) 通过工具执行器触发模拟盘交易 ─────────────
        if trigger_paper and results["final"].get("trade_allowed") and verifier_ok:
            _log_step("工具执行器", "running", "白名单触发 paper_trade_once...")
            try:
                from scripts.ai_action_executor import run_executor
                executor = run_executor(source=source, allowed_tools=["paper_trade_once"], dry_run=False, provider=provider)
                results["steps"]["tool_executor"] = {
                    "status": executor.get("status"),
                    "actions": len(executor.get("actions", [])),
                    "success": executor.get("success"),
                }
                _log_step("工具执行器", "done" if executor.get("success") else "error", f"actions={len(executor.get('actions', []))}")
            except Exception as e:
                results["errors"].append(f"工具执行器失败: {e}")
                _log_step("工具执行器", "error", str(e)[:80])
        else:
            _log_step("工具执行器", "skip", f"policy={final_policy}, 不触发交易")

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
