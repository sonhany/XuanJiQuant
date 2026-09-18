"""Read-only CNINFO disclosure query runner.

The runner keeps upstream access outside the Node event loop and applies a
small cache plus request pacing because CNINFO's website query API has no SLA.
"""

from __future__ import annotations

import html
import io
import json
import re
import sys
import time
from datetime import date, datetime, timedelta
from threading import Lock
from typing import Any, Callable
from urllib.parse import urlencode, urlparse
from zoneinfo import ZoneInfo

import requests
from pypdf import PdfReader


CNINFO_QUERY_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_STOCKS_URL = "https://www.cninfo.com.cn/new/data/szse_stock.json"
CNINFO_STATIC_ROOT = "https://static.cninfo.com.cn/"
CNINFO_DETAIL_ROOT = "https://www.cninfo.com.cn/new/disclosure/detail"
CACHE_TTL_SECONDS = 5 * 60
STOCK_CACHE_TTL_SECONDS = 4 * 60 * 60
MAX_DATE_RANGE_DAYS = 366
MAX_PAGE_SIZE = 50
MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PDF_TEXT_CHARS = 120_000

PRESET_KEYWORDS = {
    "latest": "",
    "performance_express": "业绩快报",
    "performance_forecast": "业绩预告",
    "periodic_report": "",
}

PRESET_CATEGORIES = {
    "latest": "",
    "performance_express": "",
    "performance_forecast": "",
    "periodic_report": (
        "category_ndbg_szsh;category_bndbg_szsh;"
        "category_yjdbg_szsh;category_sjdbg_szsh"
    ),
}

_TAG_PATTERN = re.compile(r"<[^>]+>")
_CODE_PATTERN = re.compile(r"^\d{6}$")
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CONTROL_PATTERN = re.compile(r"[\x00-\x1f\x7f]")


def _iso_date(value: Any, field: str) -> date:
    text = str(value or "").strip()
    if not _DATE_PATTERN.fullmatch(text):
        raise ValueError(f"invalid {field}")
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"invalid {field}") from exc


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int, field: str) -> int:
    try:
        number = int(value if value not in (None, "") else default)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field}") from exc
    if not minimum <= number <= maximum:
        if field == "page_size":
            raise ValueError(f"page_size must be between {minimum} and {maximum}")
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return number


def normalize_request(req: dict[str, Any] | None, *, today: date | None = None) -> dict[str, Any]:
    payload = req if isinstance(req, dict) else {}
    action = str(payload.get("action") or "query").strip()
    if action not in {"query", "detail", "status"}:
        raise ValueError(f"unsupported action: {action}")
    if action == "status":
        return {"action": "status"}
    if action == "detail":
        pdf_url = str(payload.get("pdf_url") or "").strip()
        parsed = urlparse(pdf_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "static.cninfo.com.cn"
            or not parsed.path.startswith("/finalpage/")
            or not parsed.path.lower().endswith(".pdf")
        ):
            raise ValueError("detail requires an official CNINFO PDF URL")
        return {
            "action": "detail",
            "pdf_url": pdf_url,
            "title": sanitize_title(payload.get("title"))[:200],
            "code": str(payload.get("code") or "").strip()[:12],
            "name": sanitize_title(payload.get("name"))[:60],
        }

    current = today or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    end = _iso_date(payload.get("end_date"), "end_date") if payload.get("end_date") else current
    start = _iso_date(payload.get("start_date"), "start_date") if payload.get("start_date") else end - timedelta(days=30)
    if start > end:
        raise ValueError("start_date must not be after end_date")
    if (end - start).days > MAX_DATE_RANGE_DAYS:
        raise ValueError(f"date range exceeds {MAX_DATE_RANGE_DAYS} days")

    code = str(payload.get("code") or "").strip().upper()
    code = code.removeprefix("SH").removeprefix("SZ").removeprefix("BJ")
    code = re.sub(r"\.(SH|SZ|BJ)$", "", code)
    if code and not _CODE_PATTERN.fullmatch(code):
        raise ValueError("invalid stock code")

    preset = str(payload.get("preset") or "latest").strip()
    if preset not in PRESET_KEYWORDS:
        raise ValueError("invalid preset")
    custom_keyword = _CONTROL_PATTERN.sub("", str(payload.get("keyword") or "")).strip()
    if len(custom_keyword) > 60:
        raise ValueError("keyword exceeds 60 characters")
    keyword = custom_keyword or PRESET_KEYWORDS[preset]

    return {
        "action": "query",
        "preset": preset,
        "code": code,
        "keyword": keyword,
        "category": PRESET_CATEGORIES[preset],
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "page": _bounded_int(payload.get("page"), default=1, minimum=1, maximum=100, field="page"),
        "page_size": _bounded_int(
            payload.get("page_size"), default=30, minimum=1, maximum=MAX_PAGE_SIZE, field="page_size"
        ),
        "force_refresh": payload.get("force_refresh") is True,
    }


