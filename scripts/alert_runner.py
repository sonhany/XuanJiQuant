"""Alert Engine — 量化系统监控告警引擎

监控项目：
  1. 系统健康（各层进程、数据完整性）
  2. 持仓风险（VaR、集中度、暴露度）
  3. 盈亏预警（单股/总仓位阈值触发）
  4. 数据质量（K线缺失、因子失效）
  5. 追踪止损（持仓价格回落触发）

Alert Levels: info / warning / critical
Alert States:  active / acknowledged / resolved / silenced
"""
import sys, json, os, time, logging
from datetime import datetime
from typing import Optional, Dict, List, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger("alerts")

cache = create_cache()
ALERT_KEY     = "alerts:records"   # List[AlertRecord]
ALERT_RULES   = "alerts:rules"     # Dict[rule_id, AlertRule]
COUNTER_KEY   = "alerts:counter"   # global alert counter

DEFAULT_RULES = [
    {
        "id": "sys_health",
        "name": "系统健康",
        "desc": "任一系统层异常时触发",
        "level": "critical",
        "category": "system",
        "condition": "health_check",
        "threshold": 1,
        "enabled": True,
    },
    {
        "id": "var_threshold",
        "name": "VaR 超限",
        "desc": "日 VaR 超过 3% 时触发",
        "level": "warning",
        "category": "risk",
        "condition": "var_above",
        "threshold": 3.0,
        "enabled": True,
    },
    {
        "id": "position_loss",
        "name": "持仓亏损预警",
        "desc": "单只股票浮亏超 8%",
        "level": "warning",
        "category": "pnl",
        "condition": "position_loss_above",
        "threshold": 8.0,
        "enabled": True,
    },
    {
        "id": "total_loss",
        "name": "总资产亏损预警",
        "desc": "总权益浮亏超 10%",
        "level": "critical",
        "category": "pnl",
        "condition": "total_loss_above",
        "threshold": 10.0,
        "enabled": True,
    },
    {
        "id": "concentration",
        "name": "持仓集中度预警",
        "desc": "单只股票占总权益超 30%",
        "level": "warning",
        "category": "risk",
        "condition": "concentration_above",
        "threshold": 30.0,
        "enabled": True,
    },
    {
        "id": "kline_missing",
        "name": "K线数据缺失",
        "desc": "任一持仓股当日无新K线",
        "level": "warning",
        "category": "data",
        "condition": "kline_missing",
        "threshold": 1,
        "enabled": True,
    },
    {
        "id": "data_stale",
        "name": "行情数据过期",
        "desc": "最新K线日期早于今天(工作日)，数据未更新",
        "level": "critical",
        "category": "data",
        "condition": "data_stale",
        "threshold": 0,
        "enabled": True,
    },
    {
        "id": "stop_loss_triggered",
        "name": "追踪止损触发",
        "desc": "持仓触发预设的追踪止损",
        "level": "critical",
        "category": "execution",
        "condition": "stop_loss",
        "threshold": 1,
        "enabled": True,
    },
]


def _now_ts() -> float:
    return time.time()


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _uid(prefix: str = "A") -> str:
    cnt_raw = cache.get(COUNTER_KEY) or 0
    cnt = int(cnt_raw) + 1
    cache.set(COUNTER_KEY, cnt)
    return f"{prefix}{cnt:06d}"


# ── Data Loaders ───────────────────────────────────────

def _get_health() -> Optional[dict]:
    try:
        return cache.get("health:last") or {}
    except Exception:
        return {}


def _get_positions() -> List[dict]:
    try:
        exec_state = cache.get("execution:state") or {}
        return exec_state.get("positions", {})
    except Exception:
        return []


