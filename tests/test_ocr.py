import argparse

from macscraper import cli, ocr
from macscraper.filters import Criteria, evaluate
from macscraper.models import Listing
from macscraper.sources import craigslist, ebay, reddit

ABOUT_THIS_MAC_M2 = "Chip Apple M2\nMemory 24 GB\nSerial Number FQ9X79G0Y1\nmacOS Sonoma\nTrash\nDesktop"
ABOUT_THIS_MAC_INTEL = "MacBook Pro (13-inch, 2019)\nProcessor 2.3 GHz Quad-Core Intel Core i7\nMemory 16 GB 2133 MHz LPDDR3"


def test_useful_text_keeps_the_specs_and_drops_the_noise():
    out = ocr.useful_text(ABOUT_THIS_MAC_M2)
    assert "Chip Apple M2" in out and "Memory 24 GB" in out and "Serial Number FQ9X79G0Y1" in out
    assert "Trash" not in out and "Desktop" not in out
    assert ocr.useful_text("Hello\nworld\n") == ""


def test_photo_urls_from_each_site():
    html = ('<img src="https://i.ebayimg.com/images/g/AbC~kOkQ/s-l140.jpg"><img src="https://i.ebayimg.com/images/g/AbC~kOkQ/s-l500.jpg">'
            '<img data-zoom-src="https://i.ebayimg.com/thumbs/images/g/Z9yAAOSw/s-l225.webp">')
    assert ebay.image_urls(html) == ["https://i.ebayimg.com/images/g/AbC~kOkQ/s-l1600.jpg",
                                     "https://i.ebayimg.com/images/g/Z9yAAOSw/s-l1600.jpg"]
    cl = '<img src="https://images.craigslist.org/00a0a_k3Jx9_600x450.jpg"><a href="https://images.craigslist.org/00a0a_k3Jx9_1200x900.jpg">'
    assert craigslist.image_urls(cl) == ["https://images.craigslist.org/00a0a_k3Jx9_1200x900.jpg"]
    post = {"selftext": "pics https://i.imgur.com/abc123.jpg", "preview": {"images": [{"source": {"url": "https://preview.redd.it/x.jpg?width=1&amp;s=sig"}}]},
            "media_metadata": {"a": {"s": {"u": "https://preview.redd.it/g1.jpg?width=2&amp;s=sig2"}}}}
    assert reddit.post_images(post) == ["https://preview.redd.it/g1.jpg?width=2&s=sig2", "https://preview.redd.it/x.jpg?width=1&s=sig",
                                        "https://i.imgur.com/abc123.jpg"]


class FakePhoto:
    """A "downloaded" photo whose bytes are just its URL, so the fake OCR engine can pick the text."""

    def __init__(self, url):
        self.content = url.encode()

    def raise_for_status(self):
        pass


class FakeClient:
    def get(self, url, timeout=None):
        return FakePhoto(url)


def possible(title, images):
    it = Listing(source="reddit/appleswap", title=title, url="https://redd.it/" + title[-3:], price=450, shipping=0.0, images=images)
    return evaluate(it, Criteria(max_total=500))


def test_photo_text_settles_possible_listings(monkeypatch):
    texts = {"https://x/m2.jpg": ABOUT_THIS_MAC_M2, "https://x/intel.jpg": ABOUT_THIS_MAC_INTEL, "https://x/blank.jpg": "just a desk\nlamp"}
    monkeypatch.setattr(ocr, "get_backend", lambda *a, **k: (lambda data: texts[data.decode()]))
    monkeypatch.setattr(ocr, "MIN_IMAGE_BYTES", 1)  # the fake photos are tiny
    client = FakeClient()

    m2 = possible("Apple MacBook Air 13 inch Midnight aaa", ["https://x/m2.jpg"])
    intel = possible("Apple MacBook Pro 13 inch Silver bbb", ["https://x/intel.jpg"])
    blank = possible("Apple MacBook Air Starlight ccc", ["https://x/blank.jpg"])
    assert [m2.verdict, intel.verdict, blank.verdict] == ["POSSIBLE"] * 3  # titles say nothing

    logs = []
    cli.read_photos_step(client, [m2, intel, blank], Criteria(max_total=500),
                         argparse.Namespace(ocr_max_images=6), lambda *a, **k: logs.append(" ".join(map(str, a))))
    assert m2.verdict == "MATCH" and m2.chip == "M2" and m2.ram_gb == 24
    assert any("read from photos" in r for r in m2.reasons)
    assert intel.verdict == "REJECT" and "Intel" in intel.reasons[0]
    assert blank.verdict == "POSSIBLE"                                    # nothing readable: unchanged
    assert any("2 changed verdict" in line for line in logs)


