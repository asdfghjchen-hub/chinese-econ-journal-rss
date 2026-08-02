\
from __future__ import annotations

import argparse
import html
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

import yaml

from .feed_builder import write_feed
from .fetcher import Fetcher
from .models import Article
from .parser import discover_feed_urls, parse_existing_feed, parse_html_articles
from .state import load_state, mark_run, merge_articles, save_state


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def scrape_journal(fetcher: Fetcher, journal: dict, settings: dict) -> tuple[List[Article], List[str]]:
    collected: List[Article] = []
    notes: List[str] = []

    for source_url in journal["start_urls"]:
        try:
            page = fetcher.get(source_url)
            notes.append(f"HTML {page.status_code}: {page.url}")

            feed_urls = discover_feed_urls(page.text, page.url)
            if feed_urls:
                notes.append(f"发现原生RSS/Atom: {len(feed_urls)}")

            used_native = False
            for feed_url in feed_urls[:3]:
                try:
                    feed_page = fetcher.get(feed_url)
                    native_items = parse_existing_feed(
                        feed_page.text,
                        feed_page.url,
                        journal,
                        settings["max_items_per_source"],
                    )
                    if native_items:
                        collected.extend(native_items)
                        used_native = True
                        notes.append(f"原生源读取 {len(native_items)} 条: {feed_page.url}")
                        break
                except Exception as exc:
                    notes.append(f"原生源失败 {feed_url}: {type(exc).__name__}: {exc}")

            if not used_native:
                html_items = parse_html_articles(page.text, page.url, journal, settings)
                collected.extend(html_items)
                notes.append(f"HTML识别 {len(html_items)} 条: {page.url}")

        except Exception as exc:
            notes.append(f"抓取失败 {source_url}: {type(exc).__name__}: {exc}")

    deduped: Dict[str, Article] = {}
    for article in collected:
        key = "".join(article.title.lower().split())
        existing = deduped.get(key)
        if existing is None or (article.published and not existing.published):
            deduped[key] = article

    return list(deduped.values()), notes


def build_index(journals: list[dict], state: dict, output_dir: Path) -> None:
    rows = []
    for journal in journals:
        run = state.get("runs", {}).get(journal["id"], {})
        status = run.get("status", "尚未运行")
        count = run.get("count", 0)
        updated = run.get("time", "")
        feed_path = f"feeds/{journal['id']}.xml"
        rows.append(
            "<tr>"
            f"<td>{html.escape(journal['tier'])}</td>"
            f"<td>{html.escape(journal['name'])}</td>"
            f"<td>{html.escape(status)}</td>"
            f"<td>{count}</td>"
            f"<td>{html.escape(updated)}</td>"
            f'<td><a href="{feed_path}">RSS</a></td>'
            "</tr>"
        )

    page = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>中文经管期刊 RSS</title>
<style>
body {{ max-width: 1100px; margin: 2rem auto; padding: 0 1rem; font-family: system-ui, sans-serif; line-height: 1.6; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border-bottom: 1px solid #ddd; padding: .65rem; text-align: left; }}
code {{ background: #f3f3f3; padding: .1rem .3rem; }}
</style>
</head>
<body>
<h1>中文经管期刊 RSS</h1>
<p>单刊源与分级综合源由 GitHub Actions 定时更新。</p>
<p>
<a href="feeds/a1-all.xml">A1综合源</a> ·
<a href="feeds/a2-all.xml">A2综合源</a> ·
<a href="feeds/a3-all.xml">A3综合源</a> ·
<a href="feeds/all-journals.xml">全部期刊综合源</a>
</p>
<table>
<thead><tr><th>等级</th><th>期刊</th><th>状态</th><th>条目</th><th>更新时间</th><th>订阅</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
</body>
</html>
"""
    (output_dir.parent / "index.html").write_text(page, encoding="utf-8")


def build_report(journals: list[dict], state: dict, path: Path) -> None:
    lines = ["# 抓取报告", ""]
    for journal in journals:
        run = state.get("runs", {}).get(journal["id"], {})
        lines.extend(
            [
                f"## {journal['name']}（{journal['tier']}）",
                f"- 状态：{run.get('status', '尚未运行')}",
                f"- 条目：{run.get('count', 0)}",
                f"- 时间：{run.get('time', '')}",
                f"- 详情：{run.get('detail', '')}",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="生成中文经管期刊 RSS")
    parser.add_argument("--config", default="journals.yml")
    parser.add_argument("--journal", help="只运行一个期刊ID")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    settings = config["settings"]
    journals = config["journals"]
    if args.journal:
        journals = [j for j in journals if j["id"] == args.journal]
        if not journals:
            raise SystemExit(f"找不到期刊ID: {args.journal}")

    output_dir = Path(settings["output_dir"])
    state_path = Path(settings["state_file"])
    state = load_state(state_path)

    fetcher = Fetcher(
        settings["user_agent"],
        settings["timeout_seconds"],
        settings["request_delay_seconds"],
    )

    all_articles: List[Article] = []
    by_tier: dict[str, List[Article]] = defaultdict(list)

    for journal in journals:
        print(f"[{journal['tier']}] {journal['name']}")
        fresh, notes = scrape_journal(fetcher, journal, settings)

        if fresh:
            retained = merge_articles(state, fresh, journal["id"])
            status = "成功"
            detail = "；".join(notes)
        else:
            retained = merge_articles(state, [], journal["id"])
            status = "保留旧源" if retained else "失败"
            detail = "未识别到新条目；" + "；".join(notes)

        mark_run(state, journal["id"], status, detail, len(retained))
        write_feed(
            retained,
            title=f"{journal['name']}—最新文章",
            description=f"{journal['name']}官网文章更新（非官方RSS，由公开网页生成）",
            site_url=journal["homepage"],
            output_path=output_dir / f"{journal['id']}.xml",
        )
        all_articles.extend(retained)
        by_tier[journal["tier"]].extend(retained)

    # When running the full job, regenerate aggregate feeds.
    if not args.journal:
        for tier in ("A1", "A2", "A3"):
            write_feed(
                by_tier[tier],
                title=f"中文经管期刊 {tier} 综合源",
                description=f"{tier}期刊最新文章综合订阅",
                site_url="https://github.com/",
                output_path=output_dir / f"{tier.lower()}-all.xml",
            )
        write_feed(
            all_articles,
            title="中文经管重点期刊综合源",
            description="A1、A2、A3重点期刊最新文章综合订阅",
            site_url="https://github.com/",
            output_path=output_dir / "all-journals.xml",
        )

    save_state(state_path, state)
    build_index(config["journals"], state, output_dir)
    build_report(config["journals"], state, Path("docs/report.md"))

    failed = [
        journal["name"]
        for journal in journals
        if state.get("runs", {}).get(journal["id"], {}).get("status") == "失败"
    ]
    if failed:
        print("完全失败（无历史条目）:", "、".join(failed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
