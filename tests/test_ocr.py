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