def test_no_ocr_engine_is_handled(monkeypatch):
    monkeypatch.setattr(ocr, "get_backend", lambda *a, **k: None)
    it = possible("Apple MacBook Air 13 inch Midnight ddd", ["https://x/a.jpg"])
    logs = []
    cli.read_photos_step(FakeClient(), [it], Criteria(), argparse.Namespace(ocr_max_images=6), lambda *a, **k: logs.append(a[0]))
    assert it.verdict == "POSSIBLE" and "no OCR engine" in logs[0]


# ---- what the real run showed: eBay refused every listing page, and each refusal cost ~40 s ----------------

def test_ebay_page_breaker_stops_asking_after_three_refusals(monkeypatch):
    import httpx

    ebay.reset_page_breaker()
    calls, logs = [], []

    def refused(client, url, **kw):
        calls.append((url, kw.get("retries")))
        raise httpx.HTTPStatusError("403", request=httpx.Request("GET", url), response=httpx.Response(403))

    monkeypatch.setattr(ebay, "get", refused)
    outcomes = []
    for n in range(30):
        try:
            ebay.item_page(None, f"https://www.ebay.com/itm/{n}", logs.append)
        except ebay.PagesBlocked:
            outcomes.append("skipped")
        except httpx.HTTPError:
            outcomes.append("refused")
    assert outcomes[:3] == ["refused"] * 3 and set(outcomes[3:]) == {"skipped"}
    assert len(calls) == 3 and all(retries == 0 for _, retries in calls)   # no 40-second backoff, no 30 requests
    assert len([m for m in logs if "refusing listing pages" in m]) == 1     # said once, not 27 times
    ebay.reset_page_breaker()


def test_ocr_still_runs_on_the_search_result_photo_when_pages_are_blocked(monkeypatch):
    ebay.reset_page_breaker()
    ebay._page_state["fails"] = ebay.PAGE_FAIL_LIMIT            # the breaker has already tripped
    texts = {"https://i.ebayimg.com/images/g/AAA/s-l1600.jpg": ABOUT_THIS_MAC_M2}
    monkeypatch.setattr(ocr, "get_backend", lambda *a, **k: (lambda data: texts[data.decode()]))
    monkeypatch.setattr(ocr, "MIN_IMAGE_BYTES", 1)
    it = Listing(source="ebay", title="Apple MacBook Air 13 inch Midnight eee", url="https://www.ebay.com/itm/1", price=450,
                 shipping=0.0, images=["https://i.ebayimg.com/images/g/AAA/s-l1600.jpg"])
    it = evaluate(it, Criteria(max_total=500))
    assert it.verdict == "POSSIBLE"
    cli.read_photos_step(FakeClient(), [it], Criteria(max_total=500), argparse.Namespace(ocr_max_images=6), lambda *a, **k: None)
    assert it.verdict == "MATCH" and it.ram_gb == 24              # settled from the one photo, no listing page needed
    ebay.reset_page_breaker()


def test_search_card_carries_its_photo():
    html = ('<ul><li class="s-item"><a href="https://www.ebay.com/itm/42"><div class="s-item__title">MacBook Air M2 24GB</div></a>'
            '<img src="https://i.ebayimg.com/images/g/XyZ~AAOS/s-l225.jpg"><span class="s-item__price">$450.00</span></li></ul>')
    (item,) = ebay.parse_search(html)
    assert item.images == ["https://i.ebayimg.com/images/g/XyZ~AAOS/s-l1600.jpg"]


def test_blocked_search_page_is_retried_from_that_page_not_from_page_one(monkeypatch):
    import httpx

    requested, state = [], {"failed": False}

    class Page:
        text = "<html></html>"

    def flaky(client, url, **kw):
        requested.append(url)
        if "_pgn=3" in url and not state["failed"]:
            state["failed"] = True
            raise httpx.HTTPError("403")
        return Page()

    monkeypatch.setattr(ebay, "get", flaky)
    monkeypatch.setattr(ebay, "parse_search", lambda html: [Listing(source="ebay", title="m", url=f"u{len(requested)}-{i}") for i in range(200)])
    monkeypatch.setattr(ebay, "_warm_up", lambda client: None)
    monkeypatch.setattr(ebay.time, "sleep", lambda s: None)
    results, blocked = ebay._run(None, ["macbook"], 575, 250, lambda *a, **k: None)
    pages = [u.split("_pgn=")[1][0] if "_pgn=" in u else "1" for u in requested]
    assert pages == ["1", "2", "3", "3"]            # page 3 retried; pages 1-2 not downloaded again
    assert len(results) == 600 and blocked == []
