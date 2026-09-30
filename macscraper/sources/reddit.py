"""r/appleswap: posts look like "[USA-CA] [H] MacBook Air M2 24GB/512GB [W] PayPal, Local Cash"."""
from __future__ import annotations

import re
from urllib.parse import urlencode

import httpx

from ..http import PRICE_RE, get, polite_pause
from ..models import Listing

HAVE_RE = re.compile(r"\[H\](.*?)(?:\[W\]|$)", re.I | re.S)
LOC_RE = re.compile(r"\[(USA?-[A-Z]{2}[^\]]*)\]", re.I)
CLOSED_RE = re.compile(r"sold|closed|complete|traded|pending", re.I)


def _prices(text: str, floor: float) -> list[float]:
    vals = []
    for m in PRICE_RE.finditer(text):
        v = float(m.group(1).replace(",", ""))
        if v >= floor:
            vals.append(v)
    return vals


def parse_posts(data: dict, min_price: float) -> list[Listing]:
    out = []
    for child in data.get("data", {}).get("children", []):
        p = child.get("data", {})
        title = p.get("title", "")
        flair = p.get("link_flair_text") or ""
        if CLOSED_RE.search(flair):
            continue
        have = HAVE_RE.search(title)
        if not have:
            continue
        body = p.get("selftext", "")
        prices = _prices(have.group(1), min_price) or _prices(body, min_price)
        loc = LOC_RE.search(title)
        item = Listing(
            source="reddit/appleswap",
            title=have.group(1).strip(" -|,"),
            url="https://www.reddit.com" + p.get("permalink", ""),
            price=min(prices) if prices else None,
            shipping=None,
            location=loc.group(1) if loc else "",
            description=body[:4000],
            negotiable=True,
            posted=str(int(p.get("created_utc", 0))),
        )
        if len(set(prices)) > 1:
            item.condition = f"post lists several prices: {', '.join(f'${v:.0f}' for v in sorted(set(prices)))}"
        out.append(item)
    return out


def search(client: httpx.Client, queries: list[str], min_price: float, log) -> list[Listing]:
    results: list[Listing] = []
    headers = {"User-Agent": "macscraper/0.1 (personal deal finder)"}
    for q in queries:
        params = {"q": q, "restrict_sr": 1, "sort": "new", "t": "month", "limit": 100}
        data = None
        for host in ("https://www.reddit.com", "https://old.reddit.com"):
            try:
                r = get(client, f"{host}/r/appleswap/search.json?" + urlencode(params), headers=headers, retries=1)
                data = r.json()
                break
            except (httpx.HTTPError, ValueError) as e:
                log(f"[reddit] {host} {q!r}: {e}")
        if data is None:
            continue
        items = parse_posts(data, min_price)
        log(f"[reddit] {q!r}: {len(items)} open [H] posts")
        results.extend(items)
        polite_pause()
    return results
