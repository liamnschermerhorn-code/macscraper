"""r/appleswap: posts look like "[USA-CA] [H] MacBook Air M2 24GB/512GB [W] PayPal, Local Cash"."""
from __future__ import annotations

import html
import re
import time
from urllib.parse import urlencode

import httpx

from ..http import PRICE_RE, get, polite_pause
from ..models import Listing

HAVE_RE = re.compile(r"\[H\](.*?)(?:\[W\]|$)", re.I | re.S)
LOC_RE = re.compile(r"\[(USA?-[A-Z]{2}[^\]]*)\]", re.I)
CLOSED_RE = re.compile(r"sold|closed|complete|traded|pending", re.I)

MAC_RE = re.compile(r"mac\s?book|mac\s?mini|mac\s?studio|\bmba\b|\bmbp\b", re.I)
SOLD_RE = re.compile(r"\b(sold|pending|spf|traded|gone|sale\s+pending)\b", re.I)
NOT_SOLD_RE = re.compile(r"\b(not|isn'?t|never|un)\s*(yet\s+)?(sold|pending|gone)\b|still\s+available", re.I)
STRIKE_RE = re.compile(r"~~(.+?)~~", re.S)
ALL_SOLD_RE = re.compile(
    r"\b(all|everything|both|items?)\s+(items\s+)?(are\s+|is\s+|has\s+been\s+|have\s+been\s+)?(sold|gone|pending|traded)\b|"
    r"\bclos(ed|ing)\s+(this\s+|the\s+)?(post|thread|out)|^\W*(edit|update)\W*(\s*\w+){0,3}\s*sold\b|^\W*sold\W*$",
    re.I | re.M,
)
GONE_BODIES = {"[removed]", "[deleted]"}
SHIPPING_INCLUDED_RE = re.compile(
    r"(including|incl\.?|includes|with|plus\s+free|free)\s+shipping|shipping\s+(is\s+)?(included|incl|free)|"
    r"\bshipped\b|\bships\s+free",
    re.I,
)


def _says_sold(text: str) -> bool:
    return bool(SOLD_RE.search(text)) and not NOT_SOLD_RE.search(text)


def body_sold_status(body: str) -> str | None:
    """"all" if the post says everything (or every Mac in it) is sold, "some" if only part is, else None."""
    if ALL_SOLD_RE.search(body):
        return "all"
    mac_lines = [ln for ln in body.splitlines() if MAC_RE.search(ln)]
    sold_lines = [
        ln for ln in mac_lines
        if any(MAC_RE.search(s) for s in STRIKE_RE.findall(ln)) or _says_sold(STRIKE_RE.sub("", ln) if "~~" in ln else ln)
    ]
    if mac_lines and len(sold_lines) == len(mac_lines):
        return "all"
    return "some" if sold_lines else None


def comment_signals(data: list, op: str) -> list[str]:
    """Look through a post's comments for the seller saying sold/pending, or the swap bot
    confirming a trade. `data` is Reddit's /comments/<id>.json response."""
    found = []

    def walk(children):
        for ch in children:
            c = ch.get("data", {}) if isinstance(ch, dict) else {}
            body, author = c.get("body", "") or "", c.get("author", "") or ""
            if author == op and _says_sold(body):
                found.append("seller commented: " + body.strip().replace("\n", " ")[:60])
            elif "bot" in author.lower() and re.search(r"\bconfirm(ed|ing)?\b", body, re.I):
                found.append("swap bot confirmed a trade in the comments")
            replies = c.get("replies")
            if isinstance(replies, dict):
                walk(replies.get("data", {}).get("children", []))

    if isinstance(data, list) and len(data) > 1:
        walk(data[1].get("data", {}).get("children", []))
    return found


# Other things people sell in the same post; a price after one of these belongs to it, not the Mac.
OTHER_ITEM_RE = re.compile(
    r"apple\s*watch|\bwatch\b|\bipad|\biphone|airpods|\bipod|homepod|apple\s*tv|vision\s*pro|"
    r"studio\s*display|pro\s*display|\bmonitor\b|magic\s*(keyboard|mouse|trackpad)|\bimac\b",
    re.I,
)


