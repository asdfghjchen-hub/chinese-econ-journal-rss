\
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Iterable, Optional
from urllib.parse import urlparse, urlunparse

from dateutil import parser as date_parser


SPACE_RE = re.compile(r"\s+")
DATE_PATTERNS = [
    re.compile(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?"),
    re.compile(r"(20\d{2})[-/.年](\d{1,2})月?"),
]


def clean_text(value: str) -> str:
    return SPACE_RE.sub(" ", value or "").strip()


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    # Remove fragments and common tracking parameters by dropping query only
    # when it contains obvious analytics parameters.
    query = parsed.query
    if any(token in query.lower() for token in ("utm_", "spm=", "from=")):
        query = ""
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, ""))


def stable_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def parse_date(text: str) -> Optional[datetime]:
    text = clean_text(text)
    if not text:
        return None

    for pattern in DATE_PATTERNS:
        match = pattern.search(text)
        if match:
            parts = [int(v) for v in match.groups()]
            if len(parts) == 3:
                return datetime(parts[0], parts[1], parts[2])
            return datetime(parts[0], parts[1], 1)

    try:
        parsed = date_parser.parse(text, fuzzy=True, dayfirst=False)
        if 1990 <= parsed.year <= 2100:
            return parsed.replace(tzinfo=None)
    except (ValueError, OverflowError, TypeError):
        return None
    return None


def contains_any(value: str, patterns: Iterable[str]) -> bool:
    lowered = value.lower()
    return any(pattern.lower() in lowered for pattern in patterns)
