from src.parser import (
    _extract_candidate_period,
    discover_candidate_pages,
    parse_html_articles,
)


def test_ajcass_issue_pages_rank_newest_first():
    html = """
    <a href="/Magazine/GetIssueContentList?Year=2026&Issue=7">第7期</a>
    <a href="/Magazine/GetIssueContentList?Year=2026&Issue=9">第9期</a>
    <a href="/Magazine/Show?id=123">一篇文章</a>
    """
    journal = {
        "follow_url_patterns": ["/Magazine/GetIssueContentList"],
        "candidate_url_require_patterns": ["/Magazine/GetIssueContentList"],
        "candidate_url_exclude_patterns": ["/Magazine/Show"],
    }
    urls = discover_candidate_pages(
        html,
        "https://example.com/",
        journal,
        10,
    )
    assert urls[0].endswith("Year=2026&Issue=9")
    assert urls[1].endswith("Year=2026&Issue=7")
    assert all("/Magazine/Show" not in url for url in urls)


def test_candidate_period_from_query_and_qiushi_path():
    assert _extract_candidate_period(
        "https://x/Magazine/GetIssueContentList?Year=2026&Issue=8",
        "",
    ) == (2026, 8, 0)
    assert _extract_candidate_period(
        "https://www.qstheory.cn/dukan/qs/2026-15/01/x.htm",
        "",
    ) == (2026, 15, 1)


def test_issue_links_are_not_articles():
    html = """
    <a href="/Magazine/GetIssueContentList?Year=2026&Issue=8">第8期</a>
    <a href="/Magazine/Show?id=100">企业创新与生产率</a>
    """
    journal = {
        "id": "sample",
        "name": "示例",
        "tier": "A1",
        "article_url_patterns": ["/Magazine/Show?id="],
        "exclude_url_patterns": ["/Magazine/GetIssueContentList"],
    }
    settings = {
        "min_title_length": 4,
        "max_title_length": 140,
        "max_items_per_source": 40,
    }
    items = parse_html_articles(
        html,
        "https://example.com/",
        journal,
        settings,
    )
    assert [item.title for item in items] == ["企业创新与生产率"]


def test_latest_url_period_filter():
    html = """
    <a href="/jmsc/article/abstract/20260601">文章甲：企业创新研究</a>
    <a href="/jmsc/article/abstract/20260602">文章乙：金融市场研究</a>
    <a href="/jmsc/article/abstract/20260603">文章丙：数字经济研究</a>
    <a href="/jmsc/article/abstract/20240501">旧文章一：管理机制研究</a>
    """
    journal = {
        "id": "jmsc",
        "name": "管理科学学报",
        "tier": "A2",
        "article_url_patterns": ["/jmsc/article/abstract/"],
        "exclude_url_patterns": [],
        "latest_url_period_regex": r"/abstract/(20\d{2})(\d{2})",
        "latest_url_period_min_items": 3,
    }
    settings = {
        "min_title_length": 6,
        "max_title_length": 140,
        "max_items_per_source": 40,
    }
    items = parse_html_articles(
        html,
        "https://example.com/jmsc/home",
        journal,
        settings,
    )
    assert len(items) == 3
    assert all("202606" in item.url for item in items)
