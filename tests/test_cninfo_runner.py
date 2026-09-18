from __future__ import annotations

from datetime import date

import pytest

from scripts.cninfo_runner import CninfoClient, normalize_announcement, normalize_request


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakePdfResponse(FakeResponse):
    def __init__(self, content: bytes):
        super().__init__({})
        self.content = content


def test_normalize_request_applies_bounded_defaults():
    result = normalize_request(
        {"action": "query", "preset": "performance_express"},
        today=date(2026, 7, 24),
    )

    assert result["start_date"] == "2026-06-24"
    assert result["end_date"] == "2026-07-24"
    assert result["keyword"] == "业绩快报"
    assert result["page"] == 1
    assert result["page_size"] == 30


def test_normalize_request_maps_periodic_reports_to_official_categories():
    result = normalize_request(
        {"action": "query", "preset": "periodic_report"},
        today=date(2026, 7, 24),
    )

    assert result["keyword"] == ""
    assert result["category"] == (
        "category_ndbg_szsh;category_bndbg_szsh;"
        "category_yjdbg_szsh;category_sjdbg_szsh"
    )


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"action": "delete"}, "unsupported action"),
        ({"action": "query", "code": "600519;drop"}, "invalid stock code"),
        (
            {"action": "query", "start_date": "2024-01-01", "end_date": "2026-07-24"},
            "date range exceeds 366 days",
        ),
        ({"action": "query", "page_size": 500}, "page_size must be between 1 and 50"),
    ],
)
def test_normalize_request_rejects_unsafe_or_unbounded_input(payload, message):
    with pytest.raises(ValueError, match=message):
        normalize_request(payload, today=date(2026, 7, 24))


def test_normalize_announcement_strips_markup_and_builds_official_links():
    item = normalize_announcement(
        {
            "secCode": "300450",
            "secName": "先导智能",
            "announcementTitle": "2025年度<em>业绩快报</em>更正公告",
            "announcementTime": 1784822400000,
            "announcementId": "1234567890",
            "adjunctUrl": "finalpage/2026-07-24/1234567890.PDF",
            "announcementType": "01010503||010113",
        }
    )

    assert item["title"] == "2025年度业绩快报更正公告"
    assert item["announcement_date"] == "2026-07-24"
    assert item["pdf_url"] == "https://static.cninfo.com.cn/finalpage/2026-07-24/1234567890.PDF"
    assert item["detail_url"].startswith("https://www.cninfo.com.cn/new/disclosure/detail?")
    assert item["tags"] == ["业绩快报", "更正公告"]


@pytest.mark.parametrize(
    "title, expected_tag",
    [
        ("2026年半年度报告摘要", "半年度报告"),
        ("2026年第一季度报告", "一季度报告"),
        ("2025年年度报告", "年度报告"),
    ],
)
def test_normalize_announcement_uses_one_periodic_report_tag(title, expected_tag):
    item = normalize_announcement({"announcementTitle": title})

    assert item["tags"] == [expected_tag]


def test_client_caches_identical_queries_and_deduplicates_rows():
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        row = {
            "secCode": "300450",
            "secName": "先导智能",
            "announcementTitle": "2025年度业绩快报",
            "announcementTime": 1784822400000,
            "announcementId": "1234567890",
            "adjunctUrl": "finalpage/2026-07-24/1234567890.PDF",
        }
        return FakeResponse({"totalAnnouncement": 2, "announcements": [row, row]})

    client = CninfoClient(post=fake_post, clock=lambda: 1000.0, min_interval=0)
    request = normalize_request(
        {
            "action": "query",
            "preset": "performance_express",
            "start_date": "2026-06-24",
            "end_date": "2026-07-24",
        }
    )

    first = client.query(request)
    second = client.query(request)

    assert first["items"] == second["items"]
    assert len(first["items"]) == 1
    assert first["cached"] is False
    assert second["cached"] is True
    assert len(calls) == 1


def test_client_sends_official_periodic_report_categories():
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return FakeResponse({"totalAnnouncement": 0, "announcements": []})

    client = CninfoClient(post=fake_post, clock=lambda: 1000.0, min_interval=0)
    request = normalize_request(
        {
            "action": "query",
            "preset": "periodic_report",
            "start_date": "2026-07-01",
            "end_date": "2026-07-24",
        }
    )

    client.query(request)

    assert calls[0][1]["data"]["category"] == request["category"]


def test_normalize_request_accepts_only_official_cninfo_pdf_details():
    result = normalize_request(
        {
            "action": "detail",
            "pdf_url": "https://static.cninfo.com.cn/finalpage/2026-07-24/1234567890.PDF",
            "title": "年度报告",
        }
    )

    assert result["action"] == "detail"
    assert result["pdf_url"].endswith("1234567890.PDF")

    with pytest.raises(ValueError, match="official CNINFO PDF"):
        normalize_request({"action": "detail", "pdf_url": "https://example.com/report.pdf"})


def test_client_extracts_and_caches_pdf_detail():
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return FakePdfResponse(b"%PDF fake")

    client = CninfoClient(
        get=fake_get,
        clock=lambda: 1000.0,
        min_interval=0,
        pdf_extractor=lambda content: ("第一章 公司经营情况", 8, False),
    )
    request = normalize_request(
        {
            "action": "detail",
            "pdf_url": "https://static.cninfo.com.cn/finalpage/2026-07-24/1234567890.PDF",
            "title": "年度报告",
        }
    )

    first = client.detail(request)
    second = client.detail(request)

    assert first["content"] == "第一章 公司经营情况"
    assert first["page_count"] == 8
    assert first["cached"] is False
    assert second["cached"] is True
    assert len(calls) == 1
