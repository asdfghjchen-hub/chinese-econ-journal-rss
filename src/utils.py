from __future__ import annotations

import calendar
import hashlib
import re
from datetime import datetime
from typing import Iterable, Optional
from urllib.parse import urlparse, urlunparse

from dateutil import parser as date_parser


SPACE_RE = re.compile(r"\s+")
DATE_PATTERNS = [
    re.compile(r"(?<!\d)(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?(?!\d)"),
    re.compile(r"(?<!\d)(20\d{2})[-/.年](\d{1,2})月?(?!\d)"),
]


def clean_text(value: str) -> str:
    return SPACE_RE.sub(" ", value or "").strip()


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    query = parsed.query
    if any(token in query.lower() for token in ("utm_", "spm=", "from=")):
        query = ""
    return urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, "")
    )


def stable_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_datetime(year: int, month: int, day: int = 1) -> Optional[datetime]:
    if not 1990 <= year <= 2100:
        return None
    if not 1 <= month <= 12:
        return None

    max_day = calendar.monthrange(year, month)[1]
    if not 1 <= day <= max_day:
        return None

    return datetime(year, month, day)


def parse_date(text: str) -> Optional[datetime]:
    """
    Parse publication dates conservatively.

    The first version used fuzzy parsing on large HTML containers. That could
    interpret issue numbers such as "2026-15" as year-month and raise
    "month must be in 1..12". This version validates every numeric date and
    only applies general dateutil parsing to short RFC/ISO-like date strings.
    """
    text = clean_text(text)
    if not text:
        return None

    for pattern in DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue

        parts = [int(value) for value in match.groups()]
        parsed = _safe_datetime(*parts)
        if parsed:
            return parsed

    # Feed dates are often RFC 2822 or ISO 8601. Avoid fuzzy parsing long
    # Chinese HTML blocks because counters and issue numbers may look like dates.
    looks_like_feed_date = (
        len(text) <= 100
        and (
            "T" in text
            or "GMT" in text.upper()
            or "UTC" in text.upper()
            or re.search(
                r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b", text, re.I
            )
            or re.search(
                r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b",
                text,
                re.I,
            )
        )
    )

    if looks_like_feed_date:
        try:
            parsed = date_parser.parse(text, fuzzy=False)
            if 1990 <= parsed.year <= 2100:
                return parsed.replace(tzinfo=None)
        except (ValueError, OverflowError, TypeError):
            return None

    return None


def contains_any(value: str, patterns: Iterable[str]) -> bool:
    lowered = value.lower()
    return any(pattern.lower() in lowered for pattern in patterns)
