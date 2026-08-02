from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Iterable, List, Optional
from urllib.parse import parse_qs, urljoin, urlparse

import feedparser
from bs4 import BeautifulSoup, Tag

from .models import Article
from .utils import clean_text, contains_any, normalize_url, parse_date


NAV_TEXT = {
    "首页",
    "上一页",
    "下一页",
    "更多",
    "更多>>",
    "更多 >",
    "过刊",
    "过刊浏览",
    "当前期",
    "本期目录",
    "查看全部",
    "登录",
    "注册",
    "投稿",
    "投稿系统",
    "期刊介绍",
}

ISSUE_TITLE_RE = re.compile(
    r"^(?:第\s*\d+\s*期|20\d{2}\s*年\s*第?\s*\d+\s*期|"
    r".*第\s*\d+\s*卷\s*第\s*\d+\s*期.*)$"
)

ARTICLE_HINTS = (
    "abstract",
    "article",
    "detail",
    "show",
    "content",
    "reader",
    "view",
    "doi",
    "dukan",
)

STANDARD_FOLLOW_TEXT = (
    "当前期",
    "最新一期",
    "本期目录",
    "当期目录",
    "最新目录",
    "网络首发",
    "优先出版",
    "最新录用",
    "待刊论文",
)

STANDARD_FOLLOW_URL = (
    "/current",
    "current.shtml",
    "/issue/",
    "/issues/",
    "/magazine/getissuecontentlist",
    "/contents/",
    "/toc/",
)

BLOCKED_REDIRECT_HINTS = (
    "quit.aspx",
    "login.aspx",
    "signin",
)


def is_blocked_redirect(url: str) -> bool:
    lowered = url.lower()
    return any(hint in lowered for hint in BLOCKED_REDIRECT_HINTS)


def _same_or_subdomain(base_url: str, target_url: str) -> bool:
    base_host = urlparse(base_url).netloc.lower().removeprefix("www.")
    target_host = urlparse(target_url).netloc.lower().removeprefix("www.")
    return (
        target_host == base_host
        or target_host.endswith("." + base_host)
        or base_host.endswith("." + target_host)
    )


def discover_feed_urls(html: str, base_url: str) -> List[str]:
    soup = BeautifulSoup(html, "lxml")
    found: List[str] = []

    for link in soup.select('link[rel~="alternate"][href]'):
        mime = (link.get("type") or "").lower()
        if "rss" in mime or "atom" in mime or "xml" in mime:
            found.append(urljoin(base_url, link["href"]))

    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "")
        text = clean_text(anchor.get_text(" ", strip=True))
        if "rss" in href.lower() or text.upper() == "RSS":
            found.append(urljoin(base_url, href))

    deduped: List[str] = []
    for url in found:
        normalized = normalize_url(url)
        if normalized not in deduped:
            deduped.append(normalized)
    return deduped


def _extract_candidate_period(url: str, text: str) -> tuple[int, int, int]:
    """
    Return a sortable (year, issue/month, day) tuple.

    Supports:
    - ?Year=2026&Issue=8
    - /dukan/qs/2026-08/01/...
    - text such as 2026年第8期
    """
    parsed = urlparse(url)
    query = {key.lower(): value for key, value in parse_qs(parsed.query).items()}

    year = 0
    issue = 0
    day = 0

    if query.get("year"):
        try:
            year = int(query["year"][0])
        except (ValueError, TypeError):
            pass

    if query.get("issue"):
        try:
            issue = int(query["issue"][0])
        except (ValueError, TypeError):
            pass

    path_match = re.search(
        r"/(20\d{2})[-/](\d{1,2})(?:[-/](\d{1,2}))?",
        parsed.path,
    )
    if path_match:
        year = max(year, int(path_match.group(1)))
        issue = max(issue, int(path_match.group(2)))
        if path_match.group(3):
            day = int(path_match.group(3))

    text_match = re.search(
        r"(20\d{2})\s*年.*?第?\s*(\d{1,2})\s*期",
        text,
    )
    if text_match:
        year = max(year, int(text_match.group(1)))
        issue = max(issue, int(text_match.group(2)))

    return year, issue, day


