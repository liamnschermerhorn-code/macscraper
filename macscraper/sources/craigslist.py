"""Craigslist: the no-JavaScript search page for each city (`site` = the subdomain,
e.g. sfbay, newyork, chicago, seattle, boston, losangeles)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

from ..http import get, parse_price, polite_pause
from ..models import Listing


def search_url(site: str, query: str, max_price: float, min_price: float,
               postal: str | None = None, distance: int | None = None) -> str:
    params = {"query": query, "min_price": int(min_price), "max_price": int(max_price), "sort": "date"}
    if postal and distance:
        params |= {"postal": postal, "search_distance": int(distance)}
    return f"https://{site}.craigslist.org/search/sss?" + urlencode(params)


def parse_search(html: str, site: str, local: bool = True) -> list[Listing]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for li in soup.select("li.cl-static-search-result, li.cl-search-result, li.result-row"):
        a = li.select_one("a[href]")
        if not a:
            continue
        title_el = li.select_one(".title, .posting-title, .result-title, .label")
        title = (title_el.get_text(" ", strip=True) if title_el else li.get("title")) or a.get_text(" ", strip=True)
        price_el = li.select_one(".price, .priceinfo, .result-price")
        loc_el = li.select_one(".location, .result-hood, .meta")
        out.append(
            Listing(
                source=f"craigslist/{site}" + ("" if local else " (ships?)"),
                title=title,
                url=a["href"],
                price=parse_price(price_el.get_text() if price_el else ""),
                shipping=0.0 if local else None,  # local = pickup; otherwise cost unknown
                location=loc_el.get_text(" ", strip=True).strip("() ") if loc_el else site,
                negotiable=True,
                needs_shipping=not local,
            )
        )
    return out


def search(client: httpx.Client, local_sites: list[str], ship_sites: list[str], queries: list[str],
           max_price: float, min_price: float, log, postal: str | None = None, distance: int | None = None) -> list[Listing]:
    """Local cities: everything (within `distance` miles of `postal`, if set).
    Other cities: kept for now, but filters only pass posts whose seller offers shipping.
    Searches up to 6 cities at once; within a city, one request at a time."""
    jobs = [(s, True) for s in local_sites] + [(s, False) for s in ship_sites if s not in local_sites]
    with ThreadPoolExecutor(max_workers=6) as pool:
        per_site = pool.map(
            lambda job: _search_site(client, job[0], job[1], queries, max_price, min_price, log, postal, distance), jobs
        )
        return [item for items in per_site for item in items]


def _search_site(client: httpx.Client, site: str, local: bool, queries: list[str], max_price: float,
                 min_price: float, log, postal: str | None, distance: int | None) -> list[Listing]:
    results: list[Listing] = []
    tag = f"craigslist/{site}" + ("" if local else " (shipping only)")
    for q in queries:
        url = search_url(site, q, max_price, min_price, postal if local else None, distance if local else None)
        try:
            r = get(client, url)
        except httpx.HTTPError as e:
            log(f"[{tag}] {q!r}: {e}")
            continue
        items = parse_search(r.text, site, local)
        log(f"[{tag}] {q!r}: {len(items)} results")
        results.extend(items)
        polite_pause()
    return results


def item_details(client: httpx.Client, url: str) -> str:
    soup = BeautifulSoup(get(client, url).text, "html.parser")
    parts = [el.get_text(" ", strip=True) for el in soup.select(".attrgroup, #postingbody")]
    return " \n ".join(p.replace("QR Code Link to This Post", "") for p in parts)
