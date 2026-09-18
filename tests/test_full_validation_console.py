import os
import subprocess
import sys
from pathlib import Path


def test_validation_console_emits_utf8_on_windows_gbk_console():
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "gbk"

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from scripts.console_output import configure_utf8_stdio; "
                "configure_utf8_stdio(); print('✅ 全部通过')"
            ),
        ],
        env=env,
        capture_output=True,
        timeout=30,
        check=False,
    )

    diagnostic = (completed.stdout + completed.stderr).decode("utf-8", errors="replace")
    assert completed.returncode == 0, diagnostic
    assert "✅ 全部通过".encode("utf-8") in completed.stdout


def test_api_verifier_configures_utf8_before_printing_status_icons():
    source = Path("scripts/test_api.py").read_text(encoding="utf-8")
    assert "from console_output import configure_utf8_stdio" in source
    assert "configure_utf8_stdio()" in source


def test_full_validation_reads_published_factor_projection_not_retired_cache():
    source = Path("scripts/full_validation.py").read_text(encoding="utf-8")
    assert "cache.get('factor:snapshot')" not in source
    assert "factor_snapshot_latest.json" in source
    assert "_published_factor_snapshot()" in source
