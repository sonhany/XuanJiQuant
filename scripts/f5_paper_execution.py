"""Run one deterministic F5 simulation cycle."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant.paper_execution.runtime import build_runtime_service


def main() -> int:
    parser = argparse.ArgumentParser(description="F5 deterministic paper execution")
    parser.add_argument("--once", action="store_true", help="run exactly one due cycle")
    parser.add_argument("--as-of", default="", help="fixed ISO date/time for controlled replay")
    args = parser.parse_args()
    if not args.once:
        parser.error("only --once is supported")
    as_of = datetime.fromisoformat(args.as_of) if args.as_of else datetime.now()
    result = build_runtime_service().run_due(as_of)
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
