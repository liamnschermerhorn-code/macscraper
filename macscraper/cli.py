from __future__ import annotations

import argparse
import csv
import html
import json
import sys
import time
import tomllib
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

import httpx
from rich.console import Console
from rich.table import Table

from .filters import Criteria, evaluate
from .http import client as make_client
from .http import polite_pause
from .models import Listing
from .sources import craigslist, ebay, reddit

console = Console(stderr=True)

DEFAULT_EBAY_QUERIES = [
    "macbook air m2 24gb", "macbook air m3 24gb", "macbook air m4 24gb", "macbook air m4 32gb",
    "macbook pro m2 24gb", "macbook pro m2 pro 32gb", "macbook pro m3 24gb", "macbook pro m4 24gb",
    "mac mini m2 24gb", "mac mini m2 pro 32gb", "mac mini m4 24gb", "mac mini m4 32gb",
    "imac m3 24gb", "imac m4 24gb", "imac m4 32gb",
    "macbook 24gb", "macbook 32gb m2", "mac mini 24gb", "imac 24gb",
]
DEFAULT_CL_QUERIES = ["macbook", "mac mini", "imac"]
DEFAULT_REDDIT_QUERIES = ["24GB", "32GB", "M2", "M3", "M4"]
DEFAULT_CL_SITES = ["sfbay", "losangeles", "newyork", "chicago", "seattle", "boston"]


def load_config(path: Path | None) -> dict:
    if path and path.exists():
        return tomllib.loads(path.read_text())
    return {}


def manual_links(max_total: float) -> dict[str, str]:
    """Sites that need a login or JavaScript - check these by hand."""
    q = quote_plus("macbook 24gb")
    m = int(max_total)
    return {
        "Facebook Marketplace (MacBook 24GB)": f"https://www.facebook.com/marketplace/search/?query={q}&maxPrice={m}&exact=false",
        "Facebook Marketplace (Mac mini 24GB)": f"https://www.facebook.com/marketplace/search/?query={quote_plus('mac mini 24gb')}&maxPrice={m}",
        "OfferUp (MacBook 24GB)": f"https://offerup.com/search?q={q}&PRICE_MAX={m}",
        "OfferUp (Mac mini 24GB)": f"https://offerup.com/search?q={quote_plus('mac mini 24gb')}&PRICE_MAX={m}",
        "Mercari (MacBook 24GB)": f"https://www.mercari.com/search/?keyword={q}&maxPrice={m * 100}&itemStatuses=1",
        "Swappa (MacBook Air M2)": "https://swappa.com/listings/macbook-air-13-2022",
        "Swappa (Mac mini 2023)": "https://swappa.com/listings/mac-mini-2023",
        "Back Market (MacBook M2)": "https://www.backmarket.com/en-us/search?q=macbook%20air%20m2%2024gb",
        "Apple Certified Refurbished Macs": "https://www.apple.com/shop/refurbished/mac",
        "r/appleswap (new)": "https://www.reddit.com/r/appleswap/new/",
    }


def collect(args, cfg: dict, crit: Criteria) -> list[Listing]:
    sources = set(args.sources.split(","))
    search_ceiling = crit.max_total + crit.offer_stretch
    items: list[Listing] = []
    log = console.log
    with make_client() as c:
        if "ebay" in sources:
            items += ebay.search(c, cfg.get("ebay_queries", DEFAULT_EBAY_QUERIES), search_ceiling, crit.min_price, log)
        if "craigslist" in sources:
            sites = args.cl_sites.split(",") if args.cl_sites else cfg.get("craigslist_sites", DEFAULT_CL_SITES)
            items += craigslist.search(c, sites, cfg.get("craigslist_queries", DEFAULT_CL_QUERIES), search_ceiling, crit.min_price, log)
        if "reddit" in sources:
            items += reddit.search(c, cfg.get("reddit_queries", DEFAULT_REDDIT_QUERIES), crit.min_price, log)

        # De-duplicate across queries.
        uniq: dict[str, Listing] = {}
        for it in items:
            uniq.setdefault(it.key, it)
        items = [evaluate(it, crit) for it in uniq.values()]

        if args.deep:
            todo = [it for it in items if it.verdict != "REJECT" and not it.description]
            log(f"deep-checking {len(todo)} candidate pages...")
            for it in todo:
                try:
                    if it.source == "ebay":
                        it.description = ebay.item_details(c, it.url)
                    elif it.source.startswith("craigslist"):
                        it.description = craigslist.item_details(c, it.url)
                except httpx.HTTPError as e:
                    log(f"  couldn't open {it.url}: {e}")
                    continue
                it.reasons = []
                evaluate(it, crit)
                polite_pause()
    return items


