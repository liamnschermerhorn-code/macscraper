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
