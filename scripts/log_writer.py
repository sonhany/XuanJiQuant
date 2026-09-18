"""Persistent stdin log writer for Node server logs.

Each input line is a JSON object:
  {"level": "INFO", "message": "...", "source": "server", "created_at": "..."}
The writer stores it in structured audit_events as event_type=server_log.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant.data.audit import write_audit_event
from quant.data.cache import create_cache


cache = create_cache()


def _write(event: dict) -> bool:
    payload = {
        "level": str(event.get("level") or ""),
        "message": str(event.get("message") or ""),
        "created_at": event.get("created_at") or time.strftime("%Y-%m-%d %H:%M:%S"),
        "meta": event.get("meta") or {},
    }
    return write_audit_event(
        cache,
        "server_log",
        payload,
        source=str(event.get("source") or "server"),
        ref_id=payload["level"],
    )


for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        event = json.loads(line)
        ok = _write(event if isinstance(event, dict) else {"message": str(event)})
        print(json.dumps({"success": bool(ok)}, ensure_ascii=False), flush=True)
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)[:300]}, ensure_ascii=False), flush=True)