def _get_exec_status() -> dict:
    try:
        exec_state = cache.get("execution:state") or {}
        total_mv = sum(
            p.get("quantity", 0) * p.get("current_price", 0)
            for p in exec_state.get("positions", {}).values()
        )
        total_eq = exec_state.get("cash", 0) + total_mv
        init = exec_state.get("initial_capital", 1_000_000)
        return {
            "cash": exec_state.get("cash", 0),
            "market_value": total_mv,
            "total_equity": total_eq,
            "total_pnl_pct": abs(total_eq - init) / init * 100 * (-1 if total_eq < init else 1),
            "positions": list(exec_state.get("positions", {}).values()),
        }
    except Exception:
        return {}


def _get_stops() -> dict:
    try:
        return cache.get("execution:stops") or {}
    except Exception:
        return {}


# ── Alert Evaluation ────────────────────────────────────

def _eval_health_check(rule: dict) -> List[dict]:
    """系统健康检查"""
    health = _get_health()
    alerts = []
    if not health:
        return alerts
    # 检查各层状态
    for layer, info in health.items():
        if isinstance(info, dict) and info.get("status") in ("error", "warning"):
            alerts.append({
                "level": "critical",
                "title": f"系统层异常: {layer}",
                "message": f"{layer} 层状态: {info.get('status')}",
                "value": info.get("status"),
            })
    return alerts


def _eval_var_above(rule: dict) -> List[dict]:
    """VaR 超限"""
    try:
        risk_state = cache.get("risk:state") or {}
        var = abs(risk_state.get("var_95", 0))
        if var > rule.get("threshold", 3.0):
            return [{"level": "warning", "title": "VaR 超限",
                     "message": f"日 VaR {var:.2f}% 超过阈值 {rule['threshold']}%",
                     "value": var}]
    except Exception:
        pass
    return []


def _eval_position_loss(rule: dict) -> List[dict]:
    """持仓亏损"""
    status = _get_exec_status()
    threshold = rule.get("threshold", 8.0)
    alerts = []
    for p in status.get("positions", []):
        if p.get("avg_price", 0) > 0:
            pnl_pct = (p.get("current_price", 0) - p["avg_price"]) / p["avg_price"] * 100
            if pnl_pct <= -threshold:
                alerts.append({
                    "level": "warning",
                    "title": f"持仓亏损预警: {p['code']}",
                    "message": f"{p['code']} 浮亏 {pnl_pct:.1f}%，超过 -{threshold}%",
                    "value": round(pnl_pct, 2),
                    "code": p["code"],
                })
    return alerts


def _eval_total_loss(rule: dict) -> List[dict]:
    """总资产亏损"""
    status = _get_exec_status()
    pnl_pct = status.get("total_pnl_pct", 0)
    threshold = rule.get("threshold", 10.0)
    if pnl_pct <= -threshold:
        return [{"level": "critical",
                 "title": "总资产亏损预警",
                 "message": f"总权益浮亏 {pnl_pct:.1f}%，超过 -{threshold}%",
                 "value": round(pnl_pct, 2)}]
    return []


def _eval_concentration(rule: dict) -> List[dict]:
    """集中度"""
    status = _get_exec_status()
    total_eq = status.get("total_equity", 1)
    threshold = rule.get("threshold", 30.0)
    alerts = []
    for p in status.get("positions", []):
        mv = p.get("quantity", 0) * p.get("current_price", 0)
        conc = mv / total_eq * 100 if total_eq else 0
        if conc >= threshold:
            alerts.append({
                "level": "warning",
                "title": f"集中度过高: {p['code']}",
                "message": f"{p['code']} 市值占比 {conc:.1f}%，超过 {threshold}%",
                "value": round(conc, 2),
                "code": p["code"],
            })
    return alerts


