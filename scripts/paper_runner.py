"""模拟盘只读投影进程。

自动执行入口已经关闭；本模块只读取历史状态、配置、进度、日志和报告。
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant.data.cache import create_cache


cache = create_cache()


def _config() -> dict:
    value = cache.get("paper:config") or {}
    return value if isinstance(value, dict) else {}


def action_status(_request=None) -> dict:
    return {
        "success": True,
        "data": {
            "status": cache.get("paper:status") or {},
            "config": _config(),
            "last_result": cache.get("paper:last_result"),
            "daemon": {"running": False, "retired": True},
            "automatic_execution": {
                "enabled": False,
                "reason": "automatic_execution_disabled",
            },
        },
    }


def action_get_config(_request=None) -> dict:
    return {"success": True, "data": _config()}


def action_set_config(request=None) -> dict:
    config = (request or {}).get("config")
    if not isinstance(config, dict):
        return {"success": False, "error": "invalid config"}
    cache.set("paper:config", config)
    return {"success": True, "data": config}


def action_progress(_request=None) -> dict:
    return {"success": True, "data": cache.get("paper:progress") or []}


def action_log(_request=None) -> dict:
    return {"success": True, "data": cache.get("paper:log") or []}


def action_report(_request=None) -> dict:
    return {"success": True, "data": cache.get("paper:report:latest") or {}}


def action_benchmark(_request=None) -> dict:
    return {"success": True, "data": cache.get("paper:benchmark") or {}}


def action_global_context_status(_request=None) -> dict:
    return {"success": True, "data": cache.get("global:context:latest") or {}}


ACTIONS = {
    "status": action_status,
    "get_config": action_get_config,
    "set_config": action_set_config,
    "progress": action_progress,
    "log": action_log,
    "report": action_report,
    "benchmark": action_benchmark,
    "global_context_status": action_global_context_status,
}


if __name__ == "__main__":
    for line in sys.stdin:
        try:
            request = json.loads(line)
            request_id = request.get("__id")
            handler = ACTIONS.get(request.get("action", "status"))
            result = handler(request) if handler else {
                "success": False,
                "error": "unsupported read action",
            }
            if request_id:
                result["__id"] = request_id
        except Exception as error:
            result = {"success": False, "error": str(error)[:500]}
        print(json.dumps(result, ensure_ascii=False, default=str), flush=True)
