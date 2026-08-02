from src.two_journal_watch import (
    dedupe_articles,
    issue_page_matches,
    looks_like_article_title,
    parse_issue_page,
    snapshot_hash,
)


def test_title_filter():
    assert looks_like_article_title(
        "数字化转型如何影响企业创新——基于组织学习视角"
    )
    assert not looks_like_article_title("投稿须知")
    assert not looks_like_article_title("期刊编辑规程")
    assert not looks_like_article_title("订户订购进口出版物管理办法")


def test_issue_match():
    assert issue_page_matches(
        "《经济研究》2026年第6期目录",
        "经济研究",
        2026,
        6,
    )
    assert not issue_page_matches(
        "《管理世界》2025年第3期目录",
        "经济研究",
        2026,
        6,
    )


def test_ncpssd_like_page_parser():
    html = """
    <html>
      <body>
        <h1>经济研究 2026年第6期</h1>
        <ul>
          <li>
            <a href="/literature/article/1">
              数字化转型如何影响企业创新——基于组织学习视角
            </a>
            作者：张三、李四 页码：1-20
          </li>
          <li>
            <a href="/literature/article/2">
              金融发展与企业生产率：来自中国上市公司的证据
            </a>
            作者：王五 页码：21-39
          </li>
          <li>
            <a href="/literature/article/3">
              环境规制、技术进步与绿色发展
            </a>
            作者：赵六 页码：40-58
          </li>
        </ul>
      </body>
    </html>
    """
    items = parse_issue_page(
        html,
        "https://www.ncpssd.org/journal/details?x=1",
        "economic-research",
        2026,
        6,
    )
    assert len(items) == 3
    assert any(item.author for item in items)


def test_snapshot_hash_ignores_clock_noise():
    a = snapshot_hash(
        "<html><body>更新时间 2026-08-02 12:30 正文</body></html>"
    )
    b = snapshot_hash(
        "<html><body>更新时间 2026-08-03 13:45 正文</body></html>"
    )
    assert a == b
