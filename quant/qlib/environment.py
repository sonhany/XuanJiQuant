from __future__ import annotations

import importlib.util
import platform
import sys
from pathlib import Path

from quant.qlib.paths import DEFAULT_DATA_ROOT


SYSTEM_PYTHON = Path(
    r"C:\Users\HYSHEN\AppData\Local\Programs\Python\Python311\python.exe"
)
DEFAULT_VENV_DIR = Path(__file__).resolve().parents[2] / ".venv-qlib"


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def inspect_environment(
    venv_dir: Path = DEFAULT_VENV_DIR,
    data_root: Path = DEFAULT_DATA_ROOT,
) -> dict:
    venv_dir = Path(venv_dir).resolve()
    data_root = Path(data_root).resolve()
    python_path = venv_dir / "Scripts" / "python.exe"
    running_inside_venv = Path(sys.executable).resolve() == python_path
    return {
        "system_python_required": "3.11",
        "system_python": str(SYSTEM_PYTHON),
        "system_python_exists": SYSTEM_PYTHON.exists(),
        "inherits_system_site_packages": False,
        "venv_dir": str(venv_dir),
        "venv_python": str(python_path),
        "venv_ready": python_path.exists(),
        "data_root": str(data_root),
        "data_root_exists": data_root.exists(),
        "running_python": sys.version.split()[0],
        "running_inside_venv": running_inside_venv,
        "platform": platform.platform(),
        "packages": {
            "qlib": _module_available("qlib"),
            "lightgbm": _module_available("lightgbm"),
            "pyarrow": _module_available("pyarrow"),
            "torch": _module_available("torch"),
        },
    }
