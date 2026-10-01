"""Parser tests against trimmed-down copies of each site's markup."""
from macscraper.sources import craigslist, ebay, reddit

EBAY_CLASSIC = """
<ul>
<li class="s-item"><a class="s-item__link" href="https://www.ebay.com/itm/123456"><div class="s-item__title"><span>Shop on eBay</span></div></a></li>
<li class="s-item">
  <a class="s-item__link" href="https://www.ebay.com/itm/256356759063?hash=abc">
    <div class="s-item__title"><span>New Listing</span>Apple MacBook Air M2 24GB 1TB Midnight</div></a>
  <span class="SECONDARY_INFO">Pre-Owned</span>
  <span class="s-item__price">$689.00</span>
  <span class="s-item__shipping">+$12.50 shipping</span>
  <span class="s-item__purchase-options">or Best Offer</span>
  <span class="s-item__location">Located in United States</span>
</li>
</ul>"""

EBAY_CARD = """
<ul><li class="s-card" data-listingid="1">
  <a href="https://www.ebay.com/itm/204646903285"><div class="s-card__title"><span>Mac mini M2 24GB 512GB</span><span>Opens in a new window or tab</span></div></a>
  <div class="s-card__subtitle">Pre-Owned · Apple Mac mini</div>
  <span class="s-card__price">$420.00</span>
  <div class="s-card__attribute-row">12 bids · 1d 3h left</div>
  <div class="s-card__attribute-row">Free delivery</div>
</li></ul>"""

CL = """
<ol><li class="cl-static-search-result" title="MacBook Air M2 24GB">
  <a href="https://sfbay.craigslist.org/sfc/sys/d/mba/7800000000.html">
    <div class="title">MacBook Air M2 24GB</div>
    <div class="details"><div class="price">$650</div><div class="location">oakland</div></div>
  </a></li></ol>"""


def test_ebay_classic():
    items = ebay.parse_search(EBAY_CLASSIC)
    assert len(items) == 1
    it = items[0]
    assert it.title == "Apple MacBook Air M2 24GB 1TB Midnight"
    assert it.url == "https://www.ebay.com/itm/256356759063"
    assert (it.price, it.shipping, it.condition) == (689.0, 12.5, "Pre-Owned")
    assert it.negotiable and not it.is_auction


def test_ebay_card():
    (it,) = ebay.parse_search(EBAY_CARD)
    assert it.title == "Mac mini M2 24GB 512GB"
    assert it.price == 420.0 and it.shipping == 0.0 and it.is_auction


def test_craigslist():
    (it,) = craigslist.parse_search(CL, "sfbay")
    assert (it.title, it.price, it.location) == ("MacBook Air M2 24GB", 650.0, "oakland")


def test_reddit():
    data = {"data": {"children": [
        {"data": {"title": "[USA-CA] [H] MacBook Air M2 24GB/512GB [W] PayPal, Local Cash",
                  "selftext": "Timestamps: imgur. Asking $640 shipped.", "permalink": "/r/appleswap/comments/x/y/",
                  "link_flair_text": "Selling", "created_utc": 1}},
        {"data": {"title": "[USA-NY] [H] Mac mini M2 24GB [W] PayPal", "selftext": "$600",
                  "permalink": "/r/appleswap/comments/z/", "link_flair_text": "SOLD"}},
        {"data": {"title": "[USA-TX] [H] PayPal [W] MacBook M2 24GB", "selftext": "",
                  "permalink": "/r/appleswap/comments/w/"}},
    ]}}
    items = reddit.parse_posts(data, 150)
    titles = [i.title for i in items]
    assert "MacBook Air M2 24GB/512GB" in titles
    assert len(items) == 2  # SOLD dropped; the "[H] PayPal" post kept but has no Mac
    assert items[0].price == 640.0


def test_ebay_drops_fewer_words_section():
    html = EBAY_CLASSIC.replace("</ul>", "") + '<li class="srp-river-answer">Results matching fewer words</li>' + \
        '<li class="s-item"><a href="https://www.ebay.com/itm/999"><div class="s-item__title">MacBook Air M1 8GB</div></a>' + \
        '<span class="s-item__price">$400.00</span></li></ul>'
    assert [i.url for i in ebay.parse_search(html)] == ["https://www.ebay.com/itm/256356759063"]


def test_ebay_price_range_and_pagination_url():
    html = EBAY_CLASSIC.replace("$689.00", "$450.00 to $900.00")
    (it,) = ebay.parse_search(html)
    assert it.price == 450.0 and it.price_is_range
    assert ebay.search_url("macbook (24gb,32gb)", 775, 150, page=2).endswith("&_pgn=2")
    assert "_pgn" not in ebay.search_url("macbook", 775, 150)


def test_craigslist_local_vs_shipping_sites():
    (local,) = craigslist.parse_search(CL, "sfbay", local=True)
    (remote,) = craigslist.parse_search(CL, "boston", local=False)
    assert local.shipping == 0.0 and not local.needs_shipping
    assert remote.shipping is None and remote.needs_shipping
    url = craigslist.search_url("sfbay", "macbook", 775, 150, postal="94103", distance=30)
    assert "postal=94103" in url and "search_distance=30" in url
    assert "postal" not in craigslist.search_url("boston", "macbook", 775, 150)