def discover_candidate_pages(
    html: str,
    base_url: str,
    journal: dict,
    limit: int,
) -> List[str]:
    """
    Discover issue/current/online-first pages and rank newest candidates first.

    v3 distinguishes article pages from issue pages. In particular, AJCASS
    `/Magazine/Show?id=...` links are individual articles; issue pages are
    `/Magazine/GetIssueContentList?Year=...&Issue=...`.
    """
    soup = BeautifulSoup(html, "lxml")
    follow_text = tuple(journal.get("follow_text_patterns", []))
    follow_url = tuple(journal.get("follow_url_patterns", []))
    require_url = tuple(journal.get("candidate_url_require_patterns", []))
    exclude_url = tuple(journal.get("candidate_url_exclude_patterns", []))
    recent_years = journal.get("candidate_recent_years")
    current_year = datetime.utcnow().year

    scored: list[tuple[int, tuple[int, int, int], str]] = []

    def consider(url: str, text: str, base_score: int = 0) -> None:
        normalized = normalize_url(urljoin(base_url, url))
        if normalized == normalize_url(base_url):
            return
        if not _same_or_subdomain(base_url, normalized):
            return
        if exclude_url and contains_any(normalized, exclude_url):
            return
        if require_url and not contains_any(normalized, require_url):
            return

        period = _extract_candidate_period(normalized, text)
        if recent_years is not None and period[0]:
            if period[0] < current_year - int(recent_years):
                return

        lowered_url = normalized.lower()
        score = base_score
        if contains_any(text, STANDARD_FOLLOW_TEXT):
            score += 8
        if contains_any(lowered_url, STANDARD_FOLLOW_URL):
            score += 7
        if follow_text and contains_any(text, follow_text):
            score += 10
        if follow_url and contains_any(normalized, follow_url):
            score += 10
        if period[0]:
            score += 5
        if "archive" in lowered_url or "过刊" in text:
            score -= 3
        if any(
            lowered_url.endswith(ext)
            for ext in (".pdf", ".jpg", ".jpeg", ".png", ".zip", ".rar")
        ):
            return

        threshold = 4 if require_url else 6
        if score >= threshold:
            scored.append((score, period, normalized))

    for anchor in soup.find_all("a", href=True):
        text = clean_text(anchor.get("title") or anchor.get_text(" ", strip=True))
        href = clean_text(anchor.get("href", ""))
        if not href or href.startswith(("javascript:", "mailto:", "tel:")):
            continue
        consider(href, text)

    # Some platforms place issue URLs inside scripts or data attributes.
    script_text = "\n".join(
        script.get_text(" ", strip=True)
        for script in soup.find_all("script")
    )
    script_patterns = list(journal.get("candidate_script_regexes", []))
    for pattern in script_patterns:
        try:
            matches = re.findall(pattern, script_text, flags=re.I)
        except re.error:
            continue
        for match in matches:
            candidate = match[0] if isinstance(match, tuple) else match
            consider(candidate, "", base_score=8)

    # Deduplicate while preserving the strongest/newest occurrence.
    best: dict[str, tuple[int, tuple[int, int, int]]] = {}
    for score, period, url in scored:
        previous = best.get(url)
        key = (score, period)
        if previous is None or key > previous:
            best[url] = key

    # Recency dominates score once a candidate is otherwise admissible.
    ordered = sorted(
        ((score, period, url) for url, (score, period) in best.items()),
        key=lambda item: (item[1], item[0]),
        reverse=True,
    )
    return [url for _, _, url in ordered[:limit]]


def parse_existing_feed(
    raw: str,
    source_url: str,
    journal: dict,
    limit: int,
) -> List[Article]:
    parsed = feedparser.parse(raw)
    articles: List[Article] = []

    for entry in parsed.entries[:limit]:
        title = clean_text(entry.get("title", ""))
        link = normalize_url(entry.get("link", ""))
        if not title or not link:
            continue

        published = None
        for field in ("published", "updated", "created"):
            if not entry.get(field):
                continue
            published = parse_date(str(entry[field]))
            if published:
                break

        author = clean_text(entry.get("author", ""))
        summary = clean_text(
            BeautifulSoup(entry.get("summary", ""), "lxml").get_text(
                " ", strip=True
            )
        )
        articles.append(
            Article(
                journal_id=journal["id"],
                journal_name=journal["name"],
                tier=journal["tier"],
                title=title,
                url=link,
                author=author,
                published=published,
                summary=summary[:800],
                source_url=source_url,
            )
        )

    return articles


