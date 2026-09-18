"""Persistent runner for Jin10 MCP read-only data actions."""
from __future__ import annotations

import json
import hashlib
import html as html_lib
import os
import re
import sys
import time
import copy
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant.data.jin10_mcp import Jin10MCPClient, MCPProtocolError, normalize_code, page_info


class ResilientJin10MCPClient(Jin10MCPClient):
    """Retry one operation with a fresh MCP session after explicit expiry."""

    @staticmethod
    def _is_expired_session_error(exc: MCPProtocolError) -> bool:
        text = str(exc).lower()
        return "session" in text and any(marker in text for marker in ("not found", "expired", "invalid"))

    def _with_session_retry(self, operation):
        try:
            return operation()
        except MCPProtocolError as exc:
            if not self._session_id or not self._is_expired_session_error(exc):
                raise
            self._initialized = False
            self._session_id = ""
            return operation()

    def list_tools(self) -> dict[str, Any]:
        operation = super().list_tools
        return self._with_session_retry(operation)

    def list_resources(self) -> dict[str, Any]:
        operation = super().list_resources
        return self._with_session_retry(operation)

    def read_resource(self, uri: str) -> dict[str, Any]:
        operation = super().read_resource
        return self._with_session_retry(lambda: operation(uri))

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        operation = super().call_tool
        return self._with_session_retry(lambda: operation(name, arguments))


ALLOWED_ACTIONS = {
    "status",
    "tools",
    "resources",
    "codes",
    "quote",
    "quotes",
    "kline",
    "flash",
    "flash_detail",
    "news",
    "news_detail",
    "calendar",
    "interpret_flash",
}

CACHE_TTL_SECONDS = {
    "status": 300,
    "tools": 300,
    "resources": 300,
    "codes": 600,
    "quote": 20,
    "quotes": 300,
    "kline": 60,
    "flash": 30,
    "flash_detail": 300,
    "news": 60,
    "news_detail": 300,
    "calendar": 300,
}
_READ_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def ok(data: Any = None, **extra) -> dict[str, Any]:
    out = {"success": True}
    if data is not None:
        out["data"] = data
    out.update(extra)
    return out


def fail(error: str, **extra) -> dict[str, Any]:
    out = {"success": False, "error": error}
    out.update(extra)
    return out


def _client() -> ResilientJin10MCPClient:
    return ResilientJin10MCPClient.from_env()


def _cache():
    from quant.data.cache import create_cache

    return create_cache()


def _tool_data(result: dict[str, Any], include_content: bool = False) -> dict[str, Any]:
    if not result.get("success"):
        return result
    out = ok(result.get("data") or {})
    if result.get("page"):
        out["page"] = result.get("page")
    if include_content and result.get("content"):
        out["content"] = result.get("content")
    return out


def _cache_key(action: str, req: dict[str, Any], *, include_content: bool = False) -> str:
    payload = {
        "action": action,
        "code": req.get("code"),
        "codes": req.get("codes"),
        "time": req.get("time"),
        "count": req.get("count"),
        "cursor": req.get("cursor"),
        "pages": req.get("pages"),
        "keyword": req.get("keyword"),
        "id": req.get("id"),
        "url": req.get("url"),
        "include_content": include_content,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()


def _cached_tool_data(action: str, req: dict[str, Any], loader, *, ttl: int | None = None,
                      include_content: bool = False) -> dict[str, Any]:
    ttl = CACHE_TTL_SECONDS.get(action, 30) if ttl is None else ttl
    key = _cache_key(action, req, include_content=include_content)
    now = time.time()
    if not req.get("force_refresh"):
        cached = _READ_CACHE.get(key)
        if cached and now - cached[0] <= ttl:
            out = copy.deepcopy(cached[1])
            out["cache_hit"] = True
            out["cache_age_sec"] = round(now - cached[0], 3)
            return out
    data = loader()
    if isinstance(data, dict) and data.get("success"):
        data = copy.deepcopy(data)
        data["cache_hit"] = False
        _READ_CACHE[key] = (now, copy.deepcopy(data))
    return data


def _page_limit(req: dict[str, Any], maximum: int = 10) -> int:
    try:
        requested = int(req.get("pages") or 1)
    except (TypeError, ValueError):
        requested = 1
    return max(1, min(requested, maximum))


_VOID_HTML_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}
_BLOCK_HTML_TAGS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"}