def _post(body, flair="Selling", **extra):
    import time as _t
    d = {"title": "[USA-IN] [H] MacBook Air M2 24GB/512GB [W] PayPal", "selftext": body, "id": "abc",
         "author": "seller1", "permalink": "/r/appleswap/comments/abc/", "link_flair_text": flair,
         "created_utc": _t.time() - 2 * 86400}
    d.update(extra)
    return {"data": {"children": [{"data": d}]}}


def test_reddit_sold_signals_in_post():
    assert reddit.parse_posts(_post("[removed]"), 150) == []
    assert reddit.parse_posts(_post("hi", author="[deleted]"), 150) == []
    assert reddit.parse_posts(_post("hi", flair="SOLD"), 150) == []
    assert reddit.parse_posts(_post("EDIT: sold, thanks all!\n\nMacBook Air M2 24GB $600"), 150) == []
    assert reddit.parse_posts(_post("~~MacBook Air M2 24GB - $600~~"), 150) == []
    assert reddit.parse_posts(_post("MacBook Air M2 24GB - $600 SOLD"), 150) == []
    (it,) = reddit.parse_posts(_post("MacBook Air M2 24GB - $600 - not sold yet, still available"), 150)
    assert not it.sold_note
    (it,) = reddit.parse_posts(_post("~~MacBook Pro M1 16GB - $700~~\nMacBook Air M2 24GB - $600"), 150)
    assert "crossed out" in it.sold_note


def test_reddit_comment_signals():
    comments = [{}, {"data": {"children": [
        {"data": {"author": "buyer", "body": "is this sold?", "replies": {"data": {"children": [
            {"data": {"author": "seller1", "body": "Sale pending, sorry"}}]}}}},
        {"data": {"author": "AppleSwapBot", "body": "Trade confirmed between u/a and u/b"}},
    ]}}]
    sig = reddit.comment_signals(comments, "seller1")
    assert any(s.startswith("seller commented") for s in sig)
    assert any("bot" in s for s in sig)
    assert reddit.comment_signals([{}, {"data": {"children": [
        {"data": {"author": "seller1", "body": "Nope, still available!"}}]}}], "seller1") == []


def test_price_parsing_without_commas():
    from macscraper.http import parse_price
    assert parse_price("$1550 + shipping OBO") == 1550.0
    assert parse_price("$1550.50") == 1550.5
    assert parse_price("$1,550.00") == 1550.0
    assert parse_price("$650") == 650.0
    assert parse_price("US $499.00") == 499.0


def test_reddit_price_belongs_to_the_mac():
    body = ("16-inch M3 Pro MacBook Pro, running macOS Sonoma, keyboard and 12 battery cycles.\n\n"
            "$1550 + shipping OBO.\n\nEach MacBook sale includes the charger, packed for shipping.\n\n"
            "46mm Apple Watch Series 10, scratches on the screen, no damage.\n\n$270 + shipping OBO.")
    assert reddit.mac_prices(body, 150) == [1550.0]
    d = _post(body)
    d["data"]["children"][0]["data"]["title"] = "[USA-IN] [H] MacBook Pro M3 Pro, Apple Watch [W] PayPal"
    (it,) = reddit.parse_posts(d, 150)
    assert it.price == 1550.0
    assert reddit.mac_prices("~~MacBook Air M2 - $500~~\nMacBook Air M2 24GB - $640", 150) == [640.0]


def test_price_followed_by_comma():
    from macscraper.http import parse_price
    assert parse_price("$1000, including shipping") == 1000.0
    assert parse_price("$650, shipped") == 650.0
    assert parse_price("$1,000, obo") == 1000.0


def test_reddit_mac_mini_post_with_shipping_included():
    d = _post("No repairs. I ordered an Apple Studio right before the price increase, so I'm selling this. "
              "Gigabit ethernet. Includes the original box. $1000, including shipping.\n\n"
              "Pictures: https://imgur.com/a/LJO6QZm")
    d["data"]["children"][0]["data"]["title"] = "[USA-NY][H]M4 Mac Mini 24 GB / 512 GB [W]Paypal"
    (it,) = reddit.parse_posts(d, 150)
    assert it.price == 1000.0 and it.shipping == 0.0
    from macscraper.filters import Criteria, evaluate
    assert evaluate(it, Criteria()).reasons[0] == "$1000 over budget"


def test_reddit_prices_without_dollar_sign():
    assert reddit._prices("Asking 650 shipped, local pickup ok", 150) == [650.0]
    assert reddit._prices("700 OBO", 150) == [700.0]
    assert reddit._prices("M2 24GB 512GB, 100% battery, 250 cycles", 150) == []
    assert reddit._prices("Selling for 2 years old, 512 GB", 150) == []
    assert reddit._prices("$640 shipped, or 600 local", 150) == [640.0]


def test_ebay_default_queries_also_find_listings_without_chip_or_ram():
    qs = ebay.DEFAULT_QUERIES
    assert any("(m2,m3,m4)" in q and "gb" not in q.lower() for q in qs)      # chip, no RAM
    assert any("-intel" in q and "(m2" not in q and "24gb" not in q for q in qs)  # neither
    url = ebay.search_url(qs[-1], 575, 150)
    assert "-intel" in url and "%28macbook" in url


def test_manual_links_facebook_uses_city_and_budget():
    from macscraper.cli import manual_links
    links = manual_links(575, "chicago")
    fb = [u for n, u in links.items() if n.startswith("Facebook")]
    assert len(fb) == 4
    assert all("/marketplace/chicago/search?" in u and "maxPrice=575" in u and "creation_time_descend" in u for u in fb)
