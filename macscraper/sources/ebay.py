"""eBay: HTML search scraping (no key needed), or the official Browse API if you set
EBAY_CLIENT_ID / EBAY_CLIENT_SECRET (free at developer.ebay.com, far more reliable)."""
from __future__ import annotations

import base64
import os
import random
import re
import time
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

from ..http import get, parse_price
from ..models import Listing

# New, Open box, Certified/Excellent/Very good/Good/Seller refurbished, Used. Excludes "For parts" (7000).
WORKING_CONDITIONS = "1000|1500|2000|2010|2020|2030|2500|3000"

CONDITION_RE = re.compile(
    r"(Brand New|New \(Other\)|Open Box|Pre-Owned|Used|Parts Only|For parts or not working|"
    r"(?:Certified|Excellent|Very Good|Good|Seller)\s*-\s*Refurbished|Refurbished)",
    re.I,
)
SHIP_RE = re.compile(r"\+\s?\$(\d[\d,]*\.?\d*)\s+(?:shipping|delivery)", re.I)
FREE_SHIP_RE = re.compile(r"free\s+(?:shipping|delivery)|free\s+local\s+pickup", re.I)
BIDS_RE = re.compile(r"\b\d+\s+bids?\b|\btime\s+left\b|\bending\b", re.I)
LOCATION_RE = re.compile(r"(?:Located in|from)\s+([A-Z][\w .,'-]{2,40})")


def _base_search_url(query: str, max_price: float, min_price: float) -> str:
    params = {
        "_nkw": query,
        "_udlo": int(min_price),
        "_udhi": int(max_price),
        "_sop": 10,  # newly listed first
        "_ipg": 240,
        "LH_ItemCondition": WORKING_CONDITIONS,
        "LH_PrefLoc": 1,  # US only
        "rt": "nc",
    }
    return "https://www.ebay.com/sch/i.html?" + urlencode(params)


def _clean_title(t: str) -> str:
    t = re.sub(r"^\s*(New Listing|NEW LISTING)\s*", "", t)
    t = t.replace("Opens in a new window or tab", "")
    return re.sub(r"\s+", " ", t).strip()


FEWER_WORDS_RE = re.compile(r"Results matching fewer words|Results for fewer words", re.I)


def parse_search(html: str) -> list[Listing]:
    """Handles both the classic `s-item` and the 2025+ `s-card` result markup."""
    # eBay pads short result lists with loosely related items; drop everything after that divider.
    if m := FEWER_WORDS_RE.search(html):
        html = html[: m.start()]
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("li.s-item, li.s-card, li[data-listingid], div.s-item")
    out: list[Listing] = []
    seen: set[str] = set()
    for card in cards:
        link = card.select_one("a[href*='/itm/']")
        if not link:
            continue
        url = link["href"].split("?")[0]
        if url in seen or "/itm/123456" in url:
            continue
        title_el = card.select_one(".s-item__title, .s-card__title, [role='heading'], h3")
        title = _clean_title(title_el.get_text(" ") if title_el else link.get_text(" "))
        if not title or title.lower().startswith("shop on ebay"):
            continue
        seen.add(url)
        text = card.get_text(" ", strip=True)
        price_el = card.select_one(".s-item__price, .s-card__price, [class*='price']")
        price_text = price_el.get_text(" ") if price_el else text
        price = parse_price(price_text)
        shipping = None
        if m := SHIP_RE.search(text):
            shipping = float(m.group(1).replace(",", ""))
        elif FREE_SHIP_RE.search(text):
            shipping = 0.0
        cond = CONDITION_RE.search(text)
        loc = LOCATION_RE.search(text)
        out.append(
            Listing(
                source="ebay",
                title=title,
                url=url,
                price=price,
                shipping=shipping,
                condition=cond.group(0) if cond else "",
                location=loc.group(1).strip() if loc else "",
                is_auction=bool(BIDS_RE.search(text)) and "buy it now" not in text.lower(),
                negotiable="best offer" in text.lower(),
                price_is_range=bool(re.search(r"\$[\d,.]+\s*to\s*\$", price_text)),
            )
        )
    return out


