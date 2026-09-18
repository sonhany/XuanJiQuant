"""Run one current-time F5 intraday paper cycle without user order inputs."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant.paper_execution.runtime import build_runtime_service


def main() -> int:
    parser = argparse.ArgumentParser(description="F5 intraday paper execution")
    parser.add_argument("--once", action="store_true", help="run exactly one current-time cycle")
    args = parser.parse_args()
    if not args.once:
        parser.error("only --once is supported")
    result = build_runtime_service().run_intraday(datetime.now())
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

