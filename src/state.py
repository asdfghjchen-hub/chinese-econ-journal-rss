from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List

from .models import Article


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"articles": {}, "runs": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"articles": {}, "runs": {}}


def merge_articles(state: dict, new_articles: Iterable[Article], journal_id: str, keep: int = 120) -> List[Article]:
    bucket = state.setdefault("articles", {}).setdefault(journal_id, {})
    for article in new_articles:
        bucket[article.key()] = article.to_dict()

    ordered = sorted(
        bucket.values(),
        key=lambda item: (item.get("published") or "", item.get("title") or ""),
        reverse=True,
    )[:keep]
    state["articles"][journal_id] = {
        _dict_key(item): item for item in ordered
    }
    return [_from_dict(item) for item in ordered]


def mark_run(state: dict, journal_id: str, status: str, detail: str, count: int) -> None:
    state.setdefault("runs", {})[journal_id] = {
        "time": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "status": status,
        "detail": detail,
        "count": count,
    }


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _dict_key(item: dict) -> str:
    published = item.get("published") or ""
    return f"{item.get('journal_id','')}|{item.get('title','')}|{item.get('url','')}|{published}"


def _from_dict(item: dict) -> Article:
    published = datetime.fromisoformat(item["published"]) if item.get("published") else None
    return Article(
        journal_id=item["journal_id"],
        journal_name=item["journal_name"],
        tier=item["tier"],
        title=item["title"],
        url=item["url"],
        author=item.get("author", ""),
        published=published,
        summary=item.get("summary", ""),
        source_url=item.get("source_url", ""),
    )