def _eval_data_stale(rule: dict) -> List[dict]:
    """行情数据过期检测 — 委托给统一入口 data_freshness。"""
    try:
        from scripts.data_freshness import is_data_stale, get_latest_kline_date, get_expected_date
        if not is_data_stale():
            return []
        latest = get_latest_kline_date()
        expected = get_expected_date()
        if not latest:
            return [{"level": "critical", "title": "行情数据缺失",
                     "message": "无法读取任何K线日期，数据库可能为空",
                     "value": 0}]
        days_behind = 0
        try:
            ld = datetime.strptime(latest, "%Y%m%d")
            ed = datetime.strptime(expected, "%Y%m%d")
            days_behind = (ed - ld).days
        except Exception:
            pass
        return [{"level": "critical", "title": "行情数据过期",
                 "message": f"最新K线 {latest} 落后预期 {expected} 共 {days_behind} 天，请运行 daily_update.py",
                 "value": days_behind}]
    except Exception:
        return []


def _eval_stop_loss(rule: dict) -> List[dict]:
    """追踪止损触发"""
    stops = _get_stops()
    alerts = []
    for code, info in stops.items():
        if info.get("activated"):
            alerts.append({
                "level": "critical",
                "title": f"追踪止损触发: {code}",
                "message": f"{code} 价格从最高 {info.get('highest_price')} 回落 {info.get('trailing_pct')}% 触发止损",
                "value": info.get("trailing_pct"),
                "code": code,
            })
    return alerts


EVAL_MAP = {
    "health_check":          _eval_health_check,
    "var_above":             _eval_var_above,
    "position_loss_above":   _eval_position_loss,
    "total_loss_above":      _eval_total_loss,
    "concentration_above":   _eval_concentration,
    "stop_loss":             _eval_stop_loss,
    "kline_missing":         lambda r: [],  # placeholder — done via cron
    "data_stale":            _eval_data_stale,
}


# ── Alert Management ───────────────────────────────────

def _load_rules() -> List[dict]:
    rules = cache.get(ALERT_RULES)
    if not rules:
        rules = {r["id"]: r for r in DEFAULT_RULES}
        cache.set(ALERT_RULES, rules)
    return rules


def _save_rules(rules: List[dict]):
    cache.set(ALERT_RULES, {r["id"]: r for r in rules})


def _load_alerts() -> List[dict]:
    raw = cache.get(ALERT_KEY)
    return raw if isinstance(raw, list) else []


def _save_alerts(alerts: List[dict]):
    cache.set(ALERT_KEY, alerts[-200:])  # keep last 200


def _interpret_alert(alert: dict) -> str:
    """调用 LLM 对告警做 1-2 句话解读。失败返回空字符串, 不影响告警。"""
    try:
        from scripts.llm_client import chat
        cfg = cache.get("paper:config") or {}
        llm_cfg = cfg.get("llm", {})
        if not llm_cfg.get("enabled") or not llm_cfg.get("interpret_alerts", True):
            return ""
        provider = llm_cfg.get("provider", "deepseek")
        timeout = int(llm_cfg.get("timeout", 25))
        title = alert.get("title", "告警")
        message = alert.get("message", "")
        level = alert.get("level", "warning")
        system = (
            "你是量化系统运维助手。用1-2句简洁中文解读告警原因和处置建议。"
            "不要编造数据, 不要重复告警原文, 不要展示推理过程。"
        )
        user = f"告警级别: {level}\n标题: {title}\n详情: {message}"
        r = chat(provider, system, user, temperature=0.2, timeout=max(timeout, 30), max_tokens=400, scene="alert")
        return r["text"] if r["success"] else ""
    except Exception as e:
        logger.debug(f"_interpret_alert failed: {e}")
        return ""


def _emit(alert: dict):
    """发送一条告警"""
    alerts = _load_alerts()
    record = {
        "id": _uid(),
        "created_at": _now_ts(),
        "created_at_str": _now_str(),
        "level": alert.get("level", "warning"),
        "title": alert.get("title", "告警"),
        "message": alert.get("message", ""),
        "category": alert.get("category", "system"),
        "rule_id": alert.get("rule_id"),
        "code": alert.get("code"),
        "value": alert.get("value"),
        "status": "active",
        "acknowledged_at": None,
        "resolved_at": None,
        "silenced_until": None,
    }
    # 对 warning/critical 级别告警追加 AI 解读 (可选, 失败留空)
    if record["level"] in ("warning", "critical"):
        record["ai_hint"] = _interpret_alert(alert)
    alerts.append(record)
    _save_alerts(alerts)
    logger.warning(f"[ALERT] [{record['level'].upper()}] {record['title']}: {record['message']}")
    return record


