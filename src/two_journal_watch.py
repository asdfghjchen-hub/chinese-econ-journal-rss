from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .feed_builder import write_feed
from .models import Article


OUTPUT_DIR = Path("docs/feeds")
STATE_PATH = Path("data/two_journal_state.json")
REPORT_PATH = Path("docs/two-journal-report.md")
INDEX_PATH = Path("docs/two-journals.html")
DEBUG_DIR = Path("debug/two-journals")

NOW = datetime.now(timezone.utc)
CURRENT_YEAR = NOW.year
STATE_SCHEMA_VERSION = 4

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0.0.0 Safari/537.36"
)

JOURNALS = {
    "economic-research": {
        "name": "经济研究",
        "tier": "A1",
        "gch": "95645X",
        "homepage": "https://erj.ajcass.com/",
        "feed": "economic-research-only.xml",
        "primary_templates": [
            (
                "国家哲学社会科学文献中心",
                "https://www.ncpssd.org/journal/details"
                "?gch={gch}&langType=1&num={issue}&years={year}",
            ),
            (
                "国家哲学社会科学文献中心（无www）",
                "https://ncpssd.org/journal/details"
                "?gch={gch}&langType=1&num={issue}&years={year}",
            ),
            (
                "国家哲学社会科学文献中心移动端",
                "https://m.ncpssd.org/journal/details"
                "?gch={gch}&langType=1&num={issue}&years={year}",
            ),
        ],
        "backup_templates": [
            (
                "经济研究官网期次接口",
                "https://erj.ajcass.com/Magazine/GetIssueContentList"
                "?Year={year}&Issue={issue}",
            ),
            (
                "经济研究官网期次接口（小写参数）",
                "https://erj.ajcass.com/Magazine/GetIssueContentList"
                "?year={year}&issue={issue}",
            ),
        ],
    },
    "management-world": {
        "name": "管理世界",
        "tier": "A2",
        "gch": "95499X",
        "homepage": (
            "https://glsj.chinajournal.net.cn/"
            "WKB/WebPublication/index.aspx?mid=glsj"
        ),
        "feed": "management-world-only.xml",
        "primary_templates": [
            (
                "国家哲学社会科学文献中心",
                "https://www.ncpssd.org/journal/details"
                "?gch={gch}&langType=1&num={issue}&years={year}",
            ),
            (
                "国家哲学社会科学文献中心（无www）",
                "https://ncpssd.org/journal/details"
                "?gch={gch}&langType=1&num={issue}&years={year}",
            ),
            (
                "国家哲学社会科学文献中心移动端",
                "https://m.ncpssd.org/journal/details"
                "?gch={gch}&langType=1&num={issue}&years={year}",
            ),
        ],
        "backup_templates": [
            (
                "管理世界知网期次页",
                "https://glsj.chinajournal.net.cn/"
                "WKB2/WebPublication/wkTextContent.aspx"
                "?colType=4&yt={year}&st={issue2}",
            ),
            (
                "管理世界知网期次页（WKB）",
                "https://glsj.chinajournal.net.cn/"
                "WKB/WebPublication/wkTextContent.aspx"
                "?colType=4&yt={year}&st={issue2}",
            ),
        ],
    },
}

EXCLUDED_EXACT = {
    "首页",
    "当前期",
    "最新一期",
    "本期目录",
    "更多",
    "更多>>",
    "过刊",
    "过刊浏览",
    "登录",
    "注册",
    "投稿",
    "下载",
    "摘要",
    "全文",
}

EXCLUDED_PHRASES = (
    "投稿须知",
    "投稿指南",
    "订阅",
    "联系我们",
    "版权声明",
    "编委会",
    "期刊简介",
    "编辑规程",
    "编辑规范",
    "出版管理",
    "出版物市场",
    "数字印刷",
    "参考文献著录",
    "申请开通",
    "微信平台",
    "用户登录",
    "新闻出版总署",
    "学术年会",
    "发布会",
    "广告合作",
    "下载中心",
    "友情链接",
    "网站地图",
    "作者指南",
    "审稿系统",
    "期刊征订",
    "征稿启事",
    "管理办法",
    "进口出版物",
    "实施办法",
)

