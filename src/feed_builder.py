from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from feedgen.feed import FeedGenerator

from .models import Article


def _entry_description(article: Article) -> str:
    parts = [
        f"期刊：{article.journal_name}",
        f"等级：{article.tier}",
    ]
    if article.author:
        parts.append(f"作者：{article.author}")
    if article.published:
        parts.append(f"日期：{article.published:%Y-%m-%d}")
    if article.summary:
        parts.append(article.summary)
    return "<br/>".join(parts)


def write_feed(
    articles: Sequence[Article],
    title: str,
    description: str,
    site_url: str,
    output_path: Path,
) -> None:
    fg = FeedGenerator()
    fg.id(site_url)
    fg.title(title)
    fg.link(href=site_url, rel="alternate")
    fg.description(description)
    fg.language("zh-CN")
    fg.lastBuildDate(datetime.now(timezone.utc))

    for article in sorted(
        articles,
        key=lambda a: (a.published or datetime.min, a.title),
        reverse=True,
    ):
        entry = fg.add_entry(order="append")
        entry.id(article.key())
        entry.title(article.title)
        entry.link(href=article.url)
        entry.description(_entry_description(article))
        if article.author:
            entry.author({"name": article.author})
        if article.published:
            aware = article.published.replace(tzinfo=timezone.utc)
            entry.pubDate(aware)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fg.rss_file(str(output_path), pretty=True)