def _check_all_rules():
    """评估所有启用的规则，返回触发的新告警列表"""
    rules = _load_rules()
    new_alerts = []
    for rule in rules.values():
        if not rule.get("enabled", True):
            continue
        evaluator = EVAL_MAP.get(rule.get("condition", ""))
        if not evaluator:
            continue
        try:
            results = evaluator(rule)
            for r in results:
                r["category"] = rule.get("category", "system")
                r["rule_id"] = rule["id"]
                new_alerts.append(r)
        except Exception as e:
            logger.error(f"Rule {rule['id']} eval failed: {e}")
    # Deduplicate: 不重复发相同 rule+code 的未处理告警
    # active + acknowledged 都算重复，只有 resolved/silenced(未过期) 才能重发
    now = _now_ts()
    def _is_suppressing(a):
        st = a.get("status")
        if st in ("active", "acknowledged"):
            return True
        if st == "silenced":
            until = a.get("silenced_until") or 0
            return until > now
        return False
    existing = [a for a in _load_alerts() if _is_suppressing(a)]
    for new in new_alerts:
        is_dup = False
        for existing_a in existing:
            if (existing_a.get("rule_id") == new.get("rule_id") and
                    existing_a.get("code") == new.get("code")):
                is_dup = True
                break
        if not is_dup:
            _emit(new)

    # ── 自动恢复: 条件不再触发的 active 告警自动转为 resolved ──
    triggered_rule_ids = {r.get("rule_id") for r in new_alerts}
    triggered_keys = {(r.get("rule_id"), r.get("code")) for r in new_alerts}
    all_alerts = _load_alerts()
    auto_resolved = 0
    for a in all_alerts:
        if a.get("status") != "active":
            continue
        rid = a.get("rule_id")
        key = (rid, a.get("code"))
        # 如果该规则本轮未触发, 或该 rule+code 未触发, 自动恢复
        if rid not in triggered_rule_ids or key not in triggered_keys:
            a["status"] = "resolved"
            a["resolved_at"] = _now_ts()
            a["resolution"] = "auto_resolved"
            auto_resolved += 1
    if auto_resolved > 0:
        _save_alerts(all_alerts)
        logger.info(f"[ALERT] 自动恢复 {auto_resolved} 条已解除的告警")


# ── Action Handlers ────────────────────────────────────

def action_list(req):
    """返回告警列表，支持分页/过滤"""
    alerts = _load_alerts()
    status = req.get("status")  # active / acknowledged / resolved
    level  = req.get("level")   # info / warning / critical
    limit  = int(req.get("limit", 50))
    offset = int(req.get("offset", 0))
    if status:
        alerts = [a for a in alerts if a.get("status") == status]
    if level:
        alerts = [a for a in alerts if a.get("level") == level]
    alerts = sorted(alerts, key=lambda a: a["created_at"], reverse=True)
    total = len(alerts)
    page = alerts[offset:offset + limit]
    return {"success": True, "data": {
        "alerts": page,
        "total": total,
        "active_count": len([a for a in alerts if a.get("status") == "active"]),
        "critical_count": len([a for a in alerts if a.get("status") == "active" and a.get("level") == "critical"]),
    }}


def action_rules(req=None):
    """返回告警规则列表"""
    rules = _load_rules()
    return {"success": True, "data": list(rules.values())}


