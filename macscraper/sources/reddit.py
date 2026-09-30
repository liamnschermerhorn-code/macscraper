"""r/appleswap: posts look like "[USA-CA] [H] MacBook Air M2 24GB/512GB [W] PayPal, Local Cash"."""
from __future__ import annotations

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
        body = p.get("selftext", "") or ""
        if body.strip() in GONE_BODIES or p.get("removed_by_category") or p.get("author") == "[deleted]":
            continue
        status = body_sold_status(body)
        if status == "all":
            continue
        prices = _prices(have.group(1), min_price) or _prices(body, min_price)
        loc = LOC_RE.search(title)
        item = Listing(
            source="reddit/appleswap",
            title=have.group(1).strip(" -|,"),
            url=f"https://redd.it/{p['id']}" if p.get("id") else "https://www.reddit.com" + p.get("permalink", ""),
            price=min(prices) if prices else None,
            shipping=None,
            location=loc.group(1) if loc else "",
            description=body[:4000],
            negotiable=True,
            posted=str(int(p.get("created_utc", 0))),
        )
        if status == "some":
            item.sold_note = "part of this post is crossed out / marked sold - make sure the Mac isn't"
        if p.get("created_utc"):
            item.age_days = (time.time() - float(p["created_utc"])) / 86400
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