def _warm_up(client: httpx.Client) -> None:
    """Visit the homepage like a browser would, so eBay hands out its session cookies."""
    try:
        client.get("https://www.ebay.com/", headers={"Sec-Fetch-Site": "none"})
    except httpx.HTTPError:
        pass
    time.sleep(random.uniform(1.5, 3))


# eBay's search box understands "(a,b)" as "a OR b", so a few broad searches cover every
# chip/RAM combination. If eBay ever stops honoring that, FALLBACK_QUERIES spells them out.
DEFAULT_QUERIES = [
    "macbook (24gb,32gb)",
    "mac mini (24gb,32gb)",
    "mac studio (m2,m4) 32gb",
    '(macbook,mac mini) (m2,m3,m4) ("24 gb","32 gb")',
    # Listings that name the chip but not the RAM...
    '(macbook,"mac mini","mac studio") (m2,m3,m4)',
    # ...and ones that name neither. Newest first, minus the obvious Intel / small-RAM junk so the
    # few result pages we read are mostly worth reading. The filter judges the rest (POSSIBLE: ask the seller).
    '(macbook,"mac mini","mac studio") -intel -i3 -i5 -i7 -i9 -8gb -16gb -2015 -2016 -2017 -2018 -2019 -2020',
]
FALLBACK_QUERIES = [
    "macbook air m2 24gb", "macbook air m3 24gb", "macbook air m4 24gb", "macbook air m4 32gb",
    "macbook pro m2 24gb", "macbook pro m2 pro 32gb", "macbook pro m3 24gb", "macbook pro m4 24gb",
    "mac mini m2 24gb", "mac mini m2 pro 32gb", "mac mini m4 24gb", "mac mini m4 32gb",
    "macbook 24gb", "macbook 32gb m2", "mac mini 24gb", "mac studio m2 max 32gb", "mac studio 32gb",
]
MAX_PAGES = 3  # 240 results per page, newest first


def search_url(query: str, max_price: float, min_price: float, page: int = 1) -> str:
    return _base_search_url(query, max_price, min_price) + (f"&_pgn={page}" if page > 1 else "")


def _run(client: httpx.Client, queries: list[str], max_price: float, min_price: float, log) -> tuple[list[Listing], list[str]]:
    """Fetch every query (following pages while they stay full). Returns results and still-blocked queries."""
    results: list[Listing] = []
    headers = {"Referer": "https://www.ebay.com/"}
    pending = list(queries)
    blocked: list[str] = []
    for round_ in range(2):  # second round retries whatever eBay blocked, after a long pause
        blocked = []
        for q in pending:
            for page in range(1, MAX_PAGES + 1):
                url = search_url(q, max_price, min_price, page)
                try:
                    r = get(client, url, headers=headers, on_block=lambda: _warm_up(client))
                except httpx.HTTPError as e:
                    status = getattr(getattr(e, "response", None), "status_code", None)
                    log(f"[ebay] {q!r} p{page}: blocked ({status or e})" + ("; will retry" if round_ == 0 else ""))
                    blocked.append(q)
                    time.sleep(random.uniform(10, 20))
                    break
                items = parse_search(r.text)
                if not items and ("captcha" in r.text.lower() or "pardon our interruption" in r.text.lower()):
                    log(f"[ebay] {q!r}: bot check page" + ("; will retry" if round_ == 0 else ""))
                    blocked.append(q)
                    break
                log(f"[ebay] {q!r} p{page}: {len(items)} results")
                results.extend(items)
                headers["Referer"] = url
                time.sleep(random.uniform(3, 6))
                if len(items) < 200 or FEWER_WORDS_RE.search(r.text):
                    break  # last page of real results
        if not blocked:
            break
        pending = blocked
        if round_ == 0:
            log(f"[ebay] retrying {len(blocked)} blocked searches in 60s...")
            time.sleep(60)
            _warm_up(client)
    return results, blocked


