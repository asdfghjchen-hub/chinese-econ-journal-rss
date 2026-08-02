from pathlib import Path

from src.parser import discover_candidate_pages, parse_html_articles
from src.utils import parse_date


def test_invalid_month_never_raises():
    assert parse_date("2026-15") is None
    assert parse_date("2026年15期") is None
    assert parse_date("2026年13月") is None


def test_valid_dates():
    assert parse_date("2026-08-02").isoformat() == "2026-08-02T00:00:00"
    assert parse_date("2026年8月").isoformat() == "2026-08-01T00:00:00"


def test_discover_current_issue_page():
    html = """
    <html><body>
      <a href="/Magazine/Show?id=12">2026年第7期</a>
      <a href="/Article/Show?id=99">一篇文章</a>
    </body></html>
    """
    journal = {
        "follow_url_patterns": ["/Magazine/Show"],
        "follow_text_patterns": ["最新一期"],
    }
    urls = discover_candidate_pages(
        html,
        "https://example.com/",
        journal,
        4,
    )
    assert urls == ["https://example.com/Magazine/Show?id=12"]


def test_article_date_does_not_come_from_article_id():
    html = """
    <div>
      <a href="/jmsc/Article/abstract/20230503">
        大数据驱动的决策范式转变
      </a>
    </div>
    """
    journal = {
        "id": "sample",
        "name": "示例",
        "tier": "A1",
        "article_url_patterns": ["/Article/abstract/"],
        "exclude_text_patterns": [],
        "exclude_url_patterns": [],
    }
    settings = {
        "min_title_length": 6,
        "max_title_length": 140,
        "max_items_per_source": 50,
    }
    items = parse_html_articles(
        html,
        "https://example.com/current",
        journal,
        settings,
    )
    assert len(items) == 1
    assert items[0].published is None