def _class_names(attrs) -> set[str]:
    for key, value in attrs:
        if key == "class":
            return {part for part in str(value or "").split() if part}
    return set()


def _attr(attrs, name: str) -> str:
    for key, value in attrs:
        if key == name:
            return str(value or "")
    return ""


def _clean_text(value: Any) -> str:
    text = html_lib.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _has_meaningful_text(value: Any, minimum: int = 20) -> bool:
    text = _clean_text(value)
    meaningful = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", text)
    return len(meaningful) >= minimum


def _validated_jin10_url(url: str, *, kind: str) -> str:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme != "https":
        raise ValueError(f"invalid Jin10 {kind} detail URL")
    host = (parsed.hostname or "").lower()
    if kind == "flash":
        valid = host == "flash.jin10.com" and bool(re.fullmatch(r"/detail/\d{14,24}", parsed.path))
    else:
        valid = host == "xnews.jin10.com" and bool(re.fullmatch(r"/details/\d{1,20}", parsed.path))
    if not valid:
        raise ValueError(f"invalid Jin10 {kind} detail URL")
    return parsed.geturl()


def _validated_media_url(url: str) -> str:
    parsed = urlparse(html_lib.unescape(str(url or "").strip()))
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == "jin10.com" or host.endswith(".jin10.com")):
        return ""
    return parsed.geturl()