def load_seen(path: Path) -> dict[str, str]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def write_outputs(items: list[Listing], out: Path, crit: Criteria, new_keys: set[str]) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    keep = [i for i in items if i.verdict != "REJECT"]
    with open(out / "results.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["verdict", "new", "score", "total", "price", "shipping", "chip", "ram_gb", "source", "title", "location", "notes", "url"])
        for i in keep:
            w.writerow([i.verdict, i.key in new_keys, i.score, i.total, i.price, i.shipping, i.chip, i.ram_gb,
                        i.source, i.title, i.location, "; ".join(i.reasons), i.url])
    (out / "results.json").write_text(json.dumps([asdict(i) for i in items], indent=1))

    def row(i: Listing) -> str:
        total = f"${i.total:,.0f}" if i.total is not None else "?"
        ship = "" if i.shipping is None else (" free ship" if i.shipping == 0 else f" +${i.shipping:.0f} ship")
        new = '<span class="new">NEW</span> ' if i.key in new_keys else ""
        return (
            f'<tr class="{i.verdict.lower()}"><td>{i.verdict}</td><td>{total}<small>{ship}</small></td>'
            f"<td>{html.escape(i.chip or '?')}</td><td>{i.ram_gb or '?'}GB</td>"
            f'<td>{new}<a href="{html.escape(i.url)}" target="_blank">{html.escape(i.title)}</a>'
            f"<br><small>{html.escape(i.source)} {html.escape(i.location)} {html.escape(i.condition)}</small></td>"
            f"<td><small>{html.escape('; '.join(i.reasons))}</small></td></tr>"
        )

    links = "".join(f'<li><a href="{u}" target="_blank">{html.escape(n)}</a></li>' for n, u in manual_links(crit.max_total).items())
    rejects = sorted((i for i in items if i.verdict == "REJECT"), key=lambda i: i.reasons[0] if i.reasons else "")
    page = f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mac deal hunt</title>
<style>
:root{{color-scheme:light dark;--bg:#fff;--fg:#1d1d1f;--mute:#6e6e73;--match:#e3f6e8;--poss:#fff6dc;--line:#ddd}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111;--fg:#eee;--mute:#999;--match:#16361f;--poss:#3a3115;--line:#333}}}}
body{{font:14px -apple-system,system-ui,sans-serif;background:var(--bg);color:var(--fg);margin:16px auto;max-width:1200px;padding:0 16px}}
table{{border-collapse:collapse;width:100%}}td,th{{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}
tr.match{{background:var(--match)}}tr.possible{{background:var(--poss)}}small{{color:var(--mute)}}a{{color:inherit}}
.new{{background:#0a84ff;color:#fff;border-radius:4px;padding:0 4px;font-size:11px}}
.wrap{{overflow-x:auto}}
</style>
<h1>Mac deal hunt</h1>
<p>M2/M3/M4 · {"/".join(str(r) for r in crit.ram_options)}GB RAM · ≤ ${crit.max_total:.0f} delivered · fully working.
Generated {datetime.now():%Y-%m-%d %H:%M}. <b>{sum(i.verdict == "MATCH" for i in items)}</b> matches,
<b>{sum(i.verdict == "POSSIBLE" for i in items)}</b> possibles, {len(rejects)} rejected.</p>
<p><small>MATCH = chip, RAM and price confirmed from the listing, no red flags. POSSIBLE = nothing disqualifying but something
needs checking. Before paying for anything: ask for a photo of <i>About This Mac</i> and of
<i>System Settings → General → Device Management</i> (should be empty), and confirm Find My is off / Activation Lock is disabled.</small></p>
<div class="wrap"><table><tr><th></th><th>Total</th><th>Chip</th><th>RAM</th><th>Listing</th><th>Notes</th></tr>
{"".join(row(i) for i in keep)}</table></div>
<h2>Check by hand</h2><p><small>These need a login or JavaScript, so the scraper can't read them.</small></p><ul>{links}</ul>
<details><summary>Rejected ({len(rejects)})</summary><ul>
{"".join(f'<li><a href="{html.escape(i.url)}">{html.escape(i.title)}</a> <small>{html.escape(i.reasons[0] if i.reasons else "")}</small></li>' for i in rejects)}
</ul></details>"""
    report = out / "report.html"
    report.write_text(page)
    return report


def print_table(items: list[Listing], new_keys: set[str], limit: int) -> None:
    keep = [i for i in items if i.verdict != "REJECT"][:limit]
    t = Table(title="Candidates", show_lines=False)
    for col in ("", "Total", "Chip", "RAM", "Title", "Source", "Notes"):
        t.add_column(col)
    for i in keep:
        style = "green" if i.verdict == "MATCH" else "yellow"
        t.add_row(
            ("NEW " if i.key in new_keys else "") + i.verdict,
            f"${i.total:,.0f}" if i.total is not None else "?",
            i.chip or "?",
            f"{i.ram_gb}GB" if i.ram_gb else "?",
            f"[link={i.url}]{i.title[:70]}[/link]",
            i.source,
            "; ".join(i.reasons)[:80],
            style=style,
        )
    Console().print(t)


def notify(topic: str, fresh: list[Listing]) -> None:
    """Push new matches to your phone with the free ntfy app (https://ntfy.sh)."""
    for i in fresh[:10]:
        total = f"${i.total:.0f}" if i.total is not None else "price ?"
        try:
            httpx.post(
                f"https://ntfy.sh/{topic}",
                content=f"{i.title}\n{total} · {i.source}".encode(),
                headers={"Title": f"Mac {i.verdict}: {i.chip or '?'} {i.ram_gb or '?'}GB {total}", "Click": i.url, "Tags": "computer"},
                timeout=10,
            )
        except httpx.HTTPError as e:
            console.log(f"ntfy failed: {e}")


def run_once(args, cfg: dict, crit: Criteria) -> None:
    items = collect(args, cfg, crit)
    order = {"MATCH": 0, "POSSIBLE": 1, "REJECT": 2}
    items.sort(key=lambda i: (order[i.verdict], -i.score))

    seen_path = Path(args.out) / "seen.json"
    seen = load_seen(seen_path)
    keep = [i for i in items if i.verdict != "REJECT"]
    new_keys = {i.key for i in keep if i.key not in seen}
    now = datetime.now().isoformat(timespec="seconds")
    for i in keep:
        seen.setdefault(i.key, now)

    report = write_outputs(items, Path(args.out), crit, new_keys)
    seen_path.write_text(json.dumps(seen, indent=1))
    print_table(items, new_keys, args.limit)
    console.log(
        f"{sum(i.verdict == 'MATCH' for i in items)} matches, {sum(i.verdict == 'POSSIBLE' for i in items)} possibles, "
        f"{len(new_keys)} new. Report: {report.resolve()}"
    )
    if args.ntfy and new_keys:
        fresh = [i for i in keep if i.key in new_keys and (i.verdict == "MATCH" or args.notify_possible)]
        notify(args.ntfy, fresh)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Find M2/M3/M4 Macs with 24/32GB RAM under budget.")
    p.add_argument("--config", type=Path, default=Path("config.toml"))
    p.add_argument("--sources", default=None, help="comma list: ebay,craigslist,reddit")
    p.add_argument("--max", type=float, default=None, help="max total price incl. shipping (default 700)")
    p.add_argument("--min", type=float, default=None, help="ignore listings cheaper than this (default 150)")
    p.add_argument("--stretch", type=float, default=None, help="keep negotiable listings up to this much over budget (default 75, 0 = off)")
    p.add_argument("--cl-sites", default=None, help="craigslist subdomains, e.g. sfbay,sacramento")
    p.add_argument("--no-auctions", action="store_true")
    p.add_argument("--loose", action="store_true", help="also keep listings that state neither chip nor RAM")
    p.add_argument("--deep", action="store_true", help="open each candidate's page to read specs/description")
    p.add_argument("--watch", type=float, default=0, help="re-run every N minutes")
    p.add_argument("--ntfy", default=None, help="ntfy.sh topic for phone alerts on new matches")
    p.add_argument("--notify-possible", action="store_true", help="also alert on POSSIBLE listings")
    p.add_argument("--out", default="results")
    p.add_argument("--limit", type=int, default=60, help="rows to print in the terminal")
    args = p.parse_args(argv)

    cfg = load_config(args.config)
    args.sources = args.sources or ",".join(cfg.get("sources", ["ebay", "craigslist", "reddit"]))
    args.ntfy = args.ntfy or cfg.get("ntfy_topic")
    args.deep = args.deep or cfg.get("deep", False)
    pick = lambda cli, key, default: cli if cli is not None else cfg.get(key, default)  # noqa: E731
    crit = Criteria(
        max_total=pick(args.max, "max_total", 700.0),
        min_price=pick(args.min, "min_price", 150.0),
        offer_stretch=pick(args.stretch, "offer_stretch", 75.0),
        chips=tuple(cfg.get("chips", ("M2", "M3", "M4"))),
        ram_options=tuple(cfg.get("ram_options", (24, 32))),
        allow_auctions=not (args.no_auctions or cfg.get("no_auctions", False)),
        extra_red_flags=cfg.get("extra_red_flags", []),
        loose=args.loose or cfg.get("loose", False),
    )

    while True:
        try:
            run_once(args, cfg, crit)
        except KeyboardInterrupt:
            sys.exit(130)
        if not args.watch:
            break
        console.log(f"sleeping {args.watch:g} min (Ctrl-C to stop)")
        time.sleep(args.watch * 60)


if __name__ == "__main__":
    main()
