from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict

import requests


@dataclass
class FetchResult:
    url: str
    text: str
    content_type: str
    status_code: int


class Fetcher:
    def __init__(self, user_agent: str, timeout: int, delay: float) -> None:
        self.timeout = timeout
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
            }
        )
        self.cache: Dict[str, FetchResult] = {}

    def get(self, url: str) -> FetchResult:
        if url in self.cache:
            return self.cache[url]

        response = self.session.get(url, timeout=self.timeout, allow_redirects=True)
        response.raise_for_status()

        if not response.encoding or response.encoding.lower() == "iso-8859-1":
            response.encoding = response.apparent_encoding or "utf-8"

        result = FetchResult(
            url=response.url,
            text=response.text,
            content_type=response.headers.get("content-type", ""),
            status_code=response.status_code,
        )
        self.cache[url] = result
        time.sleep(self.delay)
        return result