def _fetch_jin10_html(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (XuanJi Jin10 detail reader)",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urlopen(request, timeout=15) as response:
        final_url = response.geturl()
        final_host = (urlparse(final_url).hostname or "").lower()
        if not (final_host == "jin10.com" or final_host.endswith(".jin10.com")):
            raise ValueError("Jin10 detail redirected to an untrusted host")
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("Jin10 detail page is too large")
        charset = response.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")


class _FlashDetailParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title_depth = 0
        self.title_parts: list[str] = []
        self.images: list[str] = []

    def handle_starttag(self, tag, attrs):
        classes = _class_names(attrs)
        if tag == "div" and "content-title" in classes and self.title_depth == 0:
            self.title_depth = 1
        elif self.title_depth and tag not in _VOID_HTML_TAGS:
            self.title_depth += 1

        if tag == "img" and "mini-program-card__cover-image" in classes:
            src = _validated_media_url(_attr(attrs, "src"))
            if src and src not in self.images:
                self.images.append(src)

    def handle_endtag(self, tag):
        if self.title_depth:
            self.title_depth -= 1

    def handle_data(self, data):
        if self.title_depth:
            self.title_parts.append(data)


class _NewsDetailParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.capture_depth = 0
        self.parts: list[str] = []
        self.images: list[str] = []

    def _break(self):
        if self.parts and self.parts[-1] != "\n":
            self.parts.append("\n")

    def handle_starttag(self, tag, attrs):
        classes = _class_names(attrs)
        if self.capture_depth == 0 and "jin10-news-cdetails-content" in classes:
            self.capture_depth = 1
            return
        if not self.capture_depth:
            return
        if tag in _BLOCK_HTML_TAGS or tag == "br":
            self._break()
        if tag == "img":
            src = _validated_media_url(_attr(attrs, "src"))
            if src and src not in self.images:
                self.images.append(src)
        if tag not in _VOID_HTML_TAGS:
            self.capture_depth += 1

    def handle_endtag(self, tag):
        if not self.capture_depth:
            return
        if tag in _BLOCK_HTML_TAGS:
            self._break()
        self.capture_depth -= 1

    def handle_data(self, data):
        if not self.capture_depth:
            return
        text = re.sub(r"\s+", " ", data).strip()
        if not text:
            return
        if self.parts and self.parts[-1] != "\n":
            prev = self.parts[-1][-1:] if self.parts[-1] else ""
            if prev and prev.isascii() and text[:1].isascii():
                self.parts.append(" ")
        self.parts.append(text)


def _extract_flash_detail_html(page_html: str, url: str) -> dict[str, Any]:
    parser = _FlashDetailParser()
    parser.feed(page_html)
    title = _clean_text("".join(parser.title_parts))
    return {
        "title": title,
        "content": title,
        "url": url,
        "image_url": parser.images[0] if parser.images else "",
        "images": parser.images,
    }


def _extract_news_detail_html(page_html: str, url: str) -> dict[str, Any]:
    parser = _NewsDetailParser()
    parser.feed(page_html)
    content = _clean_text("".join(parser.parts))
    return {
        "content": content,
        "url": url,
        "image_url": parser.images[0] if parser.images else "",
        "images": parser.images,
    }


def _news_item_from_tool_result(result: dict[str, Any]) -> dict[str, Any]:
    payload = result.get("data") if isinstance(result, dict) else {}
    if not isinstance(payload, dict):
        return {}
    item = payload.get("data")
    return dict(item) if isinstance(item, dict) else dict(payload)


def _load_news_detail(client, news_id: str) -> dict[str, Any]:
    result = client.call_tool("get_news", {"id": news_id})
    item = _news_item_from_tool_result(result)
    item["id"] = str(item.get("id") or news_id)
    item["title"] = _clean_text(item.get("title"))
    item["introduction"] = _clean_text(item.get("introduction"))
    item["content"] = _clean_text(item.get("content"))
    item["url"] = _validated_jin10_url(
        item.get("url") or f"https://xnews.jin10.com/details/{news_id}",
        kind="news",
    )
    if result.get("success") and _has_meaningful_text(item.get("content")):
        item.setdefault("images", [])
        item.setdefault("image_url", "")
        return ok({"item": item, "source": "mcp"})

    page_html = _fetch_jin10_html(item["url"])
    fallback = _extract_news_detail_html(page_html, item["url"])
    fallback.update({
        "id": item["id"],
        "title": item["title"],
        "introduction": item["introduction"],
    })
    if not _has_meaningful_text(fallback.get("content")):
        return fail("Jin10 news detail did not contain readable article content")
    return ok({"item": fallback, "source": "official_page_fallback"})


def _load_flash_detail(url: str) -> dict[str, Any]:
    safe_url = _validated_jin10_url(url, kind="flash")
    item = _extract_flash_detail_html(_fetch_jin10_html(safe_url), safe_url)
    if not item.get("image_url") and not _has_meaningful_text(item.get("content"), minimum=4):
        return fail("Jin10 flash detail did not contain readable content")
    return ok({"item": item, "source": "official_page"})


def _interpret_flash(req: dict[str, Any]) -> dict[str, Any]:
    text = str(req.get("content") or req.get("title") or "").strip()
    if not text:
        return fail("content is required")
    text = text[:1800]
    digest = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:24]
    c = _cache()
    from scripts.llm_registry import resolve_llm_selection

    effective = resolve_llm_selection(cache=c, scene="jin10_flash_interpret")
    provider = effective["provider"]
    model = effective["model"]
    cache_key = f"ai:jin10_interpret:{provider}:{model}:{digest}"
    cached = c.get(cache_key)
    if isinstance(cached, dict) and cached.get("interpretation"):
        cached["cached"] = True
        return ok(cached)

    cfg = c.get("paper:config") or {}
    llm_cfg = cfg.get("llm") if isinstance(cfg.get("llm"), dict) else {}
    timeout = int(llm_cfg.get("timeout", 45) or 45)
    flash = {
        "id": req.get("id"),
        "time": req.get("time"),
        "url": req.get("url"),
        "content": text,
    }

    system = (
        "你是AI量化交易系统中的资讯解读员。只返回合法JSON对象, 不输出Markdown。"
        "你的输出只能作为影子信号和人工参考, 不能直接触发交易, 不能建议绕过风控网关。"
    )
    user = (
        "请解读以下金十市场快讯, 输出JSON字段: "
        "{\"summary\":\"一句话摘要\",\"market_impact\":\"positive|negative|mixed|neutral\","
        "\"risk_level\":\"low|medium|high\",\"related_assets\":[\"...\"],"
        "\"related_sectors\":[\"...\"],\"action_hint\":\"watch_only|reduce_risk|manual_review\","
        "\"reason_codes\":[\"macro_risk|policy_event|sector_theme|liquidity|commodity|fx|geopolitical|other\"],"
        "\"rationale\":\"不超过120字解释\"}。\n"
        f"快讯: {json.dumps(flash, ensure_ascii=False, default=str)}"
    )
    from scripts.llm_client import chat_json
    from quant.data.audit import write_audit_event

    result: dict[str, Any] = {}
    last_error = ""
    for attempt in range(3):
        result = chat_json(
            provider,
            system,
            user,
            temperature=0.15,
            timeout=max(timeout, 45),
            max_tokens=1200,
            scene="jin10_flash_interpret",
            model=model,
        )
        if result.get("success"):
            break
        last_error = str(result.get("error") or "LLM interpretation failed")
        if ("429" in last_error or "Too Many Requests" in last_error) and attempt < 2:
            time.sleep(2 * (attempt + 1))
            continue
        break
    if not result.get("success"):
        error_payload = {
            "provider": provider,
            "model": model,
            "model_source": effective["source"],
            "flash": flash,
            "error": last_error or "LLM interpretation failed",
            "cache_key": cache_key,
        }
        write_audit_event(c, "jin10_ai_interpretation_failed", error_payload, source="jin10_mcp", ref_id=str(req.get("id") or req.get("time") or "flash"))
        return fail(error_payload["error"], provider=provider, model=model)

    data = result.get("data") or {}
    if not isinstance(data, dict):
        return fail("LLM returned invalid interpretation", provider=provider)

    normalized = {
        "summary": str(data.get("summary") or "")[:240],
        "market_impact": str(data.get("market_impact") or "neutral"),
        "risk_level": str(data.get("risk_level") or "low"),
        "related_assets": [str(x)[:40] for x in (data.get("related_assets") or [])[:12] if x],
        "related_sectors": [str(x)[:40] for x in (data.get("related_sectors") or [])[:12] if x],
        "action_hint": str(data.get("action_hint") or "watch_only"),
        "reason_codes": [str(x)[:60] for x in (data.get("reason_codes") or [])[:12] if x],
        "rationale": str(data.get("rationale") or "")[:300],
        "safety_boundary": "shadow_signal_only_not_order_trigger",
    }
    if normalized["market_impact"] not in {"positive", "negative", "mixed", "neutral"}:
        normalized["market_impact"] = "neutral"
    if normalized["risk_level"] not in {"low", "medium", "high"}:
        normalized["risk_level"] = "low"
    if normalized["action_hint"] not in {"watch_only", "reduce_risk", "manual_review"}:
        normalized["action_hint"] = "watch_only"

    payload = {
        "provider": provider,
        "model": result.get("model") or model,
        "model_source": effective["source"],
        "flash": flash,
        "interpretation": normalized,
        "usage": result.get("usage") or {},
    }
    payload["cache_key"] = cache_key
    c.set(cache_key, payload)
    c.set("ai:jin10_interpret:latest", payload)
    write_audit_event(c, "jin10_ai_interpretation", payload, source="jin10_mcp", ref_id=str(req.get("id") or req.get("time") or "flash"))
    return ok({
        "provider": provider,
        "model": result.get("model") or model,
        "model_source": effective["source"],
        "cache_key": cache_key,
        "flash": flash,
        "interpretation": normalized,
        "usage": result.get("usage") or {},
    })


