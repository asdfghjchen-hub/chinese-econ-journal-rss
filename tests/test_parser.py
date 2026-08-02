from pathlib import Path

from src.parser import discover_feed_urls, parse_html_articles


def test_discover_feed_url():
    html = Path("tests/fixtures/sample.html").read_text(encoding="utf-8")
    urls = discover_feed_urls(html, "https://example.com/current")
    assert urls == ["https://example.com/feed.xml"]


def test_generic_article_parser():
    html = Path("tests/fixtures/sample.html").read_text(encoding="utf-8")
    journal = {
        "id": "sample",
        "name": "示例期刊",
        "tier": "A1",
        "include_url_patterns": ["/CN/abstract/"],
        "exclude_text_patterns": ["投稿"],
    }
    settings = {
        "min_title_length": 6,
        "max_title_length": 120,
        "max_items_per_source": 40,
    }
    items = parse_html_articles(html, "https://example.com/current", journal, settings)
    assert len(items) == 1
    assert items[0].title == "数字基础设施与企业创新：机制与证据"
    assert items[0].published.year == 2026
