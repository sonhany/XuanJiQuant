"""AI 经验记忆 — 统一沉淀、摘要和压缩。

记忆是总控上下文, 不覆盖硬风控规则。
"""
import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache

cache = create_cache()
LESSONS_KEY = "ai:memory:lessons"
SUMMARY_KEY = "ai:memory:summary"
STATS_KEY = "ai:memory:stats"
LOG_KEY = "ai:memory:log"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def _normalize(item: dict) -> dict:
    if not isinstance(item, dict):
        item = {"content": str(item)}
    out = dict(item)
    out.setdefault("date", _today())
    out.setdefault("time", out.get("created_at") or out.get("generated_at") or _now())
    out.setdefault("type", out.get("category") or "lesson")
    out.setdefault("source", out.get("type") or "unknown")
    out.setdefault("importance", "medium")
    out.setdefault("content", "")
    return out


def _score(item: dict) -> int:
    weight = {"high": 3, "medium": 2, "low": 1}.get(str(item.get("importance", "medium")), 2)
    return weight


def append_memory(mem_type: str, content: str, source: str = "system", importance: str = "medium", meta: dict = None) -> dict:
    """追加一条经验记忆, 并刷新统计。"""
    lessons = [_normalize(x) for x in (cache.get(LESSONS_KEY) or [])]
    item = {
        "date": _today(),
        "time": _now(),
        "type": mem_type,
        "source": source,
        "importance": importance,
        "content": str(content or "")[:1000],
        "meta": meta or {},
    }
    lessons.append(item)
    lessons = compact_items(lessons, max_items=100)
    cache.set(LESSONS_KEY, lessons)
    stats = _build_stats(lessons)
    cache.set(STATS_KEY, stats)
    log = cache.get(LOG_KEY) or []
    log.append({"time": _now(), "event": "append", "type": mem_type, "source": source})
    cache.set(LOG_KEY, log[-50:])
    return {"success": True, "item": item, "stats": stats}


def compact_items(items: list, max_items: int = 80) -> list:
    normalized = [_normalize(x) for x in items]
    if len(normalized) <= max_items:
        return normalized
    recent_keep = max(20, max_items // 2)
    recent = normalized[-recent_keep:]
    older = normalized[:-recent_keep]
    older_sorted = sorted(enumerate(older), key=lambda p: (_score(p[1]), p[0]), reverse=True)
    selected_idx = sorted(i for i, _ in older_sorted[: max_items - recent_keep])
    return [older[i] for i in selected_idx] + recent


def _build_stats(lessons: list) -> dict:
    sources = Counter(str(x.get("source", "unknown")) for x in lessons)
    types = Counter(str(x.get("type", "lesson")) for x in lessons)
    latest = lessons[-1] if lessons else None
    return {
        "success": True,
        "total": len(lessons),
        "sources": dict(sources),
        "types": dict(types),
        "latest_at": latest.get("time") if latest else None,
        "updated_at": _now(),
    }


def summarize_memory(provider: str = None) -> dict:
    """生成轻量摘要。provider 预留给未来 LLM 摘要, 当前默认规则摘要。"""
    lessons = [_normalize(x) for x in (cache.get(LESSONS_KEY) or [])]
    recent = lessons[-12:]
    high = [x for x in lessons if x.get("importance") == "high"][-5:]
    lines = []
    if recent:
        lines.append("最近经验: " + "；".join(str(x.get("content", ""))[:80] for x in recent[-5:]))
    if high:
        lines.append("高重要性: " + "；".join(str(x.get("content", ""))[:80] for x in high))
    summary = {
        "success": True,
        "provider": provider or "rules",
        "generated_at": _now(),
        "total": len(lessons),
        "summary": "\n".join(lines) if lines else "暂无经验记忆。",
        "recent": recent[-5:],
    }
    cache.set(SUMMARY_KEY, summary)
    cache.set(STATS_KEY, _build_stats(lessons))
    return summary


def compact_memory(max_items: int = 80) -> dict:
    lessons = [_normalize(x) for x in (cache.get(LESSONS_KEY) or [])]
    before = len(lessons)
    compacted = compact_items(lessons, max_items=max_items)
    cache.set(LESSONS_KEY, compacted)
    stats = _build_stats(compacted)
    cache.set(STATS_KEY, stats)
    summary = summarize_memory()
    log = cache.get(LOG_KEY) or []
    log.append({"time": _now(), "event": "compact", "before": before, "after": len(compacted)})
    cache.set(LOG_KEY, log[-50:])
    return {"success": True, "before": before, "after": len(compacted), "stats": stats, "summary": summary}


def get_memory_status() -> dict:
    lessons = [_normalize(x) for x in (cache.get(LESSONS_KEY) or [])]
    stats = cache.get(STATS_KEY) or _build_stats(lessons)
    summary = cache.get(SUMMARY_KEY) or summarize_memory()
    return {
        "success": True,
        "stats": stats,
        "summary": summary,
        "recent": lessons[-10:],
        "log": (cache.get(LOG_KEY) or [])[-20:],
    }


def main():
    parser = argparse.ArgumentParser(description="AI 经验记忆")
    parser.add_argument("--status", action="store_true", help="读取记忆状态")
    parser.add_argument("--compact", action="store_true", help="压缩记忆")
    parser.add_argument("--summary", action="store_true", help="刷新摘要")
    parser.add_argument("--max-items", type=int, default=80)
    args = parser.parse_args()
    if args.compact:
        out = compact_memory(args.max_items)
    elif args.summary:
        out = summarize_memory()
    else:
        out = get_memory_status()
    print(json.dumps(out, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