def sanitize_title(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = _TAG_PATTERN.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _announcement_date(value: Any) -> str:
    try:
        stamp = float(value) / 1000
        return datetime.fromtimestamp(stamp, ZoneInfo("Asia/Shanghai")).date().isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def _tags_for_title(title: str) -> list[str]:
    tags = []
    for needles, label in (
        (("半年度报告",), "半年度报告"),
        (("第一季度报告", "一季度报告"), "一季度报告"),
        (("第三季度报告", "三季度报告"), "三季度报告"),
        (("年度报告",), "年度报告"),
    ):
        if any(needle in title for needle in needles):
            tags.append(label)
            break
    for needle, label in (
        ("业绩快报", "业绩快报"),
        ("业绩预告", "业绩预告"),
        ("更正", "更正公告"),
        ("风险提示", "风险提示"),
    ):
        if needle in title and label not in tags:
            tags.append(label)
    return tags or ["公司公告"]


def normalize_announcement(row: dict[str, Any]) -> dict[str, Any]:
    code = str(row.get("secCode") or "").strip()
    name = sanitize_title(row.get("secName"))
    title = sanitize_title(row.get("announcementTitle"))
    announcement_id = str(row.get("announcementId") or "").strip()
    org_id = str(row.get("orgId") or "").strip()
    announcement_date = _announcement_date(row.get("announcementTime"))
    adjunct = str(row.get("adjunctUrl") or "").strip().lstrip("/")
    pdf_url = CNINFO_STATIC_ROOT + adjunct if adjunct.startswith("finalpage/") else ""
    detail_url = ""
    if code and announcement_id:
        detail_url = CNINFO_DETAIL_ROOT + "?" + urlencode(
            {
                "stockCode": code,
                "announcementId": announcement_id,
                "orgId": org_id,
                "announcementTime": announcement_date,
            }
        )
    return {
        "id": announcement_id,
        "code": code,
        "name": name,
        "title": title,
        "announcement_time": row.get("announcementTime"),
        "announcement_date": announcement_date,
        "announcement_type": str(row.get("announcementType") or ""),
        "tags": _tags_for_title(title),
        "pdf_url": pdf_url,
        "detail_url": detail_url,
        "source": "cninfo",
    }


def extract_pdf_text(content: bytes) -> tuple[str, int, bool]:
    reader = PdfReader(io.BytesIO(content))
    parts: list[str] = []
    total_chars = 0
    truncated = False
    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        if not text:
            continue
        remaining = MAX_PDF_TEXT_CHARS - total_chars
        if remaining <= 0:
            truncated = True
            break
        if len(text) > remaining:
            text = text[:remaining]
            truncated = True
        parts.append(text)
        total_chars += len(text)
    return "\n\n".join(parts), len(reader.pages), truncated


class CninfoClient:
    def __init__(
        self,
        *,
        post: Callable[..., Any] = requests.post,
        get: Callable[..., Any] = requests.get,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        cache_ttl: int = CACHE_TTL_SECONDS,
        min_interval: float = 1.0,
        pdf_extractor: Callable[[bytes], tuple[str, int, bool]] = extract_pdf_text,
    ) -> None:
        self.post = post
        self.get = get
        self.clock = clock
        self.sleep = sleep
        self.cache_ttl = cache_ttl
        self.min_interval = max(0.0, float(min_interval))
        self.pdf_extractor = pdf_extractor
        self.cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self.stock_map: dict[str, str] = {}
        self.stock_map_at = 0.0
        self.last_request_at = 0.0
        self.lock = Lock()

    def detail(self, request: dict[str, Any]) -> dict[str, Any]:
        key = f'detail:{request["pdf_url"]}'
        now = self.clock()
        cached = self.cache.get(key)
        if cached and now - cached[0] < self.cache_ttl:
            return {**cached[1], "cached": True}

        self._pace()
        response = self.get(request["pdf_url"], headers=self._headers(), timeout=20)
        response.raise_for_status()
        content = bytes(response.content or b"")
        if not content.startswith(b"%PDF"):
            raise RuntimeError("CNINFO returned an invalid PDF")
        if len(content) > MAX_PDF_BYTES:
            raise RuntimeError("CNINFO PDF exceeds 20 MiB")
        text, page_count, truncated = self.pdf_extractor(content)
        result = {
            "content": text,
            "page_count": page_count,
            "truncated": truncated,
            "cached": False,
            "pdf_url": request["pdf_url"],
            "title": request.get("title", ""),
            "code": request.get("code", ""),
            "name": request.get("name", ""),
            "fetched_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
            "source": "CNINFO official PDF",
        }
        self.cache[key] = (now, result)
        return result

    @staticmethod
    def _headers() -> dict[str, str]:
        return {
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://www.cninfo.com.cn",
            "Referer": "https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search",
            "User-Agent": "XuanJiQuant-Cninfo/1.0 Mozilla/5.0",
            "X-Requested-With": "XMLHttpRequest",
        }

    def _pace(self) -> None:
        now = self.clock()
        wait = self.min_interval - (now - self.last_request_at) if self.last_request_at else 0
        if wait > 0:
            self.sleep(wait)
        self.last_request_at = self.clock()

    def _load_stock_map(self) -> dict[str, str]:
        now = self.clock()
        if self.stock_map and now - self.stock_map_at < STOCK_CACHE_TTL_SECONDS:
            return self.stock_map
        self._pace()
        response = self.get(CNINFO_STOCKS_URL, headers=self._headers(), timeout=15)
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("stockList") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise RuntimeError("CNINFO stock directory returned invalid data")
        self.stock_map = {
            str(row.get("code") or ""): str(row.get("orgId") or "")
            for row in rows
            if isinstance(row, dict) and row.get("code") and row.get("orgId")
        }
        self.stock_map_at = now
        return self.stock_map

    def _cache_key(self, request: dict[str, Any]) -> str:
        stable = {key: value for key, value in request.items() if key != "force_refresh"}
        return json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def query(self, request: dict[str, Any]) -> dict[str, Any]:
        key = self._cache_key(request)
        now = self.clock()
        cached = self.cache.get(key)
        if cached and not request.get("force_refresh") and now - cached[0] < self.cache_ttl:
            return {**cached[1], "cached": True}

        with self.lock:
            now = self.clock()
            cached = self.cache.get(key)
            if cached and not request.get("force_refresh") and now - cached[0] < self.cache_ttl:
                return {**cached[1], "cached": True}

            stock = ""
            if request.get("code"):
                code = str(request["code"])
                org_id = self._load_stock_map().get(code)
                if not org_id:
                    raise ValueError(f"CNINFO does not recognize stock code {code}")
                stock = f"{code},{org_id}"

            form = {
                "pageNum": str(request["page"]),
                "pageSize": str(request["page_size"]),
                "column": "szse",
                "tabName": "fulltext",
                "plate": "",
                "stock": stock,
                "searchkey": request["keyword"],
                "secid": "",
                "category": request["category"],
                "trade": "",
                "seDate": f'{request["start_date"]}~{request["end_date"]}',
                "sortName": "",
                "sortType": "",
                "isHLtitle": "true",
            }
            self._pace()
            response = self.post(
                CNINFO_QUERY_URL,
                data=form,
                headers=self._headers(),
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("announcements"), list):
                raise RuntimeError("CNINFO returned invalid announcement data")

            items = []
            seen = set()
            for row in payload["announcements"]:
                if not isinstance(row, dict):
                    continue
                item = normalize_announcement(row)
                identity = item["id"] or f'{item["code"]}|{item["announcement_time"]}|{item["title"]}'
                if not identity or identity in seen:
                    continue
                seen.add(identity)
                items.append(item)

            total = int(payload.get("totalAnnouncement") or len(items))
            result = {
                "items": items,
                "count": len(items),
                "total": total,
                "page": request["page"],
                "page_size": request["page_size"],
                "has_more": request["page"] * request["page_size"] < total,
                "cached": False,
                "query": {key: value for key, value in request.items() if key != "force_refresh"},
                "fetched_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
                "source": "CNINFO website disclosure query",
            }
            self.cache[key] = (self.clock(), result)
            return result


CLIENT = CninfoClient()


def handle(req: dict[str, Any]) -> dict[str, Any]:
    request = normalize_request(req)
    if request["action"] == "status":
        return {
            "success": True,
            "data": {
                "source": "cninfo",
                "mode": "read_only",
                "cache_ttl_seconds": CACHE_TTL_SECONDS,
                "min_interval_seconds": CLIENT.min_interval,
            },
        }
    try:
        if request["action"] == "detail":
            return {"success": True, "data": CLIENT.detail(request)}
        return {"success": True, "data": CLIENT.query(request)}
    except requests.Timeout as exc:
        return {"success": False, "error": f"CNINFO request timed out: {exc}"}
    except requests.RequestException as exc:
        return {"success": False, "error": f"CNINFO request failed: {exc}"}
    except (ValueError, RuntimeError) as exc:
        return {"success": False, "error": str(exc)}


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        req_id = None
        try:
            req = json.loads(line)
            req_id = req.pop("__id", None)
            response = handle(req)
        except Exception as exc:
            response = {"success": False, "error": str(exc)[:500]}
        if req_id is not None:
            response["__id"] = req_id
        print(json.dumps(response, ensure_ascii=False, default=str), flush=True)


if __name__ == "__main__":
    main()