def handle(req: dict[str, Any]) -> dict[str, Any]:
    action = str(req.get("action") or "status")
    if action not in ALLOWED_ACTIONS:
        return fail(f"unsupported action: {action}")

    try:
        if action == "interpret_flash":
            return _interpret_flash(req)
        if action == "flash_detail":
            return _cached_tool_data(
                action,
                req,
                lambda: _load_flash_detail(str(req.get("url") or "")),
            )

        client = _client()
        if action == "status":
            def load_status():
                try:
                    return ok({
                        "healthy": True,
                        "degraded": False,
                        "reason_code": "",
                        "server_url": client.server_url,
                        "protocol_version": client.protocol_version,
                        "initialized": True,
                        "initialize": client.initialize(),
                        "tools": [t.get("name") for t in client.list_tools().get("tools", [])],
                        "resources": [r.get("uri") for r in client.list_resources().get("resources", [])],
                    })
                except Exception as exc:
                    return ok({
                        "healthy": False,
                        "degraded": True,
                        "reason_code": "mcp_transport_unavailable",
                        "server_url": client.server_url,
                        "protocol_version": client.protocol_version,
                        "initialized": False,
                        "tools": [],
                        "resources": [],
                        "error": str(exc)[:500],
                    })

            return _cached_tool_data(action, req, load_status)

        if action == "tools":
            return _cached_tool_data(action, req, lambda: ok(client.list_tools()))
        if action == "resources":
            return _cached_tool_data(action, req, lambda: ok(client.list_resources()))
        if action == "codes":
            def load_codes():
                result = client.read_resource("quote://codes")
                if not req.get("include_raw"):
                    result.pop("raw", None)
                return result
            return _cached_tool_data(action, req, load_codes)

        if action == "quote":
            code = normalize_code(req.get("code") or "")
            if not code:
                return fail("code is required")
            return _cached_tool_data(action, {**req, "code": code}, lambda: _tool_data(
                client.call_tool("get_quote", {"code": code}),
                bool(req.get("include_content")),
            ), include_content=bool(req.get("include_content")))

        if action == "quotes":
            codes = req.get("codes") or []
            if not isinstance(codes, list):
                return fail("codes must be a list")
            norm_codes = [normalize_code(c) for c in codes if normalize_code(c)]
            norm_codes = list(dict.fromkeys(norm_codes))[:20]
            if not norm_codes:
                return fail("codes are required")

            def load_quotes():
                rows = []
                errors = []
                for code in norm_codes:
                    one = _tool_data(client.call_tool("get_quote", {"code": code}), bool(req.get("include_content")))
                    if one.get("success"):
                        rows.append((one.get("data") or {}).get("data") or one.get("data"))
                    else:
                        errors.append({"code": code, "error": one.get("error")})
                return ok({"items": rows, "errors": errors, "count": len(rows)})
            return _cached_tool_data(action, {**req, "codes": norm_codes}, load_quotes, include_content=bool(req.get("include_content")))

        if action == "kline":
            code = normalize_code(req.get("code") or "")
            if not code:
                return fail("code is required")
            args = {"code": code}
            if req.get("time"):
                args["time"] = str(req.get("time"))
            if req.get("count") is not None:
                args["count"] = int(req.get("count"))
            return _cached_tool_data(action, {**req, "code": code}, lambda: _tool_data(
                client.call_tool("get_kline", args),
                bool(req.get("include_content")),
            ), include_content=bool(req.get("include_content")))

        if action == "flash":
            keyword = str(req.get("keyword") or "").strip()
            pages = _page_limit(req)

            def load_flash():
                if keyword:
                    return _tool_data(client.call_tool("search_flash", {"keyword": keyword}), bool(req.get("include_content")))
                if pages > 1:
                    args = {"cursor": req.get("cursor")} if req.get("cursor") else {}
                    data = client.fetch_all_pages("list_flash", args, limit_pages=pages)
                else:
                    data = client.call_tool("list_flash", {"cursor": req.get("cursor")})
                if data.get("success"):
                    data["page"] = page_info(data.get("data") or {})
                return _tool_data(data, bool(req.get("include_content")))
            return _cached_tool_data(action, req, load_flash, include_content=bool(req.get("include_content")))

        if action == "news":
            keyword = str(req.get("keyword") or "").strip()
            pages = _page_limit(req)

            def load_news():
                args = {"cursor": req.get("cursor")} if req.get("cursor") else {}
                if keyword:
                    args["keyword"] = keyword
                    if pages > 1:
                        data = client.fetch_all_pages("search_news", args, limit_pages=pages)
                    else:
                        data = client.call_tool("search_news", args)
                elif pages > 1:
                    data = client.fetch_all_pages("list_news", args, limit_pages=pages)
                else:
                    data = client.call_tool("list_news", args)
                if data.get("success"):
                    data["page"] = page_info(data.get("data") or {})
                return _tool_data(data, bool(req.get("include_content")))
            return _cached_tool_data(action, req, load_news, include_content=bool(req.get("include_content")))

        if action == "news_detail":
            news_id = str(req.get("id") or "").strip()
            if not re.fullmatch(r"\d{1,20}", news_id):
                return fail("id is required")
            return _cached_tool_data(
                action,
                {**req, "id": news_id},
                lambda: _load_news_detail(client, news_id),
            )

        if action == "calendar":
            return _cached_tool_data(action, req, lambda: _tool_data(
                client.call_tool("list_calendar", {}),
                bool(req.get("include_content")),
            ), include_content=bool(req.get("include_content")))

        return fail(f"unsupported action: {action}")
    except MCPProtocolError as exc:
        return fail(str(exc), protocol="mcp")
    except Exception as exc:
        return fail(str(exc), protocol="runtime")


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
            req_id = req.pop("__id", None)
            resp = handle(req)
        except Exception as exc:
            req_id = None
            resp = fail(str(exc))
        if req_id is not None:
            resp["__id"] = req_id
        print(json.dumps(resp, ensure_ascii=False, default=str), flush=True)


if __name__ == "__main__":
    main()