def action_update_rule(req):
    """更新规则（启用/禁用/修改阈值）"""
    rule_id = req.get("id")
    rules = _load_rules()
    if rule_id not in rules:
        return {"success": False, "error": f"规则 {rule_id} 不存在"}
    for k, v in req.items():
        if k in ("id", "name", "desc", "condition"):
            continue  # 不允许改核心字段
        rules[rule_id][k] = v
    _save_rules(list(rules.values()))
    return {"success": True, "data": rules[rule_id]}


def action_acknowledge(req):
    """确认告警"""
    alert_id = req.get("alert_id")
    alerts = _load_alerts()
    for a in alerts:
        if a["id"] == alert_id:
            a["status"] = "acknowledged"
            a["acknowledged_at"] = _now_ts()
            _save_alerts(alerts)
            return {"success": True, "data": a}
    return {"success": False, "error": "告警不存在"}


def action_resolve(req):
    """解决/关闭告警"""
    alert_id = req.get("alert_id")
    alerts = _load_alerts()
    for a in alerts:
        if a["id"] == alert_id:
            a["status"] = "resolved"
            a["resolved_at"] = _now_ts()
            _save_alerts(alerts)
            return {"success": True, "data": a}
    return {"success": False, "error": "告警不存在"}


def action_silence(req):
    """静默规则一段时间（秒）"""
    rule_id = req.get("rule_id")
    duration = float(req.get("duration", 3600))  # default 1h
    rules = _load_rules()
    if rule_id and rule_id in rules:
        rules[rule_id]["silenced_until"] = _now_ts() + duration
        rules[rule_id]["enabled"] = False
        _save_rules(list(rules.values()))
        return {"success": True, "data": {"rule_id": rule_id, "silenced_until": rules[rule_id]["silenced_until"]}}
    return {"success": False, "error": "规则不存在"}


def action_check(req=None):
    """手动触发一次所有规则评估（返回新触发的告警）"""
    _check_all_rules()
    active = [a for a in _load_alerts() if a.get("status") == "active"]
    return {"success": True, "data": {
        "active_count": len(active),
        "critical_count": len([a for a in active if a.get("level") == "critical"]),
    }}


def action_stats(req=None):
    """告警统计。兼容历史记录里 resolved_at 为字符串的情况。"""
    alerts = _load_alerts()
    today_start = time.time() - 86400

    def _ts(v):
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str) and v:
            try:
                return datetime.strptime(v[:19], "%Y-%m-%d %H:%M:%S").timestamp()
            except Exception:
                return 0.0
        return 0.0

    return {"success": True, "data": {
        "total": len(alerts),
        "active": len([a for a in alerts if a.get("status") == "active"]),
        "critical_active": len([a for a in alerts if a.get("status") == "active" and a.get("level") == "critical"]),
        "resolved_24h": len([a for a in alerts if a.get("status") == "resolved" and _ts(a.get("resolved_at")) > today_start]),
    }}


ACTIONS = {
    "list":          action_list,
    "rules":         action_rules,
    "update_rule":   action_update_rule,
    "acknowledge":   action_acknowledge,
    "resolve":       action_resolve,
    "silence":       action_silence,
    "check":         action_check,
    "stats":         action_stats,
}


if __name__ == "__main__":
    logger.info("alert_runner started")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            print(json.dumps({"success": False, "error": "invalid JSON"}))
            sys.stdout.flush()
            continue
        req_id = req.get("__id")
        action = req.get("action", "list")
        handler = ACTIONS.get(action)
        if not handler:
            out = {"success": False, "error": f"unknown action: {action}"}
            if req_id: out["__id"] = req_id
            print(json.dumps(out))
            sys.stdout.flush()
            continue
        try:
            result = handler(req)
            if req_id and isinstance(result, dict): result["__id"] = req_id
            print(json.dumps(result))
        except Exception as e:
            import traceback
            traceback.print_exc()
            out = {"success": False, "error": str(e)[:500]}
            if req_id: out["__id"] = req_id
            print(json.dumps(out))
        sys.stdout.flush()