ACADEMIC_HINTS = (
    "研究",
    "影响",
    "机制",
    "效应",
    "创新",
    "企业",
    "经济",
    "市场",
    "管理",
    "治理",
    "政策",
    "发展",
    "金融",
    "产业",
    "改革",
    "技术",
    "数字",
    "资本",
    "生产率",
    "贸易",
    "投资",
    "就业",
    "增长",
    "理论",
    "实证",
    "中国",
    "财政",
    "货币",
    "环境",
    "平台",
    "供应链",
    "竞争",
    "组织",
    "知识",
    "劳动",
    "收入",
    "福利",
    "消费",
    "出口",
    "进口",
    "税",
)

ARTICLE_URL_HINTS = (
    "article",
    "literature",
    "details",
    "detail",
    "abstract",
    "magazine/show",
    "kcms",
    "doi",
    "contentid",
    "id=",
)

BLOCKED_HINTS = (
    "waf_slider_verify",
    "showvalidatecode",
    "人机验证",
    "安全验证",
    "访问验证",
    "请输入验证码",
    "captcha",
)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)

    for key in list(query):
        if key.lower().startswith("utm_"):
            query.pop(key, None)

    pairs = []
    for key in sorted(query):
        for value in query[key]:
            pairs.append((key, value))

    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(pairs),
            "",
        )
    )


def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=2,
        status=3,
        backoff_factor=0.8,
        status_forcelist=(408, 425, 429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "application/json;q=0.8,*/*;q=0.7"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
    )
    return session


def is_blocked(text: str, url: str) -> bool:
    combined = f"{url}\n{text}".lower()
    return any(hint.lower() in combined for hint in BLOCKED_HINTS)


def looks_like_article_title(title: str) -> bool:
    title = clean_text(title)

    if not 8 <= len(title) <= 180:
        return False
    if title in EXCLUDED_EXACT:
        return False
    if any(phrase in title for phrase in EXCLUDED_PHRASES):
        return False
    if len(re.findall(r"[\u4e00-\u9fff]", title)) < 5:
        return False

    punctuation_signal = any(mark in title for mark in ("——", "：", "?", "？"))
    academic_signal = any(hint in title for hint in ACADEMIC_HINTS)
    return punctuation_signal or academic_signal


def issue_page_matches(
    text: str,
    journal_name: str,
    year: int,
    issue: int,
) -> bool:
    normalized = clean_text(text)
    score = 0

    if journal_name in normalized:
        score += 2
    if str(year) in normalized:
        score += 1
    if re.search(rf"第\s*0?{issue}\s*期", normalized):
        score += 1
    if re.search(rf"{year}\s*年\s*第?\s*0?{issue}\s*期", normalized):
        score += 1

    # Some endpoints return only the issue fragment, without repeating journal name.
    return score >= 2


def context_text(node: Tag) -> str:
    current: Tag = node
    for _ in range(4):
        parent = current.parent
        if not isinstance(parent, Tag):
            break
        current = parent
        text = clean_text(current.get_text(" ", strip=True))
        if 10 <= len(text) <= 1200:
            return text
    return ""


def extract_author(context: str, title: str) -> str:
    remaining = clean_text(context.replace(title, " ", 1))
    if not remaining:
        return ""

    patterns = [
        r"(?:作者|文)\s*[:：]\s*([^|｜;；]{2,100})",
        r"^([一-龥A-Za-z·\s、，,]{2,80})(?:\s+\d{1,4}(?:-\d{1,4})?)?$",
    ]

    for pattern in patterns:
        match = re.search(pattern, remaining)
        if not match:
            continue
        value = clean_text(match.group(1))
        value = re.sub(r"\s+(摘要|关键词|下载|全文).*$", "", value)
        if 2 <= len(value) <= 100 and not any(
            phrase in value for phrase in EXCLUDED_PHRASES
        ):
            return value

    return ""


