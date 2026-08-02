from __future__ import annotations

import argparse
import html
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

import yaml

from .feed_builder import write_feed
from .fetcher import Fetcher
from .models import Article
from .parser import (
    discover_candidate_pages,
    discover_feed_urls,
    is_blocked_redirect,
    parse_existing_feed,
    parse_html_articles,
)
from .state import load_state, mark_run, merge_articles, save_state


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _request_options(
    journal: dict,
    referer: str | None = None,
) -> dict:
    return {
        "verify_ssl": journal.get("verify_ssl", True),
        "allow_insecure_ssl": journal.get("allow_insecure_ssl", False),
        "headers": journal.get("request_headers", {}),
        "referer": referer,
    }


def _dedupe_articles(articles: List[Article]) -> List[Article]:
    deduped: Dict[str, Article] = {}
    for article in articles:
        key = "".join(article.title.lower().split())
        existing = deduped.get(key)
        if existing is None or (
            article.published and not existing.published
        ):
            deduped[key] = article
    return list(deduped.values())


def scrape_journal(
    fetcher: Fetcher,
    journal: dict,
    settings: dict,
) -> tuple[List[Article], List[str]]:
    collected: List[Article] = []
    notes: List[str] = []

    candidate_limit = int(
        journal.get(
            "candidate_page_limit",
            settings.get("candidate_page_limit", 6),
        )
    )
    min_candidate_items = int(journal.get("min_candidate_items", 1))
    stop_after_first_success = bool(
        journal.get("stop_after_first_candidate_success", False)
    )

    for source_url in journal["start_urls"]:
        try:
            page = fetcher.get(
                source_url,
                **_request_options(journal),
            )

            if is_blocked_redirect(page.url):
                notes.append(
                    f"跳过登录/退出重定向: {source_url} -> {page.url}"
                )
                continue

            notes.append(f"HTML {page.status_code}: {page.url}")

            feed_urls = discover_feed_urls(page.text, page.url)
            if feed_urls:
                notes.append(f"发现原生RSS/Atom: {len(feed_urls)}")

            native_items: List[Article] = []
            for feed_url in feed_urls[:3]:
                try:
                    feed_page = fetcher.get(
                        feed_url,
                        **_request_options(journal, referer=page.url),
                    )
                    if is_blocked_redirect(feed_page.url):
                        notes.append(
                            f"原生源跳转至登录/退出页: {feed_page.url}"
                        )
                        continue

                    current = parse_existing_feed(
                        feed_page.text,
                        feed_page.url,
                        journal,
                        journal.get(
                            "max_items_per_source",
                            settings["max_items_per_source"],
                        ),
                    )
                    if current:
                        native_items.extend(current)
                        notes.append(
                            f"原生源读取 {len(current)} 条: {feed_page.url}"
                        )
                        break
                except Exception as exc:
                    notes.append(
                        f"原生源失败 {feed_url}: "
                        f"{type(exc).__name__}: {exc}"
                    )

            if native_items:
                collected.extend(native_items)
                if journal.get("stop_after_first_source_success", False):
                    break
                continue

            candidate_urls = discover_candidate_pages(
                page.text,
                page.url,
                journal,
                candidate_limit,
            )
            if candidate_urls:
                notes.append(
                    f"发现候选目录页 {len(candidate_urls)} 个"
                )

            candidate_items: List[Article] = []
            for candidate_url in candidate_urls:
                try:
                    candidate_page = fetcher.get(
                        candidate_url,
                        **_request_options(journal, referer=page.url),
                    )
                    if is_blocked_redirect(candidate_page.url):
                        notes.append(
                            f"候选页跳转至登录/退出页: {candidate_page.url}"
                        )
                        continue

                    current = parse_html_articles(
                        candidate_page.text,
                        candidate_page.url,
                        journal,
                        settings,
                    )
                    notes.append(
                        f"目录页识别 {len(current)} 条: "
                        f"{candidate_page.url}"
                    )

                    if len(current) < min_candidate_items:
                        notes.append(
                            f"候选页条目不足（要求至少"
                            f"{min_candidate_items}条），继续尝试"
                        )
                        continue

                    candidate_items.extend(current)
                    if stop_after_first_success:
                        notes.append("已采用首个合格的最新目录页")
                        break
                except Exception as exc:
                    notes.append(
                        f"候选页失败 {candidate_url}: "
                        f"{type(exc).__name__}: {exc}"
                    )

            candidate_items = _dedupe_articles(candidate_items)
            if candidate_items:
                collected.extend(candidate_items)
                if journal.get("stop_after_first_source_success", False):
                    break

            should_parse_home = (
                not candidate_items
                or not journal.get("prefer_discovered_pages", True)
            )
            if should_parse_home:
                home_items = parse_html_articles(
                    page.text,
                    page.url,
                    journal,
                    settings,
                )
                collected.extend(home_items)
                notes.append(
                    f"HTML识别 {len(home_items)} 条: {page.url}"
                )
                if (
                    home_items
                    and journal.get("stop_after_first_source_success", False)
                ):
                    break

        except Exception as exc:
            notes.append(
                f"抓取失败 {source_url}: {type(exc).__name__}: {exc}"
            )

    return _dedupe_articles(collected), notes


