from __future__ import annotations

from scripts import jin10_runner


FLASH_HTML = """
<html>
  <body>
    <div class="content-title"><div>金十图示：投机情绪指数</div></div>
    <button class="mini-program-card">
      <div class="mini-program-card__cover">
        <img
          src="https://img.jin10.com/mp/26/07/speculative.jpg/lite"
          class="mini-program-card__cover-image"
        >
      </div>
    </button>
  </body>
</html>
"""


NEWS_HTML = """
<html>
  <body>
    <div class="jin10-news-cdetails-content">
      <div>
        <p><strong>1. 证监会召开座谈会</strong></p>
        <p>会议将听取促进市场稳定健康发展的意见建议。</p>
        <p><strong>2. 长期资金增持中国股票资产</strong></p>
        <p>相关机构表示将继续维护资本市场平稳运行。</p>
      </div>
    </div>
  </body>
</html>
"""


def setup_function():
    jin10_runner._READ_CACHE.clear()


def test_flash_detail_parser_extracts_chart_image():
    parser = getattr(jin10_runner, "_extract_flash_detail_html", None)
    assert callable(parser), "flash detail HTML parser is missing"

    detail = parser(FLASH_HTML, "https://flash.jin10.com/detail/20260720084021571800")

    assert detail["title"] == "金十图示：投机情绪指数"
    assert detail["image_url"] == "https://img.jin10.com/mp/26/07/speculative.jpg/lite"
    assert detail["images"] == ["https://img.jin10.com/mp/26/07/speculative.jpg/lite"]


def test_news_detail_parser_extracts_article_text():
    parser = getattr(jin10_runner, "_extract_news_detail_html", None)
    assert callable(parser), "news detail HTML parser is missing"

    detail = parser(NEWS_HTML, "https://xnews.jin10.com/details/224989")

    assert "证监会召开座谈会" in detail["content"]
    assert "维护资本市场平稳运行" in detail["content"]
    assert detail["url"] == "https://xnews.jin10.com/details/224989"


def test_news_detail_falls_back_to_official_page_when_mcp_body_is_empty(monkeypatch):
    class FakeClient:
        def call_tool(self, name, arguments):
            assert name == "get_news"
            assert arguments == {"id": "224989"}
            return {
                "success": True,
                "data": {
                    "data": {
                        "id": "224989",
                        "title": "A股盘前市场要闻速递（2026-07-20）",
                        "content": "“‘’”“”————–———“·”“”",
                        "url": "https://xnews.jin10.com/details/224989",
                    }
                },
            }

    fetch_html = getattr(jin10_runner, "_fetch_jin10_html", None)
    assert callable(fetch_html), "official Jin10 HTML fallback is missing"
    monkeypatch.setattr(jin10_runner, "_client", lambda: FakeClient())
    monkeypatch.setattr(jin10_runner, "_fetch_jin10_html", lambda url: NEWS_HTML)

    result = jin10_runner.handle({
        "action": "news_detail",
        "id": "224989",
        "force_refresh": True,
    })

    assert result["success"] is True
    assert result["data"]["source"] == "official_page_fallback"
    assert "证监会召开座谈会" in result["data"]["item"]["content"]


def test_flash_detail_reads_only_validated_official_detail_url(monkeypatch):
    fetch_html = getattr(jin10_runner, "_fetch_jin10_html", None)
    assert callable(fetch_html), "official Jin10 HTML fallback is missing"
    monkeypatch.setattr(jin10_runner, "_fetch_jin10_html", lambda url: FLASH_HTML)

    result = jin10_runner.handle({
        "action": "flash_detail",
        "url": "https://flash.jin10.com/detail/20260720084021571800",
        "force_refresh": True,
    })

    assert result["success"] is True
    assert result["data"]["item"]["image_url"].endswith("speculative.jpg/lite")

    blocked = jin10_runner.handle({
        "action": "flash_detail",
        "url": "https://example.com/detail/20260720084021571800",
        "force_refresh": True,
    })
    assert blocked["success"] is False
    assert "invalid Jin10 flash detail URL" in blocked["error"]


def test_flash_detail_cache_is_scoped_by_url(monkeypatch):
    first_url = "https://flash.jin10.com/detail/20260720084021571800"
    second_url = "https://flash.jin10.com/detail/20260720092101447800"

    def fake_fetch(url):
        image_name = "first.jpg" if url == first_url else "second.jpg"
        return f"""
        <html>
          <body>
            <div class="content-title"><div>{url}</div></div>
            <img
              src="https://img.jin10.com/{image_name}"
              class="mini-program-card__cover-image"
            >
          </body>
        </html>
        """

    monkeypatch.setattr(jin10_runner, "_fetch_jin10_html", fake_fetch)

    first = jin10_runner.handle({"action": "flash_detail", "url": first_url})
    second = jin10_runner.handle({"action": "flash_detail", "url": second_url})

    assert first["data"]["item"]["image_url"].endswith("first.jpg")
    assert second["data"]["item"]["image_url"].endswith("second.jpg")
