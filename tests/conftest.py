import os
import tempfile
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_PRODUCTION_DB = (_ROOT / "data" / "quant.db").resolve()
_TEST_DB_ROOT = None

configured_path = os.environ.get("QUANT_DB_PATH")
configured_db = Path(configured_path).resolve() if configured_path else None
if configured_db is None or configured_db == _PRODUCTION_DB:
    _TEST_DB_ROOT = tempfile.TemporaryDirectory(
        prefix="xuanji2-ai-pytest-",
        ignore_cleanup_errors=True,
    )
    os.environ["QUANT_DB_PATH"] = str(Path(_TEST_DB_ROOT.name) / "quant.db")


def pytest_unconfigure(config):
    del config
    if _TEST_DB_ROOT is not None:
        _TEST_DB_ROOT.cleanup()