def mac_prices(body: str, floor: float) -> list[float]:
    """Prices that follow a Mac mention, before the post moves on to another item.
    In "MacBook Pro ... $1550 OBO. Apple Watch ... $270", only $1550 belongs to the Mac."""
    text = STRIKE_RE.sub("", body)  # crossed-out items are sold; ignore their prices
    found = []
    for mac in MAC_RE.finditer(text):
        nxt = OTHER_ITEM_RE.search(text, mac.end())
        end = nxt.start() if nxt else len(text)
        m = PRICE_RE.search(text, mac.end(), end)
        if m and (v := float(m.group(1).replace(",", ""))) >= floor:
            found.append(v)
    return found


# Prices written without "$": "650 shipped", "asking 700", "800 OBO", "price: 650".
BARE_PRICE_RE = re.compile(
    r"\b(?:asking|price\s*:?|for|at)\s+(\d{3,4}(?:\.\d{2})?)\b(?!\s*(?:gb|tb|mhz|hz|nits|mm|in|inch|\"|cycles?|hours?|days?))|"
    r"\b(\d{3,4}(?:\.\d{2})?)\s*(?:usd|dollars|bucks|shipped|obo|firm|or\s+best\s+offer|\+\s*ship)",
    re.I,
)


def post_images(p: dict, limit: int = 12) -> list[str]:
    """Photo URLs Reddit hands us in the post's JSON (galleries, previews) plus direct imgur links."""
    urls = []
    for meta in (p.get("media_metadata") or {}).values():
        src = meta.get("s") or {}
        if u := src.get("u") or src.get("gif"):
            urls.append(html.unescape(u))
    for img in (p.get("preview") or {}).get("images", []):
        if u := img.get("source", {}).get("url"):
            urls.append(html.unescape(u))
    urls += re.findall(r"https?://i\.imgur\.com/\w+\.(?:jpe?g|png)", p.get("selftext") or "")
    return list(dict.fromkeys(urls))[:limit]


def _prices(text: str, floor: float) -> list[float]:
    vals = []
    for m in PRICE_RE.finditer(text):
        v = float(m.group(1).replace(",", ""))
        if v >= floor:
            vals.append(v)
    if not vals:
        for m in BARE_PRICE_RE.finditer(text):
            v = float(m.group(1) or m.group(2))
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
        body = p.get("selftext", "") or ""
        if body.strip() in GONE_BODIES or p.get("removed_by_category") or p.get("author") == "[deleted]":
            continue
        status = body_sold_status(body)
        if status == "all":
            continue
        prices = _prices(have.group(1), min_price) or mac_prices(body, min_price) or _prices(body, min_price)
        loc = LOC_RE.search(title)
        item = Listing(
            source="reddit/appleswap",
            title=have.group(1).strip(" -|,"),
            url=f"https://redd.it/{p['id']}" if p.get("id") else "https://www.reddit.com" + p.get("permalink", ""),
            price=min(prices) if prices else None,
            shipping=0.0 if SHIPPING_INCLUDED_RE.search(have.group(1) + " " + body) else None,
            location=loc.group(1) if loc else "",
            description=body[:4000],
            negotiable=True,
            posted=str(int(p.get("created_utc", 0))),
        )
        if status == "some":
            item.sold_note = "part of this post is crossed out / marked sold - make sure the Mac isn't"
        if p.get("created_utc"):
            item.age_days = (time.time() - float(p["created_utc"])) / 86400
        item.images = post_images(p)
        item.meta = {"id": p.get("id", ""), "author": p.get("author", ""), "n_prices": len(set(prices))}
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


def check_comments(client: httpx.Client, item: Listing) -> None:
    """Open a post's comments and mark the listing sold (single-item post) or flag it (multi-item)."""
    pid = item.meta.get("id")
    if not pid:
        return
    headers = {"User-Agent": "macscraper/0.1 (personal deal finder)"}
    r = get(client, f"https://www.reddit.com/comments/{pid}.json?limit=200", headers=headers, retries=1)
    signals = comment_signals(r.json(), item.meta.get("author", ""))
    if not signals:
        return
    if item.meta.get("n_prices", 0) <= 1 and any(s.startswith("seller") for s in signals):
        item.sold = True  # one-item post and the seller says it's sold/pending
    item.sold_note = "; ".join(dict.fromkeys(signals))
