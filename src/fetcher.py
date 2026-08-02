from __future__ import annotations

import time
import warnings
from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.exceptions import InsecureRequestWarning
from urllib3.util.retry import Retry


@dataclass
class FetchResult:
    url: str
    text: str
    content_type: str
    status_code: int


class Fetcher:
    def __init__(
        self,
        user_agent: str,
        timeout: int,
        delay: float,
        retry_total: int = 3,
        connect_timeout: int = 15,
    ) -> None:
        self.timeout: Tuple[int, int] = (connect_timeout, timeout)
        self.delay = delay
        self.session = requests.Session()

        retry = Retry(
            total=retry_total,
            connect=retry_total,
            read=max(1, retry_total - 1),
            status=retry_total,
            backoff_factor=0.8,
            status_forcelist=(408, 425, 429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "HEAD"}),
            raise_on_status=False,
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "application/rss+xml;q=0.9,application/atom+xml;q=0.8,*/*;q=0.7"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
            }
        )
        self.cache: Dict[tuple, FetchResult] = {}

    def get(
        self,
        url: str,
        *,
        verify_ssl: bool = True,
        allow_insecure_ssl: bool = False,
        headers: Optional[Mapping[str, str]] = None,
        referer: Optional[str] = None,
    ) -> FetchResult:
        request_headers = dict(headers or {})
        if referer and "Referer" not in request_headers:
            request_headers["Referer"] = referer

        cache_key = (
            url,
            verify_ssl,
            allow_insecure_ssl,
            tuple(sorted(request_headers.items())),
        )
        if cache_key in self.cache:
            return self.cache[cache_key]

        try:
            response = self.session.get(
                url,
                timeout=self.timeout,
                allow_redirects=True,
                verify=verify_ssl,
                headers=request_headers or None,
            )
        except requests.exceptions.SSLError:
            if not allow_insecure_ssl:
                raise

            with warnings.catch_warnings():
                warnings.simplefilter("ignore", InsecureRequestWarning)
                response = self.session.get(
                    url,
                    timeout=self.timeout,
                    allow_redirects=True,
                    verify=False,
                    headers=request_headers or None,
                )

        response.raise_for_status()

        if not response.encoding or response.encoding.lower() == "iso-8859-1":
            response.encoding = response.apparent_encoding or "utf-8"

        result = FetchResult(
            url=response.url,
            text=response.text,
            content_type=response.headers.get("content-type", ""),
            status_code=response.status_code,
        )
        self.cache[cache_key] = result

        if self.delay > 0:
            time.sleep(self.delay)

        return result