def _extract_context(anchor: Tag) -> tuple[str, Optional[datetime], str]:
    container = anchor
    for _ in range(3):
        parent = container.parent
        if not isinstance(parent, Tag):
            break

        container = parent
        text = clean_text(container.get_text(" ", strip=True))
        if 12 <= len(text) <= 500:
            date = parse_date(text)
            author = ""
            author_match = re.search(
                r"(?:作者|文\s*/)\s*[:：]?\s*([^|｜;；，,]{2,40})",
                text,
            )
            if author_match:
                author = clean_text(author_match.group(1))
            return text, date, author

    return "", None, ""


def _anchor_score(
    title: str,
    url: str,
    base_url: str,
    article_patterns: Iterable[str],
    exclude_text_patterns: Iterable[str],
    exclude_url_patterns: Iterable[str],
    min_len: int,
    max_len: int,
    allow_issue_titles: bool,
) -> int:
    if not (min_len <= len(title) <= max_len):
        return -100
    if title in NAV_TEXT or contains_any(title, exclude_text_patterns):
        return -100
    if not allow_issue_titles and ISSUE_TITLE_RE.match(title):
        return -100
    if contains_any(url, exclude_url_patterns):
        return -100
    if url.startswith(("javascript:", "mailto:", "tel:")):
        return -100
    if url.lower().endswith(
        (".jpg", ".jpeg", ".png", ".gif", ".zip", ".rar", ".doc", ".docx")
    ):
        return -100

    score = 0
    if _same_or_subdomain(base_url, url):
        score += 2
    if article_patterns and contains_any(url, article_patterns):
        score += 7
    if contains_any(url, ARTICLE_HINTS):
        score += 2
    if re.search(r"[\u4e00-\u9fff]", title):
        score += 2
    if any(
        token in title
        for token in (
            "研究",
            "影响",
            "机制",
            "效应",
            "经济",
            "管理",
            "创新",
            "企业",
            "政策",
            "发展",
            "治理",
            "市场",
        )
    ):
        score += 1
    if "pdf" in url.lower():
        score += 1

    return score


def _jsonld_articles(
    soup: BeautifulSoup,
    source_url: str,
    journal: dict,
) -> List[Article]:
    result: List[Article] = []

    def walk(value):
        if isinstance(value, list):
            for item in value:
                yield from walk(item)
        elif isinstance(value, dict):
            if "@graph" in value:
                yield from walk(value["@graph"])
            yield value

    for node in soup.select('script[type="application/ld+json"]'):
        raw = node.string or node.get_text(" ", strip=True)
        if not raw:
            continue

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue

        for item in walk(payload):
            item_type = str(item.get("@type", "")).lower()
            if item_type not in {
                "article",
                "scholarlyarticle",
                "newsarticle",
                "report",
            }:
                continue

            title = clean_text(item.get("headline") or item.get("name") or "")
            url = normalize_url(urljoin(source_url, item.get("url", "")))
            if not title or not url:
                continue

            author_data = item.get("author", "")
            if isinstance(author_data, list):
                author = "、".join(
                    clean_text(
                        value.get("name", "")
                        if isinstance(value, dict)
                        else str(value)
                    )
                    for value in author_data
                )
            elif isinstance(author_data, dict):
                author = clean_text(author_data.get("name", ""))
            else:
                author = clean_text(str(author_data))

            result.append(
                Article(
                    journal_id=journal["id"],
                    journal_name=journal["name"],
                    tier=journal["tier"],
                    title=title,
                    url=url,
                    author=author,
                    published=parse_date(
                        str(
                            item.get("datePublished")
                            or item.get("dateModified")
                            or ""
                        )
                    ),
                    summary=clean_text(str(item.get("description", "")))[:800],
                    source_url=source_url,
                )
            )

    return result


