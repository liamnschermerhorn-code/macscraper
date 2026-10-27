"""SearchSpec -> listings -> cheap prefilter -> Claude judge -> sorted results."""
import asyncio
import httpx

from . import config
from .llm import judge_batch
from .models import Judged, Listing, SearchSpec
from .sources import demo, ebay

ORDER = {"MATCH": 0, "POSSIBLE": 1, "REJECT": 2}
BATCH = 10


def prefilter(spec: SearchSpec, listings: list[Listing]) -> tuple[list[Listing], list[Judged]]:
    """Drop duplicates and obvious price failures without spending tokens."""
    seen, keep, out = set(), [], []
    ceiling = spec.max_total + spec.flex.price_stretch
    for l in listings:
        if l.url in seen:
            continue
        seen.add(l.url)
        if l.is_auction and not spec.flex.allow_auctions:
            out.append(Judged(listing=l, verdict="REJECT", reasons=["Auction (you asked for fixed price only)"]))
        elif l.total > ceiling:
            out.append(Judged(listing=l, verdict="REJECT", reasons=[f"${l.total:.0f} total is over your budget"]))
        elif spec.min_price and l.price < spec.min_price:
            out.append(Judged(listing=l, verdict="REJECT", reasons=[f"${l.price:.0f} is suspiciously cheap"]))
        else:
            keep.append(l)
    return keep, out


async def gather(spec: SearchSpec) -> tuple[list[Listing], list[str]]:
    notes, found = [], []
    if config.DEMO:
        for q in spec.search_queries[:1]:
            found += demo.search(q)
        notes.append("Demo mode: these are fake listings.")
    elif config.EBAY_ID and config.EBAY_SECRET:
        async with httpx.AsyncClient(timeout=20) as c:
            res = await asyncio.gather(*[ebay.search(c, config.EBAY_ID, config.EBAY_SECRET, q) for q in spec.search_queries],
                                       return_exceptions=True)
        for q, r in zip(spec.search_queries, res):
            if isinstance(r, Exception):
                notes.append(f"eBay search '{q}' failed: {type(r).__name__}")
            else:
                found += r
    else:
        notes.append("No marketplace is configured on this server (set EBAY_CLIENT_ID / EBAY_CLIENT_SECRET).")
    return found, notes


async def run(client, spec: SearchSpec) -> dict:
    found, notes = await gather(spec)
    keep, judged = prefilter(spec, found)
    keep = keep[: config.MAX_LISTINGS_JUDGED]
    batches = [keep[i:i + BATCH] for i in range(0, len(keep), BATCH)]
    results = await asyncio.gather(*[asyncio.to_thread(judge_batch, client, spec, b) for b in batches],
                                   return_exceptions=True)
    for b, r in zip(batches, results):
        if isinstance(r, Exception):
            notes.append("Some listings could not be judged; shown as POSSIBLE.")
            judged += [Judged(listing=l, verdict="POSSIBLE", reasons=["Judging failed; check by hand"]) for l in b]
        else:
            judged += r
    judged.sort(key=lambda j: (ORDER[j.verdict], j.listing.total))
    return {"notes": notes, "count": len(found), "results": [j.model_dump() for j in judged]}
