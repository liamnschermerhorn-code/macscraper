from __future__ import annotations

import random
import re
import time

import httpx

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
]

# "$1,550.00" or "$1550" - the comma form needs at least one comma, otherwise "$1550" would read as $155.
PRICE_RE = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{2}))?(?![\d,])")


def client() -> httpx.Client:
    return httpx.Client(
        headers={
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
        },
        follow_redirects=True,
        timeout=25,
        http2=False,
    )


def get(c: httpx.Client, url: str, *, retries: int = 2, on_block=None, **kw) -> httpx.Response:
    """GET with retries. 403/429/503 usually mean "slow down", so those back off harder
    (and call `on_block`, e.g. to re-visit the homepage for fresh cookies) before retrying."""
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            r = c.get(url, **kw)
            if r.status_code in (403, 429, 503) and attempt < retries:
                time.sleep(random.uniform(8, 15) * (attempt + 1))
                if on_block:
                    on_block()
                continue
            r.raise_for_status()
            return r
        except httpx.HTTPError as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise last  # type: ignore[misc]


def polite_pause() -> None:
    time.sleep(random.uniform(1.0, 2.5))


def parse_price(text: str | None) -> float | None:
    """First dollar amount in text. Ranges like "$500 to $700" return the low end."""
    if not text:
        return None
    m = PRICE_RE.search(text)
    if not m:
        return None
    return float(m.group(1).replace(",", "") + "." + (m.group(2) or "00"))