def search_html(client: httpx.Client, queries: list[str], max_price: float, min_price: float, log) -> list[Listing]:
    _warm_up(client)
    results, blocked = _run(client, queries, max_price, min_price, log)
    if not results and not blocked and queries == DEFAULT_QUERIES:
        log("[ebay] combined searches found nothing - falling back to one search per model")
        results, blocked = _run(client, FALLBACK_QUERIES, max_price, min_price, log)
    if blocked:
        log("[ebay] some searches stayed blocked - run again later, or set EBAY_CLIENT_ID/SECRET to use the API")
    return results


# ---------------------------------------------------------------- Browse API

def _api_token(client: httpx.Client) -> str:
    cid, secret = os.environ["EBAY_CLIENT_ID"], os.environ["EBAY_CLIENT_SECRET"]
    basic = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    r = client.post(
        "https://api.ebay.com/identity/v1/oauth2/token",
        headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"},
    )
    r.raise_for_status()
    return r.json()["access_token"]


def search_api(client: httpx.Client, queries: list[str], max_price: float, min_price: float, log) -> list[Listing]:
    token = _api_token(client)
    headers = {"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"}
    results: list[Listing] = []
    for q in queries:
        params = {
            "q": q,
            "limit": 200,
            "sort": "newlyListed",
            "filter": (
                f"price:[{int(min_price)}..{int(max_price)}],priceCurrency:USD,"
                "conditionIds:{1000|1500|2000|2010|2020|2030|2500|3000},itemLocationCountry:US"
            ),
        }
        try:
            r = client.get("https://api.ebay.com/buy/browse/v1/item_summary/search", params=params, headers=headers)
            r.raise_for_status()
        except httpx.HTTPError as e:
            log(f"[ebay-api] {q!r}: {e}")
            continue
        items = r.json().get("itemSummaries", [])
        log(f"[ebay-api] {q!r}: {len(items)} results")
        for it in items:
            opts = it.get("buyingOptions", [])
            auction = "AUCTION" in opts and "FIXED_PRICE" not in opts
            price = (it.get("currentBidPrice") if auction else None) or it.get("price") or {}
            ship = None
            if so := it.get("shippingOptions"):
                cost = so[0].get("shippingCost", {}).get("value")
                ship = float(cost) if cost is not None else None
            loc = it.get("itemLocation", {})
            results.append(
                Listing(
                    source="ebay",
                    title=it.get("title", ""),
                    url=it.get("itemWebUrl", "").split("?")[0],
                    price=float(price["value"]) if price.get("value") else None,
                    shipping=ship,
                    condition=it.get("condition", ""),
                    description=it.get("shortDescription", ""),
                    location=", ".join(x for x in (loc.get("city"), loc.get("stateOrProvince")) if x),
                    is_auction=auction,
                    negotiable="BEST_OFFER" in opts,
                    posted=it.get("itemCreationDate", ""),
                )
            )
    return results


def search(client: httpx.Client, queries: list[str], max_price: float, min_price: float, log) -> list[Listing]:
    if os.environ.get("EBAY_CLIENT_ID") and os.environ.get("EBAY_CLIENT_SECRET"):
        try:
            return search_api(client, queries, max_price, min_price, log)
        except (httpx.HTTPError, KeyError) as e:
            log(f"[ebay-api] failed ({e}); falling back to HTML")
    return search_html(client, queries, max_price, min_price, log)


def item_details(client: httpx.Client, url: str) -> str:
    """Condition notes, item specifics and seller description of one item page."""
    r = get(client, url)
    soup = BeautifulSoup(r.text, "html.parser")
    parts = []
    for sel in (
        ".x-item-condition-text, .x-item-condition",
        "[data-testid='ux-layout-section-evo'], .ux-layout-section-evo, .x-about-this-item",
        ".x-bin-price, .x-price-primary",
    ):
        for el in soup.select(sel):
            parts.append(el.get_text(" ", strip=True))
    iframe = soup.select_one("iframe#desc_ifr")
    if iframe and iframe.get("src"):
        try:
            d = get(client, iframe["src"])
            parts.append(BeautifulSoup(d.text, "html.parser").get_text(" ", strip=True)[:6000])
        except httpx.HTTPError:
            pass
    return " \n ".join(parts)
