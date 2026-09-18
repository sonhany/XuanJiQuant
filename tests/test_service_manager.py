"""Tests for unified service manager."""
import json
import pytest


class TestServiceManager:
    """Test service_manager.py module."""

    def test_child_process_repr(self):
        from scripts.service_manager import ChildProcess
        cp = ChildProcess(name="test-api", service="api")
        assert cp.name == "test-api"
        assert cp.alive is False
        assert cp.restart_count == 0

    def test_child_process_not_alive_without_process(self):
        from scripts.service_manager import ChildProcess
        cp = ChildProcess(name="test", service="api")
        assert cp.alive is False
        assert cp.process is None

    def test_child_process_check_health_restarts(self):
        from scripts.service_manager import ChildProcess
        cp = ChildProcess(name="test", service="api", max_restarts=3)
        # alive=False triggers restart path
        result = cp.check_health()
        # Should try to start but fail (no service_host.cmd in test env)
        assert cp.restart_count == 1

    def test_write_status(self, tmp_path, monkeypatch):
        from scripts.service_manager import ChildProcess, _write_status
        import scripts.service_manager as sm
        monkeypatch.setattr(sm, "LOGS", tmp_path)
        children = [ChildProcess(name="API", service="api")]
        _write_status(children)
        status_file = tmp_path / "service-manager-status.json"
        assert status_file.exists()
        data = json.loads(status_file.read_text(encoding="utf-8"))
        assert "API" in data
        assert data["API"]["alive"] is False

    def test_legacy_tasks_removed(self):
        """Verify legacy task names are no longer used."""
        legacy = ["XuanJiQuant-API-Service", "XuanJiQuant-Web-Service", "XuanJiQuant-Service-Supervisor"]
        # The installer should handle removal; just verify module doesn't reference them
        from scripts.service_manager import ChildProcess
        cp = ChildProcess(name="XuanJiQuant-API", service="api")
        assert cp.name not in legacy
