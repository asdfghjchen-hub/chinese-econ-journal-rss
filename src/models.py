from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class Article:
    journal_id: str
    journal_name: str
    tier: str
    title: str
    url: str
    author: str = ""
    published: Optional[datetime] = None
    summary: str = ""
    source_url: str = ""

    def key(self) -> str:
        normalized_title = "".join(self.title.lower().split())
        return f"{self.journal_id}|{normalized_title}|{self.url.rstrip('/')}"

    def to_dict(self) -> dict:
        data = asdict(self)
        data["published"] = self.published.isoformat() if self.published else None
        return data
