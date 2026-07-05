"""AI 受控自我更新 — 只生成提案, 不直接修改生产代码。"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache

cache = create_cache()
LATEST_KEY = "ai:updates:latest"
PROPOSALS_KEY = "ai:updates:proposals"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def _recent_errors() -> list:
    items = []
    for key in ("ai:loop:log", "ai:scheduler:log", "ai:tool_executor:log", "ai:verifier:log"):
        for row in (cache.get(key) or [])[-10:]:
            if not isinstance(row, dict):
                continue
            result = row.get("result") if isinstance(row.get("result"), dict) else {}
            has_error = (
                row.get("errors", 0)
                or row.get("overall") == "fail"
                or row.get("status") == "error"
                or row.get("error")
                or row.get("success") is False
                or result.get("success") is False
            )
            if has_error:
                items.append({"key": key, **row})
    return items[-20:]


def _build_rule_proposal() -> dict:
    errors = _recent_errors()
    verifier = cache.get("ai:verifier:latest") or {}
    report = cache.get("paper:report:latest") or {}
    factor_candidates = cache.get("ai:factor:candidates") or []
    strategy_candidates = cache.get("ai:strategy:candidates") or []
    failed_checks = verifier.get("failed", []) if isinstance(verifier, dict) else []

    title = "AI 自主闭环稳定性巡检提案"
    problem = "近期未发现严重错误, 建议继续观察并优化经验摘要。"
    risk = "low"
    files = ["scripts/ai_loop.py", "scripts/ai_operator.py", "scripts/ai_memory.py"]
    if failed_checks:
        problem = "统一自我验证存在失败项: " + ", ".join(failed_checks)
        risk = "medium"
        files = ["scripts/ai_verifier.py", "scripts/ai_loop.py", "scripts/ai_risk_agent.py"]
    elif errors:
        problem = "近期运行日志存在异常, 需要增强容错和状态可观测性。"
        risk = "medium"
        files = ["scripts/ai_scheduler.py", "scripts/ai_action_executor.py", "server/routes/paper.mjs"]
    elif len(factor_candidates) > 20 or len(strategy_candidates) > 20:
        problem = "候选因子/策略积累较多, 建议增加候选压缩和晋级复盘。"
        risk = "low"
        files = ["scripts/ai_factor_agent.py", "scripts/ai_strategy_agent.py", "scripts/ai_memory.py"]

    return {
        "id": f"proposal-{_today()}-{int(datetime.now().timestamp())}",
        "date": _today(),
        "generated_at": _now(),
        "status": "pending_review",
        "risk": risk,
        "title": title,
        "problem": problem,
        "impact": "仅生成改进提案, 不自动修改代码或生产配置。",
        "suggested_files": files,
        "recommendations": [
            "先运行 quick/full verifier 确认失败范围",
            "优先补充测试和状态审计, 再考虑行为改动",
            "所有策略/因子改动继续走 shadow 验证和回测门槛",
        ],
        "verification_commands": [
            "python -m py_compile scripts/ai_memory.py scripts/ai_verifier.py scripts/ai_action_executor.py scripts/ai_self_improver.py",
            "python scripts/ai_verifier.py --run --mode quick",
            "python scripts/verify_paper_rules.py",
        ],
        "rollback": "不直接改代码；若后续应用补丁, 使用 git diff/git checkout 或备份文件回滚。",
        "signals": {
            "recent_errors": errors[-5:],
            "failed_checks": failed_checks,
            "has_report": bool(report),
        },
    }


def propose_update(provider: str = None) -> dict:
    proposal = _build_rule_proposal()
    proposals = cache.get(PROPOSALS_KEY) or []
    proposals.append(proposal)
    proposals = proposals[-30:]
    cache.set(PROPOSALS_KEY, proposals)
    latest = {"success": True, "generated_at": _now(), "latest": proposal, "pending": len([p for p in proposals if p.get("status") == "pending_review"])}
    cache.set(LATEST_KEY, latest)
    try:
        from scripts.ai_memory import append_memory
        append_memory("self_improve", f"生成受控更新提案: {proposal['problem']}", source="ai_self_improver", importance=proposal.get("risk", "medium"))
    except Exception:
        pass
    return latest


def get_status() -> dict:
    proposals = cache.get(PROPOSALS_KEY) or []
    latest = cache.get(LATEST_KEY) or {"success": True, "latest": proposals[-1] if proposals else None, "pending": len(proposals)}
    return {"success": True, "latest": latest, "proposals": proposals[-10:]}


def main():
    parser = argparse.ArgumentParser(description="AI 受控自我更新")
    parser.add_argument("--propose", action="store_true", help="生成改进提案")
    parser.add_argument("--status", action="store_true", help="读取状态")
    parser.add_argument("--provider", default=None)
    args = parser.parse_args()
    out = propose_update(args.provider) if args.propose else get_status()
    print(json.dumps(out, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
