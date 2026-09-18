import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


RETIRED_FILES = (
    "ai_tools.json",
    "server/ai_scheduler_manager.mjs",
    "components/AgentRuntimeStatus.tsx",
    "components/agentRuntimeLifecycle.ts",
    "components/AutonomousSchedulingDrawer.tsx",
    "scripts/agent_runner.py",
    "scripts/agent_control.py",
    "scripts/ai_scheduler.py",
    "scripts/ai_action_executor.py",
    "scripts/ai_verifier.py",
    "scripts/ai_memory.py",
    "scripts/ai_self_improver.py",
    "scripts/ai_data_agent.py",
    "scripts/ai_execution_agent.py",
    "scripts/ai_risk_agent.py",
    "scripts/ai_portfolio_planner.py",
    "scripts/ai_stock_screener.py",
    "scripts/ai_objective.py",
    "scripts/ai_status.py",
    "scripts/ai_validation_universe.py",
    "scripts/ai_factor_agent.py",
    "scripts/ai_strategy_agent.py",
)


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_agent_production_files_are_removed():
    assert not (ROOT / "quant" / "agent").exists()
    assert not [relative for relative in RETIRED_FILES if (ROOT / relative).exists()]


def test_active_python_has_no_quant_agent_imports():
    violations = []
    for path in [*ROOT.joinpath("quant").rglob("*.py"), *ROOT.joinpath("scripts").glob("*.py")]:
        if "test" in path.name.lower() or "graphify-out" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            module = ""
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
            elif isinstance(node, ast.Import):
                module = " ".join(alias.name for alias in node.names)
            if "quant.agent" in module:
                violations.append(str(path.relative_to(ROOT)))
    assert violations == []


def test_node_control_plane_has_no_agent_lifecycle_or_actions():
    combined = "\n".join(
        _source(path)
        for path in (
            "server/router.mjs",
            "server/watchdog.mjs",
            "server/routes/paper.mjs",
            "server/routes/workbench.mjs",
        )
    ).lower()
    for token in ("agent_runtime", "agent_control", "ai_scheduler", "ai_autonomous"):
        assert token not in combined


def test_web_has_no_agent_components_actions_or_current_state_copy():
    combined = "\n".join(
        _source(path)
        for path in (
            "components/DashboardPanel.tsx",
            "components/PaperPanel.tsx",
            "components/WorkbenchStatus.tsx",
            "lib/workbench-state.mjs",
            "lib/ui-workbench.mjs",
        )
    ).lower()
    for token in ("agentruntimestatus", "agent_runtime", "agent_control", "ai_scheduler", "等待 agent", "agent 自治", "agent 专属", "agent runtime"):
        assert token not in combined


def test_research_scheduler_does_not_import_retired_ai_factories():
    source = _source("scripts/research_training_scheduler.py")
    assert "ai_factor_agent" not in source
    assert "ai_strategy_agent" not in source


def test_execution_api_declares_automatic_order_writes_disabled():
    source = _source("server/routes/execution.mjs")
    assert "automatic_execution_disabled" in source


def test_tick_collection_does_not_consume_retired_decision_caches():
    source = _source("scripts/tick_collector.py")
    assert "ai:screen" not in source
    assert "ai:execution" not in source