def build_index(
    journals: list[dict],
    state: dict,
    output_dir: Path,
) -> None:
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
    (output_dir.parent / "index.html").write_text(
        page,
        encoding="utf-8",
    )


def build_report(
    journals: list[dict],
    state: dict,
    path: Path,
) -> None:
    lines = [
        "# 抓取报告",
        "",
        f"- 状态结构版本：{state.get('schema_version', 1)}",
        "",
    ]

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


def upgrade_state_schema(
    state: dict,
    target_version: int,
) -> tuple[dict, bool]:
    current_version = int(state.get("schema_version", 1))
    if current_version >= target_version:
        return state, False

    upgraded = {
        "schema_version": target_version,
        "articles": {},
        "runs": state.get("runs", {}),
    }
    return upgraded, True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="生成中文经管期刊 RSS"
    )
    parser.add_argument("--config", default="journals.yml")
    parser.add_argument("--journal", help="只运行一个期刊ID")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    settings = config["settings"]
    journals = config["journals"]

    if args.journal:
        journals = [
            journal
            for journal in journals
            if journal["id"] == args.journal
        ]
        if not journals:
            raise SystemExit(f"找不到期刊ID: {args.journal}")

    output_dir = Path(settings["output_dir"])
    state_path = Path(settings["state_file"])
    state = load_state(state_path)
    state, upgraded = upgrade_state_schema(
        state,
        settings.get("state_schema_version", 3),
    )
    if upgraded:
        print("State schema upgraded; old article cache was cleared once.")

    fetcher = Fetcher(
        settings["user_agent"],
        settings["timeout_seconds"],
        settings["request_delay_seconds"],
        retry_total=settings.get("retry_total", 3),
        connect_timeout=settings.get("connect_timeout_seconds", 15),
    )

    all_articles: List[Article] = []
    by_tier: dict[str, List[Article]] = defaultdict(list)

    for journal in journals:
        print(f"[{journal['tier']}] {journal['name']}")
        fresh, notes = scrape_journal(
            fetcher,
            journal,
            settings,
        )

        if fresh:
            retained = merge_articles(
                state,
                fresh,
                journal["id"],
                keep=journal.get("state_keep_items", 120),
            )
            status = "成功"
            detail = "；".join(notes)
        else:
            retained = merge_articles(
                state,
                [],
                journal["id"],
                keep=journal.get("state_keep_items", 120),
            )
            status = "保留旧源" if retained else "失败"
            detail = "未识别到新条目；" + "；".join(notes)

        mark_run(
            state,
            journal["id"],
            status,
            detail,
            len(retained),
        )
        write_feed(
            retained,
            title=f"{journal['name']}—最新文章",
            description=(
                f"{journal['name']}官网文章更新"
                "（非官方RSS，由公开网页生成）"
            ),
            site_url=journal["homepage"],
            output_path=output_dir / f"{journal['id']}.xml",
        )

        all_articles.extend(retained)
        by_tier[journal["tier"]].extend(retained)

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
    build_report(
        config["journals"],
        state,
        Path("docs/report.md"),
    )

    failed = [
        journal["name"]
        for journal in journals
        if state.get("runs", {})
        .get(journal["id"], {})
        .get("status")
        == "失败"
    ]
    if failed:
        print("完全失败（无历史条目）:", "、".join(failed))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