def extract_page_range(context: str) -> str:
    patterns = [
        r"(?:页码|页)\s*[:：]?\s*(\d{1,4}\s*[-–—]\s*\d{1,4})",
        r"\b(\d{1,4}\s*[-–—]\s*\d{1,4})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, context)
        if match:
            return clean_text(match.group(1))
    return ""


def article_from_candidate(
    journal_id: str,
    title: str,
    url: str,
    source_url: str,
    year: int,
    issue: int,
    context: str = "",
) -> Article:
    meta = JOURNALS[journal_id]
    author = extract_author(context, title)
    page_range = extract_page_range(context)

    summary_parts = [f"{year}年第{issue}期"]
    if page_range:
        summary_parts.append(f"页码：{page_range}")
    if context and context != title:
        compact_context = clean_text(context)
        if len(compact_context) <= 500:
            summary_parts.append(compact_context)

    return Article(
        journal_id=journal_id,
        journal_name=meta["name"],
        tier=meta["tier"],
        title=clean_text(title),
        url=normalize_url(url),
        author=author,
        published=None,
        summary="；".join(summary_parts)[:800],
        source_url=source_url,
    )


def extract_from_anchors(
    soup: BeautifulSoup,
    base_url: str,
    journal_id: str,
    year: int,
    issue: int,
) -> list[Article]:
    items: list[Article] = []

    for anchor in soup.find_all("a", href=True):
        title = clean_text(
            anchor.get("title") or anchor.get_text(" ", strip=True)
        )
        if not looks_like_article_title(title):
            continue

        url = normalize_url(urljoin(base_url, anchor["href"]))
        lowered_url = url.lower()

        # Allow all plausible detail links on NCPSD, but reject obvious navigation.
        if not any(hint in lowered_url for hint in ARTICLE_URL_HINTS):
            if "ncpssd.org" not in urlparse(url).netloc.lower():
                continue
            if url.rstrip("/") == base_url.rstrip("/"):
                continue

        context = context_text(anchor)
        items.append(
            article_from_candidate(
                journal_id,
                title,
                url,
                base_url,
                year,
                issue,
                context,
            )
        )

    return items


def extract_from_structured_nodes(
    soup: BeautifulSoup,
    base_url: str,
    journal_id: str,
    year: int,
    issue: int,
) -> list[Article]:
    items: list[Article] = []

    selectors = (
        "h1",
        "h2",
        "h3",
        "h4",
        ".title",
        ".article-title",
        ".articleTitle",
        ".paper-title",
        ".paperTitle",
        "[class*='article'] [class*='title']",
        "[class*='paper'] [class*='title']",
        "li",
        "tr",
    )

    for node in soup.select(",".join(selectors)):
        text = clean_text(node.get_text(" ", strip=True))
        if not text or len(text) > 1200:
            continue

        title = ""
        link = ""

        anchor = node.find("a", href=True)
        if anchor:
            candidate = clean_text(
                anchor.get("title") or anchor.get_text(" ", strip=True)
            )
            if looks_like_article_title(candidate):
                title = candidate
                link = normalize_url(urljoin(base_url, anchor["href"]))

        if not title:
            for separator in (" 作者：", " 作者 ", " 摘要", " 关键词", " 页码"):
                if separator in text:
                    candidate = clean_text(text.split(separator, 1)[0])
                    if looks_like_article_title(candidate):
                        title = candidate
                        break

        if not title:
            continue

        if not link:
            link = base_url

        items.append(
            article_from_candidate(
                journal_id,
                title,
                link,
                base_url,
                year,
                issue,
                text,
            )
        )

    return items


def extract_from_json_scripts(
    soup: BeautifulSoup,
    base_url: str,
    journal_id: str,
    year: int,
    issue: int,
) -> list[Article]:
    items: list[Article] = []

    title_keys = (
        "title",
        "articleTitle",
        "article_title",
        "paperTitle",
        "paper_title",
        "name",
    )
    url_keys = ("url", "link", "href", "detailUrl", "detail_url")
    author_keys = ("author", "authors", "authorName", "author_name")

    def walk(value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)

    for script in soup.find_all("script"):
        raw = script.string or script.get_text(" ", strip=True)
        raw = clean_text(raw)
        if not raw or len(raw) > 5_000_000:
            continue

        parsed_values = []
        if script.get("type") == "application/ld+json":
            try:
                parsed_values.append(json.loads(raw))
            except json.JSONDecodeError:
                pass

        # Extract embedded JSON objects that contain likely title keys.
        for match in re.finditer(
            r"\{[^{}]{0,4000}(?:articleTitle|paperTitle|title)[^{}]{0,4000}\}",
            raw,
            flags=re.I,
        ):
            try:
                parsed_values.append(json.loads(match.group(0)))
            except json.JSONDecodeError:
                continue

        for payload in parsed_values:
            for obj in walk(payload):
                title = ""
                for key in title_keys:
                    value = obj.get(key)
                    if isinstance(value, str) and looks_like_article_title(value):
                        title = clean_text(value)
                        break
                if not title:
                    continue

                url = base_url
                for key in url_keys:
                    value = obj.get(key)
                    if isinstance(value, str) and value:
                        url = normalize_url(urljoin(base_url, value))
                        break

                author = ""
                for key in author_keys:
                    value = obj.get(key)
                    if isinstance(value, str):
                        author = clean_text(value)
                        break
                    if isinstance(value, list):
                        author = "、".join(
                            clean_text(
                                item.get("name", "")
                                if isinstance(item, dict)
                                else str(item)
                            )
                            for item in value
                        )
                        break

                article = article_from_candidate(
                    journal_id,
                    title,
                    url,
                    base_url,
                    year,
                    issue,
                    "",
                )
                if author:
                    article = Article(
                        journal_id=article.journal_id,
                        journal_name=article.journal_name,
                        tier=article.tier,
                        title=article.title,
                        url=article.url,
                        author=author,
                        published=article.published,
                        summary=article.summary,
                        source_url=article.source_url,
                    )
                items.append(article)

    return items


def dedupe_articles(items: Iterable[Article]) -> list[Article]:
    result: dict[str, Article] = {}

    for item in items:
        key = re.sub(r"\s+", "", item.title.lower())
        existing = result.get(key)
        if existing is None:
            result[key] = item
            continue

        # Prefer the item with a real detail URL and author.
        existing_score = int(existing.url != existing.source_url) + int(bool(existing.author))
        item_score = int(item.url != item.source_url) + int(bool(item.author))
        if item_score > existing_score:
            result[key] = item

    values = list(result.values())
    values.sort(key=lambda item: item.title)
    return values


def parse_issue_page(
    raw_html: str,
    final_url: str,
    journal_id: str,
    year: int,
    issue: int,
) -> list[Article]:
    soup = BeautifulSoup(raw_html, "lxml")
    text = clean_text(soup.get_text(" ", strip=True))
    meta = JOURNALS[journal_id]

    if is_blocked(text, final_url):
        return []
    if not issue_page_matches(text, meta["name"], year, issue):
        return []

    items = []
    items.extend(
        extract_from_anchors(soup, final_url, journal_id, year, issue)
    )
    items.extend(
        extract_from_structured_nodes(soup, final_url, journal_id, year, issue)
    )
    items.extend(
        extract_from_json_scripts(soup, final_url, journal_id, year, issue)
    )

    return dedupe_articles(items)


def fetch_html(
    session: requests.Session,
    url: str,
    referer: Optional[str] = None,
) -> tuple[str, str]:
    headers = {"Referer": referer} if referer else None
    response = session.get(
        url,
        timeout=(15, 45),
        allow_redirects=True,
        headers=headers,
    )
    response.raise_for_status()

    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding or "utf-8"

    return response.url, response.text


def candidate_issues() -> list[tuple[int, int]]:
    result = []
    for year in (CURRENT_YEAR, CURRENT_YEAR - 1):
        for issue in range(12, 0, -1):
            result.append((year, issue))
    return result


def crawl_journal(
    session: requests.Session,
    journal_id: str,
) -> tuple[list[Article], list[str], str]:
    meta = JOURNALS[journal_id]
    notes: list[str] = []
    best_snapshot = ""

    source_groups = (
        ("主源", meta["primary_templates"]),
        ("备用源", meta["backup_templates"]),
    )

    for group_name, templates in source_groups:
        for source_name, template in templates:
            consecutive_network_errors = 0

            for year, issue in candidate_issues():
                url = template.format(
                    gch=meta["gch"],
                    year=year,
                    issue=issue,
                    issue2=f"{issue:02d}",
                )
                try:
                    final_url, raw_html = fetch_html(
                        session,
                        url,
                        referer=meta["homepage"],
                    )
                    consecutive_network_errors = 0

                    if not best_snapshot:
                        best_snapshot = raw_html

                    articles = parse_issue_page(
                        raw_html,
                        final_url,
                        journal_id,
                        year,
                        issue,
                    )
                    notes.append(
                        f"{group_name}/{source_name} "
                        f"{year}年第{issue}期识别{len(articles)}条"
                    )

                    if len(articles) >= 3:
                        notes.append(
                            f"采用{source_name}：{year}年第{issue}期"
                        )
                        return articles, notes, raw_html

                except (
                    requests.exceptions.ConnectionError,
                    requests.exceptions.SSLError,
                ) as exc:
                    consecutive_network_errors += 1
                    notes.append(
                        f"{group_name}/{source_name} "
                        f"{year}年第{issue}期网络失败："
                        f"{type(exc).__name__}: {exc}"
                    )
                    if consecutive_network_errors >= 2:
                        notes.append(
                            f"{source_name}连续网络失败，切换下一来源"
                        )
                        break

                except Exception as exc:
                    notes.append(
                        f"{group_name}/{source_name} "
                        f"{year}年第{issue}期失败："
                        f"{type(exc).__name__}: {exc}"
                    )

    # Snapshot fallback: fetch the homepage for change detection.
    try:
        final_url, homepage_html = fetch_html(session, meta["homepage"])
        notes.append(f"官网页面可访问：{final_url}")
        if homepage_html:
            best_snapshot = homepage_html
    except Exception as exc:
        notes.append(f"官网页面失败：{type(exc).__name__}: {exc}")

    return [], notes, best_snapshot


def sanitize_snapshot(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html or "", "lxml")

    for node in soup(["script", "style", "noscript"]):
        node.decompose()

    text = clean_text(soup.get_text(" ", strip=True))
    text = re.sub(
        r"\b20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?\b",
        "<DATE>",
        text,
    )
    text = re.sub(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", "<TIME>", text)
    text = re.sub(
        r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b",
        "<UUID>",
        text,
        flags=re.I,
    )
    text = re.sub(r"\b\d{10,}\b", "<LONG_NUMBER>", text)
    return text[:250_000]


def snapshot_hash(raw_html: str) -> str:
    value = sanitize_snapshot(raw_html)
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_state() -> dict:
    empty_state = {
        "schema_version": STATE_SCHEMA_VERSION,
        "journals": {},
    }
    if not STATE_PATH.exists():
        return empty_state

    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return empty_state

    # Previous focused-watch prototypes may contain false positives from
    # publishing regulations or generic navigation pages. Clear that cache once.
    if int(state.get("schema_version", 0)) != STATE_SCHEMA_VERSION:
        return empty_state

    return state


def article_to_dict(article: Article) -> dict:
    data = asdict(article)
    data["published"] = (
        article.published.isoformat()
        if article.published
        else None
    )
    return data


def article_from_dict(data: dict) -> Article:
    published = data.get("published")
    return Article(
        journal_id=data["journal_id"],
        journal_name=data["journal_name"],
        tier=data["tier"],
        title=data["title"],
        url=data["url"],
        author=data.get("author", ""),
        published=datetime.fromisoformat(published) if published else None,
        summary=data.get("summary", ""),
        source_url=data.get("source_url", ""),
    )


def merge_articles(
    state: dict,
    journal_id: str,
    fresh: Iterable[Article],
    keep: int = 100,
) -> list[Article]:
    journal_state = state.setdefault("journals", {}).setdefault(
        journal_id,
        {},
    )
    bucket = journal_state.setdefault("articles", {})

    for article in fresh:
        bucket[article.key()] = article_to_dict(article)

    ordered = sorted(
        bucket.values(),
        key=lambda item: (
            item.get("published") or "",
            item.get("title") or "",
        ),
        reverse=True,
    )[:keep]

    journal_state["articles"] = {
        (
            f"{item['journal_id']}|{item['title']}|"
            f"{item['url']}|{item.get('published') or ''}"
        ): item
        for item in ordered
    }

    return [article_from_dict(item) for item in ordered]


def make_change_alert(
    journal_id: str,
    previous_hash: str,
    current_hash: str,
) -> Optional[Article]:
    if not previous_hash or not current_hash:
        return None
    if previous_hash == current_hash:
        return None

    meta = JOURNALS[journal_id]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return Article(
        journal_id=journal_id,
        journal_name=meta["name"],
        tier=meta["tier"],
        title=f"《{meta['name']}》相关页面发生变化，请检查最新一期",
        url=meta["homepage"],
        published=now,
        summary=(
            "自动程序本次未能稳定提取论文标题，但监测到主源或官网页面"
            "发生实质变化。建议打开页面确认是否发布了新一期、网络首发"
            "或目录更新。"
        ),
        source_url=meta["homepage"],
    )


def write_debug_html(journal_id: str, raw_html: str) -> None:
    if not raw_html:
        return
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    (DEBUG_DIR / f"{journal_id}.html").write_text(
        raw_html,
        encoding="utf-8",
    )


def build_report(results: dict) -> None:
    lines = [
        "# 《经济研究》《管理世界》专项抓取报告",
        "",
        f"- 运行时间：{datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        "- 策略：国家哲学社会科学文献中心主源＋期刊官网/知网备用＋页面变化提醒",
        "",
    ]

    for journal_id, meta in JOURNALS.items():
        result = results[journal_id]
        lines.extend(
            [
                f"## {meta['name']}",
                f"- 状态：{result['status']}",
                f"- 本次识别：{result['fresh_count']}条",
                f"- RSS累计：{result['retained_count']}条",
                f"- 页面变化：{'是' if result['changed'] else '否'}",
                f"- 详情：{result['detail']}",
                "",
            ]
        )

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def build_index(results: dict) -> None:
    rows = []

    for journal_id, meta in JOURNALS.items():
        result = results[journal_id]
        rows.append(
            "<tr>"
            f"<td>{html_lib.escape(meta['name'])}</td>"
            f"<td>{html_lib.escape(result['status'])}</td>"
            f"<td>{result['retained_count']}</td>"
            f'<td><a href="feeds/{meta["feed"]}">RSS</a></td>'
            "</tr>"
        )

    page = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>经济研究与管理世界专项RSS</title>
<style>
body {{ max-width: 900px; margin: 2rem auto; padding: 0 1rem; font-family: system-ui, sans-serif; line-height: 1.7; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border-bottom: 1px solid #ddd; padding: .7rem; text-align: left; }}
</style>
</head>
<body>
<h1>《经济研究》《管理世界》专项RSS</h1>
<p>主源优先提取最新一期论文；失败时使用官网或知网页面，并以页面变化提醒兜底。</p>
<p><a href="feeds/two-journals.xml">订阅两刊综合RSS</a></p>
<table>
<thead><tr><th>期刊</th><th>状态</th><th>累计条目</th><th>订阅</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
<p><a href="two-journal-report.md">查看专项抓取报告</a></p>
</body>
</html>
"""
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(page, encoding="utf-8")


def main() -> int:
    session = build_session()
    state = load_state()
    results = {}
    retained_by_journal = {}

    for journal_id, meta in JOURNALS.items():
        fresh, notes, snapshot_html = crawl_journal(session, journal_id)
        extracted_count = len(fresh)

        journal_state = state.setdefault("journals", {}).setdefault(
            journal_id,
            {},
        )
        old_hash = journal_state.get("snapshot_hash", "")
        new_hash = snapshot_hash(snapshot_html)
        changed = bool(old_hash and new_hash and old_hash != new_hash)

        if new_hash:
            journal_state["snapshot_hash"] = new_hash

        alert_generated = False
        alert = make_change_alert(journal_id, old_hash, new_hash)
        if not fresh and alert:
            fresh = [alert]
            alert_generated = True
            notes.append("未提取到论文，已生成页面变化提醒")

        retained = merge_articles(state, journal_id, fresh)
        retained_by_journal[journal_id] = retained

        if alert_generated:
            status = "页面变化提醒"
        elif fresh:
            status = "论文提取成功"
        elif retained:
            status = "保留旧RSS"
        else:
            status = "等待有效数据"

        results[journal_id] = {
            "status": status,
            "fresh_count": extracted_count,
            "retained_count": len(retained),
            "changed": changed,
            "detail": "；".join(notes)[-20000:],
        }

        if extracted_count == 0:
            write_debug_html(journal_id, snapshot_html)

        write_feed(
            retained,
            title=f"{meta['name']}专项更新",
            description=f"{meta['name']}最新一期论文与页面变化提醒",
            site_url=meta["homepage"],
            output_path=OUTPUT_DIR / meta["feed"],
        )

    combined = dedupe_articles(
        retained_by_journal["economic-research"]
        + retained_by_journal["management-world"]
    )
    write_feed(
        combined,
        title="经济研究与管理世界综合更新",
        description="两刊最新一期论文与页面变化提醒",
        site_url=(
            "https://asdfghjchen-hub.github.io/"
            "chinese-econ-journal-rss/two-journals.html"
        ),
        output_path=OUTPUT_DIR / "two-journals.xml",
    )

    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    build_report(results)
    build_index(results)

    for journal_id, result in results.items():
        print(
            f"{JOURNALS[journal_id]['name']}: "
            f"{result['status']} / fresh={result['fresh_count']} "
            f"/ retained={result['retained_count']}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
