"""Facebook Marketplace, from pages YOU saved.

The scraper never talks to Facebook. You search Marketplace in your own browser, scroll down so more
listings load, and save the page (Chrome / Edge / Firefox: Cmd+S, format "Webpage, Complete"). Drop the
.html files in the `marketplace/` folder (or pass them with --import) and this reads the listings out of
them; they then go through the same checks as every other source.

Two readers, because Facebook's markup changes: the visible listing cards (a link to /marketplace/item/<id>
holding the price, title and place as text), and the JSON data Facebook embeds in the page.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from bs4 import BeautifulSoup

from ..models import Listing

ITEM_RE = re.compile(r"/marketplace/item/(\d{6,})")
PRICE_TOKEN = r"(?:US\s?)?\$\s?\d[\d,]*(?:\.\d{2})?"
PRICE_LINE_RE = re.compile(rf"^(?:{PRICE_TOKEN}|free)(?:\s*{PRICE_TOKEN})*$", re.I)
PRICE_RE = re.compile(r"\$\s?(\d[\d,]*(?:\.\d{2})?)")
PLACE_RE = re.compile(r"^[A-Za-z][A-Za-z .'\-]+,\s*[A-Z]{2}$")  # "Oak Park, IL"
NOISE_RE = re.compile(
    r"^(just listed|sponsored|listed .*ago|\d+\s*(?:min|hr|hour|day|week)s?\s*ago|free shipping|"
    r"ships? .*|shipping .*|\d+ (?:mi|miles?) away|in stock|pending|sold|price drop.*)$",
    re.I,
)


def canonical(item_id: str) -> str:
    return f"https://www.facebook.com/marketplace/item/{item_id}/"


def _money(text: str) -> float | None:
    if re.match(r"^\s*free\s*$", text, re.I):
        return 0.0
    m = PRICE_RE.search(text)
    return float(m.group(1).replace(",", "")) if m else None


# ---------------------------------------------------------------- reader 1: the visible cards
def parse_cards(html: str) -> list[Listing]:
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, Listing] = {}
    for a in soup.find_all("a", href=ITEM_RE):
        item_id = ITEM_RE.search(a["href"]).group(1)
        if item_id in found:
            continue
        lines = [ln.strip() for ln in a.get_text("\n").split("\n") if ln.strip()]
        price = title = place = None
        for ln in lines:
            if PRICE_LINE_RE.match(ln):
                if price is None:
                    price = _money(ln)  # the first price is the current one; a second is the old, struck one
            elif PLACE_RE.match(ln):
                place = place or ln
            elif NOISE_RE.match(ln):
                continue
            elif title is None:
                title = ln
        img = a.find("img")
        if not title and img and img.get("alt"):
            title = re.sub(r"\s+in\s+[A-Z][\w .'\-]+,\s*[A-Z]{2}$", "", img["alt"]).strip()
        if not title:
            continue
        found[item_id] = Listing(
            source="facebook",
            title=title,
            url=canonical(item_id),
            price=price,
            shipping=0.0,  # Marketplace search results are local pickup
            location=place or "",
            negotiable=True,
            images=[img["src"]] if img and img.get("src", "").startswith("http") else [],
        )
    return list(found.values())


# ---------------------------------------------------------------- reader 2: Facebook's embedded JSON
TITLE_RE = re.compile(r'"marketplace_listing_title":"((?:[^"\\]|\\.)*)"')


def _unescape(raw: str) -> str:
    try:
        return json.loads(f'"{raw}"')
    except ValueError:
        return raw


def parse_embedded(html: str) -> list[Listing]:
    out: dict[str, Listing] = {}
    for m in TITLE_RE.finditer(html):
        before, after = html[max(0, m.start() - 600): m.start()], html[m.end(): m.end() + 1500]
        ids = re.findall(r'"id":"(\d{8,})"', before)
        if not ids:
            ids = re.findall(r'"id":"(\d{8,})"', after)[:1]
        if not ids:
            continue
        item_id = ids[-1] if re.findall(r'"id":"(\d{8,})"', before) else ids[0]
        if item_id in out:
            continue
        price_m = re.search(r'"listing_price":\{[^{}]*?"amount":"(\d+(?:\.\d+)?)"', after) or \
            re.search(r'"amount":"(\d+(?:\.\d+)?)"', after)
        city = re.search(r'"city":"([^"]+)"', after)
        state = re.search(r'"state":"([A-Z]{2})"', after)
        photo = re.search(r'"uri":"(https:[^"]+)"', after)
        out[item_id] = Listing(
            source="facebook",
            title=_unescape(m.group(1)),
            url=canonical(item_id),
            price=float(price_m.group(1)) if price_m else None,
            shipping=0.0,
            location=(f"{_unescape(city.group(1))}, {state.group(1)}" if city and state else ""),
            negotiable=True,
            images=[photo.group(1).replace("\\/", "/")] if photo else [],
        )
    return list(out.values())


def parse_page(html: str) -> list[Listing]:
    """Listings in one saved page: the visible cards first, plus any only the embedded data knows about."""
    items = {i.url: i for i in parse_cards(html)}
    for i in parse_embedded(html):
        if i.url not in items:
            items[i.url] = i
        else:  # fill gaps in a card from the embedded data
            card = items[i.url]
            card.price = card.price if card.price is not None else i.price
            card.location = card.location or i.location
            card.images = card.images or i.images
    return list(items.values())


# ---------------------------------------------------------------- files
def find_pages(paths: list[str | Path]) -> list[Path]:
    files: list[Path] = []
    for p in map(Path, paths):
        if p.is_dir():
            files += sorted(f for f in p.rglob("*") if f.suffix.lower() in (".html", ".htm") and f.is_file())
        elif p.is_file():
            files.append(p)
    return files


def load(paths: list[str | Path], log=lambda *_: None) -> list[Listing]:
    files = find_pages(paths)
    if not files:
        return []
    items: dict[str, Listing] = {}
    # Newest file first, so when a listing is in several saved pages the freshest snapshot is the one kept.
    for f in sorted(files, key=lambda f: f.stat().st_mtime, reverse=True):
        try:
            page = parse_page(f.read_text(errors="ignore"))
        except OSError as e:
            log(f"[facebook] couldn't read {f.name}: {e}")
            continue
        age = (time.time() - f.stat().st_mtime) / 86400
        for it in page:
            if age >= 1:
                it.condition = f"from a page you saved {age:.0f} days ago - may be sold"
            items.setdefault(it.key, it)
        log(f"[facebook] {f.name}: {len(page)} listings" if page else
            f"[facebook] {f.name}: no listings found - scroll down to load them, then save as 'Webpage, Complete'")
    return list(items.values())
