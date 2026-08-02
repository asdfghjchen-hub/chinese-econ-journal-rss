\
from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable, List, Optional
from urllib.parse import urljoin, urlparse

import feedparser
from bs4 import BeautifulSoup, Tag

from .models import Article
from .utils import clean_text, contains_any, normalize_url, parse_date


NAV_TEXT = {
    "首页", "上一页", "下一页", "更多", "更多>>", "更多 >",
    "过刊", "过刊浏览", "当前期", "本期目录", "查看全部",
    "登录", "注册", "投稿", "投稿系统", "期刊介绍",
}

ARTICLE_HINTS = (
    "abstract", "article", "detail", "show", "content", "reader",
    "magazine", "view", "doi", "dukan",
)


def _same_or_subdomain(base_url: str, target_url: str) -> bool:
    base_host = urlparse(base_url).netloc.lower().removeprefix("www.")
    target_host = urlparse(target_url).netloc.lower().removeprefix("www.")
    return target_host == base_host or target_host.endswith("." + base_host) or base_host.endswith("." + target_host)


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

    deduped = []
    for url in found:
        url = normalize_url(url)
        if url not in deduped:
            deduped.append(url)
    return deduped


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
            if entry.get(field):
                published = parse_date(str(entry[field]))
                if published:
                    break

        author = clean_text(entry.get("author", ""))
        summary = clean_text(BeautifulSoup(entry.get("summary", ""), "lxml").get_text(" ", strip=True))
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
        if 12 <= len(text) <= 1000:
            date = parse_date(text)
            author = ""
            author_match = re.search(r"(?:作者|文\s*/)\s*[:：]?\s*([^|｜;；，,]{2,30})", text)
            if author_match:
                author = clean_text(author_match.group(1))
            return text, date, author
    return "", None, ""


def _anchor_score(
    title: str,
    url: str,
    base_url: str,
    include_patterns: Iterable[str],
    exclude_patterns: Iterable[str],
    min_len: int,
    max_len: int,
) -> int:
    if not (min_len <= len(title) <= max_len):
        return -100
    if title in NAV_TEXT or contains_any(title, exclude_patterns):
        return -100
    if url.startswith(("javascript:", "mailto:", "tel:")):
        return -100
    if url.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".zip", ".rar", ".doc", ".docx")):
        return -100

    score = 0
    if _same_or_subdomain(base_url, url):
        score += 2
    if contains_any(url, include_patterns):
        score += 5
    if contains_any(url, ARTICLE_HINTS):
        score += 3
    if re.search(r"[\u4e00-\u9fff]", title):
        score += 2
    if any(p in title for p in ("研究", "影响", "机制", "效应", "经济", "管理", "创新", "企业", "政策", "发展")):
        score += 1
    if re.search(r"20\d{2}", title):
        score -= 1
    if "pdf" in url.lower():
        score -= 1
    return score


def parse_html_articles(
    html: str,
    source_url: str,
    journal: dict,
    settings: dict,
) -> List[Article]:
    soup = BeautifulSoup(html, "lxml")
    include_patterns = journal.get("include_url_patterns", [])
    exclude_patterns = journal.get("exclude_text_patterns", [])
    selectors = journal.get("selectors", {})

    candidates: List[Article] = []

    # Prefer explicit selectors when a site-specific rule is later added.
    if selectors.get("item") and selectors.get("title"):
        for item in soup.select(selectors["item"]):
            title_node = item.select_one(selectors["title"])
            link_node = item.select_one(selectors.get("link", selectors["title"]))
            if not title_node or not link_node or not link_node.get("href"):
                continue
            title = clean_text(title_node.get_text(" ", strip=True))
            url = normalize_url(urljoin(source_url, link_node["href"]))
            date_node = item.select_one(selectors.get("date", "")) if selectors.get("date") else None
            author_node = item.select_one(selectors.get("author", "")) if selectors.get("author") else None
            candidates.append(
                Article(
                    journal_id=journal["id"],
                    journal_name=journal["name"],
                    tier=journal["tier"],
                    title=title,
                    url=url,
                    author=clean_text(author_node.get_text(" ", strip=True)) if author_node else "",
                    published=parse_date(date_node.get_text(" ", strip=True)) if date_node else None,
                    source_url=source_url,
                )
            )
    else:
        for anchor in soup.find_all("a", href=True):
            title = clean_text(anchor.get("title") or anchor.get_text(" ", strip=True))
            url = normalize_url(urljoin(source_url, anchor["href"]))
            score = _anchor_score(
                title,
                url,
                source_url,
                include_patterns,
                exclude_patterns,
                settings["min_title_length"],
                settings["max_title_length"],
            )
            if score < 5:
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
        key = "".join(article.title.lower().split())
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = article
        elif article.published and not existing.published:
            deduped[key] = article

    values = list(deduped.values())
    values.sort(key=lambda a: (a.published or datetime.min, a.title), reverse=True)
    return values[: settings["max_items_per_source"]]