def _filter_latest_url_period(
    articles: List[Article],
    journal: dict,
) -> List[Article]:
    pattern = journal.get("latest_url_period_regex")
    if not pattern or not articles:
        return articles

    try:
        compiled = re.compile(pattern, re.I)
    except re.error:
        return articles

    grouped: dict[str, List[Article]] = {}
    unmatched: List[Article] = []

    for article in articles:
        match = compiled.search(article.url)
        if not match:
            unmatched.append(article)
            continue

        period = "".join(match.groups()) if match.groups() else match.group(0)
        grouped.setdefault(period, []).append(article)

    min_items = int(journal.get("latest_url_period_min_items", 3))
    eligible = [
        (period, values)
        for period, values in grouped.items()
        if len(values) >= min_items
    ]
    if not eligible:
        return articles

    latest_period, latest_articles = max(eligible, key=lambda item: item[0])
    return latest_articles


def parse_html_articles(
    html: str,
    source_url: str,
    journal: dict,
    settings: dict,
) -> List[Article]:
    soup = BeautifulSoup(html, "lxml")
    article_patterns = journal.get(
        "article_url_patterns",
        journal.get("include_url_patterns", []),
    )
    exclude_text_patterns = journal.get("exclude_text_patterns", [])
    exclude_url_patterns = journal.get("exclude_url_patterns", [])
    selectors = journal.get("selectors", {})
    max_items = journal.get(
        "max_items_per_source",
        settings["max_items_per_source"],
    )
    min_score = journal.get("min_anchor_score", 7)
    allow_issue_titles = bool(journal.get("allow_issue_titles", False))

    candidates: List[Article] = []
    candidates.extend(_jsonld_articles(soup, source_url, journal))

    if selectors.get("item") and selectors.get("title"):
        for item in soup.select(selectors["item"]):
            title_node = item.select_one(selectors["title"])
            link_selector = selectors.get("link", selectors["title"])
            link_node = item.select_one(link_selector)
            if not title_node or not link_node or not link_node.get("href"):
                continue

            title = clean_text(title_node.get_text(" ", strip=True))
            url = normalize_url(urljoin(source_url, link_node["href"]))

            date_node = (
                item.select_one(selectors["date"])
                if selectors.get("date")
                else None
            )
            author_node = (
                item.select_one(selectors["author"])
                if selectors.get("author")
                else None
            )

            candidates.append(
                Article(
                    journal_id=journal["id"],
                    journal_name=journal["name"],
                    tier=journal["tier"],
                    title=title,
                    url=url,
                    author=(
                        clean_text(author_node.get_text(" ", strip=True))
                        if author_node
                        else ""
                    ),
                    published=(
                        parse_date(date_node.get_text(" ", strip=True))
                        if date_node
                        else None
                    ),
                    source_url=source_url,
                )
            )
    else:
        for anchor in soup.find_all("a", href=True):
            title = clean_text(
                anchor.get("title") or anchor.get_text(" ", strip=True)
            )
            url = normalize_url(urljoin(source_url, anchor["href"]))

            score = _anchor_score(
                title,
                url,
                source_url,
                article_patterns,
                exclude_text_patterns,
                exclude_url_patterns,
                settings["min_title_length"],
                settings["max_title_length"],
                allow_issue_titles,
            )
            if score < min_score:
                continue

            context, date, author = _extract_context(anchor)
            candidates.append(
                Article(
                    journal_id=journal["id"],
                    journal_name=journal["name"],
                    tier=journal["tier"],
                    title=title,
                    url=url,
                    author=author,
                    published=date,
                    summary=context[:800] if context != title else "",
                    source_url=source_url,
                )
            )

    deduped: dict[str, Article] = {}
    for article in candidates:
        if not article.title or not article.url:
            continue

        title_key = "".join(article.title.lower().split())
        existing = deduped.get(title_key)
        if existing is None:
            deduped[title_key] = article
        elif article.published and not existing.published:
            deduped[title_key] = article

    values = list(deduped.values())
    values = _filter_latest_url_period(values, journal)
    values.sort(
        key=lambda article: (
            article.published or datetime.min,
            article.title,
        ),
        reverse=True,
    )
    return values[:max_items]
