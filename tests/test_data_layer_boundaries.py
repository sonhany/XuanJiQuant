import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _imports(relative: str) -> set[str]:
    modules = set()
    source = (ROOT / relative).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_data_sync_has_no_retired_control_plane_dependency():
    assert not any(module.startswith("quant.agent") for module in _imports("quant/data/sync_service.py"))


def test_tick_collection_uses_only_positions_watchlist_and_open_orders():
    source = (ROOT / "scripts" / "tick_collector.py").read_text(encoding="utf-8")
    assert "ai:screen" not in source
    assert "ai:execution" not in source


def test_paper_api_has_no_automatic_execution_or_data_repair_action():
    source = (ROOT / "server" / "routes" / "paper.mjs").read_text(encoding="utf-8")
    assert "automatic_execution_disabled" in source
    assert "auto_fix" not in source
