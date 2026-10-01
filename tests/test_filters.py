import pytest

from macscraper.filters import Criteria, evaluate, find_chips, find_ram, red_flags
from macscraper.models import Listing

C = Criteria(max_total=700)


def ev(title, price=600.0, shipping=0.0, **kw):
    return evaluate(Listing(source="t", title=title, url="u", price=price, shipping=shipping, **kw), C)


@pytest.mark.parametrize(
    "title",
    [
        "Apple MacBook Air 13.6\" M2 24GB RAM 512GB SSD Midnight",
        "Mac mini M4 24GB 512GB - excellent",
        "MacBook Pro 14 M2 Pro 32GB 1TB Space Gray",
        "Apple MacBook Air 15\" M3 8-core 24 GB unified memory 1TB",
        "MacBook Air M2 24GB 1TB - iCloud unlocked, no MDM, no damage",
        "Mac mini M2 24gb/256gb with charger and box",
        "Apple Mac Studio M2 Max 32GB 512GB",
    ],
)
def test_matches(title):
    it = ev(title)
    assert it.verdict == "MATCH", it.reasons


@pytest.mark.parametrize(
    "title,why",
    [
        ("MacBook Air M1 16GB 512GB", "chip"),
        ("MacBook Air M2 8GB 256GB", "RAM"),
        ("MacBook Air M2 16GB 512GB", "RAM"),
        ("MacBook Pro M3 Pro 18GB", "RAM"),
        ("MacBook Pro M3 Pro 36GB", "RAM"),
        ("MacBook Air M2 24GB 512GB FOR PARTS", "red flags"),
        ("MacBook Air M2 24GB iCloud locked", "red flags"),
        ("MacBook Air M2 24GB cracked screen", "red flags"),
        ("MacBook Pro M2 32GB MDM locked", "red flags"),
        ("MacBook Air M2 24GB as-is", "red flags"),
        ("Case for MacBook Air M2 13 inch 2022", "accessory"),
        ("MacBook Air 2020 Intel i5 8GB", "Intel"),
        ("WTB MacBook Air M2 24GB", "wanted"),
        ("Samsung M.2 NVMe SSD 1TB", "not a Mac"),
        ("Mac mini 2020 16GB", "M1 or Intel"),
        ("Apple iMac 24\" M3 24GB 1TB", "imac not wanted"),
        ("Mac Studio 2022 32GB 512GB", "M1 or Intel"),
        ("Mac Studio M1 Max 32GB", "chip"),
        ("Mac Studio M4 Max 36GB", "RAM"),
        ("MacBook Pro 16 2021 32GB", "M1 or Intel"),
    ],
)
def test_rejects(title, why):
    it = ev(title)
    assert it.verdict == "REJECT"
    assert why.lower() in it.reasons[0].lower(), it.reasons


def test_over_budget():
    assert ev("Mac mini M4 32GB", price=900).verdict == "REJECT"
    assert ev("Mac mini M4 32GB", price=650, shipping=60).verdict == "REJECT"


def test_best_offer_stretch():
    it = ev("MacBook Air M2 24GB 1TB", price=709, negotiable=True)
    assert it.verdict == "POSSIBLE"
    assert any("offer" in r for r in it.reasons)
    assert ev("MacBook Air M2 24GB 1TB", price=709).verdict == "REJECT"


def test_possible_when_ram_missing():
    it = ev("MacBook Air M2 13-inch Midnight 512GB")
    assert it.verdict == "POSSIBLE"
    assert "RAM not stated" in it.reasons


def test_year_inference():
    it = ev("Apple Mac mini 2023 24GB 512GB")
    assert it.verdict == "POSSIBLE"
    assert it.chip == "M2?"


def test_neither_chip_nor_ram_is_possible_unless_strict():
    for title in ("MacBook Air 13 Midnight", "Apple Mac mini", "Apple Mac Studio 1TB"):
        it = ev(title)
        assert it.verdict == "POSSIBLE", (title, it.reasons)
        assert any("ask the seller" in r for r in it.reasons)
    strict = evaluate(Listing(source="t", title="MacBook Air 13 Midnight", url="u", price=500, shipping=0), Criteria(loose=False))
    assert strict.verdict == "REJECT"
    # clear Intel giveaways are still rejected even though chip/RAM are missing
    assert ev("Apple Mac mini A1993 Space Gray").verdict == "REJECT"
    assert ev('MacBook Pro 15" 1TB').verdict == "REJECT"
    assert ev("MacBook Air 2019 Intel").verdict == "REJECT"


def test_auction_is_possible():
    assert ev("Mac mini M2 24GB", price=400, is_auction=True).verdict == "POSSIBLE"


def test_description_boilerplate_warns_not_rejects():
    it = ev("MacBook Air M2 24GB 512GB", description="Works perfectly. Please read the description: we do not sell items that are iCloud locked.")
    assert it.verdict == "POSSIBLE"
    assert it.reasons[0].startswith("!!")


def test_parsers():
    assert find_chips("M2 Pro 12-core") == {"M2 Pro"}
    assert find_chips("1TB M.2 NVMe") == set()
    assert find_chips("M2 NVMe SSD") == set()
    assert find_ram("24GB/512GB") == {24}
    assert find_ram("16 GB RAM, 256 GB SSD") == {16}
    assert find_ram("32G unified 1TB") == {32}
    assert red_flags("no scratches, no dents, not locked, never repaired") == []
    assert red_flags("activation lock is off, MDM free") == []
    assert red_flags("iCloud locked") == ["icloud locked"]


def test_macbook_ranks_above_same_price_mini():
    assert ev("MacBook Air M2 24GB 512GB").score > ev("Mac mini M2 24GB 512GB").score


def test_unknown_shipping_or_price_range_is_not_a_match():
    assert ev("MacBook Air M2 24GB 512GB", shipping=None).verdict == "POSSIBLE"
    it = ev("MacBook Air M2 24GB 512GB", price_is_range=True)
    assert it.verdict == "POSSIBLE" and any("several configs" in r for r in it.reasons)


@pytest.mark.parametrize(
    "title",
    [
        'MacBook Pro 13" 2022 A2338 M2 Chip Logic Board 24GB 1TB w/ Touch ID',
        "Apple MacBook Air M2 24GB 512GB Motherboard with Heatsink",
        "MacBook Air 13 M2 A2681 Top Case with Keyboard and Battery",
        "MacBook Pro 14 M2 Pro LCD Display Assembly Space Gray",
        "Mac mini M2 24GB 512GB logic board + power supply",
        "MacBook Air M2 24GB housing chassis",
        "MacBook Air M3 Hard Shell Case 13.6 inch",
        "Mac mini M4 24GB stand and cooling fan",
    ],
)
def test_parts_and_accessories_rejected(title):
    it = ev(title, price=499)
    assert it.verdict == "REJECT", it.reasons
    assert "part" in it.reasons[0] or "accessory" in it.reasons[0], it.reasons


@pytest.mark.parametrize(
    "title",
    [
        "MacBook Air M2 24GB 512GB with charger and case",
        "Mac mini M2 24GB 512GB w/ box + power cable",
        "MacBook Pro 14 M2 Pro 32GB 1TB includes sleeve",
    ],
)
def test_macs_with_extras_still_match(title):
    assert ev(title).verdict == "MATCH", ev(title).reasons


def test_pulled_part_wording_in_condition():
    it = ev("MacBook Pro M2 24GB 1TB", condition="The board was fully tested and removed from a working environment")
    assert it.verdict == "REJECT"


def ev_remote(title, description=""):
    return evaluate(Listing(source="craigslist/boston (ships?)", title=title, url="u", price=600, shipping=None,
                            description=description, needs_shipping=True), C)


def test_out_of_town_craigslist_needs_shipping():
    t = "MacBook Air M2 24GB 512GB"
    assert ev_remote(t).reasons[0].startswith("not local")
    assert ev_remote(t, "Great shape. Local pickup only, cash.").verdict == "REJECT"
    assert ev_remote(t, "Great shape. Won't ship, sorry").verdict == "REJECT"
    for ok in ("Can ship anywhere in the US", "Shipping available, buyer pays", "$640 shipped via UPS", "Happy to ship"):
        it = ev_remote(t, ok)
        assert it.verdict == "POSSIBLE", (ok, it.reasons)  # shipping cost unknown -> never a clean MATCH
        assert any("ships" in r for r in it.reasons)


def test_local_craigslist_unaffected():
    it = evaluate(Listing(source="craigslist/sfbay", title="MacBook Air M2 24GB 512GB", url="u", price=600, shipping=0.0), C)
    assert it.verdict == "MATCH"


def test_mac_studio_year_inference():
    it = ev("Apple Mac Studio 2023 32GB 512GB")
    assert it.verdict == "POSSIBLE" and it.chip == "M2?"


def test_sold_and_stale_handling():
    assert ev("MacBook Air M2 24GB 512GB", sold=True, sold_note="seller commented: sold").verdict == "REJECT"
    it = ev("MacBook Air M2 24GB 512GB", sold_note="swap bot confirmed a trade in the comments")
    assert it.verdict == "POSSIBLE" and it.reasons[0].startswith("!!")
    it = ev("MacBook Air M2 24GB 512GB", age_days=14)
    assert it.verdict == "POSSIBLE" and any("14 days ago" in r for r in it.reasons)
    assert ev("MacBook Air M2 24GB 512GB", age_days=3).verdict == "MATCH"


def test_old_format_serial_means_intel_or_m1():
    from macscraper.filters import find_serial, serial_is_pre_m2
    assert find_serial("Serial: C02XG0FDH03Q, works great") == "C02XG0FDH03Q"
    assert find_serial("S/N FVFGK0XXQ6L4") == "FVFGK0XXQ6L4"
    assert find_serial("Serial number information available on request") is None
    assert serial_is_pre_m2("C02XG0FDH03Q") and serial_is_pre_m2("W88123456AB")
    assert not serial_is_pre_m2("FQ9X79G0Y1") and not serial_is_pre_m2(None)
    # chip not stated + old serial -> rejected
    it = ev("MacBook Pro 24GB 512GB", description="Serial: C02XG0FDH03Q")
    assert it.verdict == "REJECT" and "serial" in it.reasons[0]
    # seller says M2 but the serial is old -> never a clean MATCH
    it = ev("MacBook Pro M2 24GB 512GB", description="Serial: C02XG0FDH03Q")
    assert it.verdict == "POSSIBLE" and it.reasons[0].startswith("!!")
    # modern 10-character serial is fine
    assert ev("MacBook Air M2 24GB 512GB", description="Serial: FQ9X79G0Y1").verdict == "MATCH"


def test_intel_giveaways_without_the_word_intel():
    # the listing that slipped through: 2018 Intel Mac mini, no chip named
    it = ev("Apple Mac mini A1993 3.2GHz 32GB RAM 256GB SSD Gray Z0W200042", price=435, negotiable=True)
    assert it.verdict == "REJECT" and "A1993" in it.reasons[0]
    assert "GHz" in ev("Apple Mac mini 3.2GHz 32GB RAM 256GB SSD").reasons[0]
    assert "gray" in ev("Apple Mac mini 32GB RAM 256GB SSD Space Gray").reasons[0]
    assert ev("MacBook Air A2337 24GB").verdict == "REJECT"     # M1 Air
    assert ev("MacBook Pro A1707 32GB").verdict == "REJECT"     # 2016-17 Intel
    # things that must keep working
    assert ev("MacBook Pro 13 M2 A2338 24GB 512GB").verdict == "MATCH"  # A2338 is also the M2 13"
    assert ev("Mac mini M2 A2686 24GB 512GB").verdict == "MATCH"
    assert ev("MacBook Air M2 24GB 512GB Space Gray").verdict == "MATCH"  # gray is normal on laptops
    assert ev("Mac mini M2 Pro 32GB silver").verdict == "MATCH"


def test_15_inch_macbook_pro_and_old_custom_config_number():
    # the listing that slipped through
    it = ev('MacBook Pro 15" Upgraded - 32GB -1TB -Z0V10001W', price=450)
    assert it.verdict == "REJECT" and "15-inch" in it.reasons[0]
    assert ev("Apple MacBook Pro 15-inch 32GB 1TB").verdict == "REJECT"
    assert ev('15" MacBook Pro 32GB 1TB').verdict == "REJECT"
    assert ev("MacBook Pro 15.4 inch 32GB").verdict == "REJECT"
    assert "Z0V10001W" in ev("MacBook Pro 32GB 1TB Z0V10001W").reasons[0]
    # these must keep working
    assert ev('MacBook Air 15" M2 24GB 512GB').verdict == "MATCH"
    assert ev('MacBook Pro 16" M2 Pro 32GB 1TB').verdict == "MATCH"
    assert ev("MacBook Pro 14 M3 Pro 32GB 1TB, 15 cycles").verdict == "MATCH"
    # chip named but a giveaway disagrees -> flagged, never a clean MATCH
    for title in ('MacBook Pro 15" M2 32GB 1TB', "MacBook Pro M2 32GB 1TB Z0V10001W"):
        it = ev(title)
        assert it.verdict == "POSSIBLE" and it.reasons[0].startswith("!!"), (title, it.reasons)


def test_year_and_intel_wording_checks():
    assert "description says Intel" in ev("MacBook Air 24GB 512GB", description="Late 2018 model, Intel i7").reasons[0]
    # a purchase year in the description is not a model year
    assert ev("MacBook Air M2 24GB 512GB", description="Bought in 2020 for work").verdict == "MATCH"
    # chip named but the title's year says Intel era -> flagged, never a clean MATCH
    it = ev("MacBook Air M2 24GB 512GB 2019")
    assert it.verdict == "POSSIBLE" and it.reasons[0].startswith("!!")
    assert ev("MacBook Air 2022 24GB 512GB").verdict == "POSSIBLE"  # year-inferred chip stays POSSIBLE


def test_part_listings_and_impossible_prices_rejected():
    # the listing that slipped through: a trackpad for a MacBook Pro
    it = ev('Macbook Pro M4 Pro 14 Inch A3401 / M4 14" A3112 Original Touchpad Silver', price=168.30, negotiable=True)
    assert it.verdict == "REJECT" and "part" in it.reasons[0]
    for title in ("MacBook Pro M3 Pro 14 Speakers Left Right", "MacBook Air M2 Webcam Flex Cable",
                  "MacBook Pro M3 Max 16 Charging Board", "MacBook Air M2 Original Battery"):
        assert ev(title, price=300).verdict == "REJECT", title
    # spec-heavy titles of real Macs (they state the RAM) are not parts
    assert ev("MacBook Air M2 24GB 512GB Force Touch trackpad 4-speaker", price=450).verdict == "MATCH"
    # even without the word "touchpad", a Pro chip at $168 is not a whole Mac
    it = ev("MacBook Pro 14 M4 Pro 24GB 512GB Silver", price=168.30)
    assert it.verdict == "REJECT" and "cheap" in it.reasons[0]
    assert "too cheap for a M4 Pro" in ev("MacBook Pro 14 M4 Pro 24GB", price=300).reasons[0]
    # real machines and auctions are unaffected
    assert ev("MacBook Air M2 24GB 512GB", price=300).verdict == "MATCH"
    assert ev("MacBook Pro 14 M4 Pro 24GB", price=120, is_auction=True).verdict == "POSSIBLE"


def test_intel_core_m_is_not_apple_m3():
    from macscraper.filters import find_chips
    # the listing that slipped through: 2017 12" MacBook, Intel Core m3-7Y32
    it = ev('Apple MacBook MMGL2LL/A 12" 256GB m3-7Y32, Rose Gold', price=300)
    assert it.verdict == "REJECT", it.reasons
    assert find_chips("MacBook m3-7Y32 1.2GHz") == set()
    assert find_chips("MacBook Core m5-6Y54") == set()
    assert find_chips("MacBook m3-8100Y") == set()
    assert "Intel Core m" in ev("MacBook 256GB Core m3", price=300).reasons[0]
    # 11"/12" MacBooks are Intel-only even when nothing else says so
    for title in ('Apple MacBook 12" 256GB Rose Gold', 'MacBook Air 11" 2015 8GB', "Apple MacBook 12 inch 512GB Space Gray"):
        r = ev(title, price=300)
        assert r.verdict == "REJECT" and ("12" in r.reasons[0] or "11" in r.reasons[0] or "Intel" in r.reasons[0]), (title, r.reasons)
    # real Apple M3 and hyphenated M-chip titles keep working
    assert find_chips("MacBook Air M3 24GB") == {"M3"}
    assert find_chips("MacBook Air M2-24GB-1TB") == {"M2"}
    assert ev("MacBook Air M3-24GB-512GB", price=450).verdict == "MATCH"
    assert ev('MacBook Pro 14" M4 Pro 12-core 24GB 512GB', price=480).verdict == "MATCH"


def test_touch_bar_rules():
    # no chip named: Intel unless the RAM says it's the 2022 M2 13" Pro
    for title in ('MacBook Pro 13" Touch Bar 512GB', 'MacBook Pro 13" Touch Bar 32GB 1TB'):
        r = ev(title, price=450)
        assert r.verdict == "REJECT" and "Touch Bar" in r.reasons[0], (title, r.reasons)
    assert ev("MacBook Pro TouchBar 2019", price=450).verdict == "REJECT"  # the year rule gets there first
    it = ev('MacBook Pro 13" Touch Bar 24GB 512GB', price=450)
    assert it.verdict == "POSSIBLE" and any("M2 13-inch" in r for r in it.reasons)
    # the M2 13" Pro really has a Touch Bar and is a legitimate match
    assert ev('MacBook Pro 13" M2 Touch Bar 24GB 512GB', price=450).verdict == "MATCH"
    # M3/M4 Pros have no Touch Bar -> flagged
    it = ev('MacBook Pro 14" M3 Touch Bar 24GB 512GB', price=450)
    assert it.verdict == "POSSIBLE" and it.reasons[0].startswith("!!")
    # Touch ID is not Touch Bar
    assert ev("MacBook Air M2 24GB 512GB Touch ID", price=450).verdict == "MATCH"


def test_macbook_only_setting_rejects_desktops():
    only = Criteria(max_total=700, models=("macbook",))
    for title in ("Apple Mac mini M2 24GB 512GB", "Apple Mac Studio M2 Max 32GB 512GB"):
        it = evaluate(Listing(source="t", title=title, url="u", price=600, shipping=0.0), only)
        assert it.verdict == "REJECT" and "not wanted" in it.reasons[0], (title, it.reasons)
    assert evaluate(Listing(source="t", title="MacBook Air M2 24GB 512GB", url="u", price=600, shipping=0.0), only).verdict == "MATCH"


def test_64_and_128gb_ram():
    big = Criteria(max_total=1000, ram_options=(24, 32, 64, 128))
    def run(title, price=700.0, crit=big):
        return evaluate(Listing(source="t", title=title, url="u", price=price, shipping=0.0), crit)
    assert run("MacBook Pro 16 M3 Max 64GB 1TB").verdict == "MATCH"
    it = run("MacBook Pro 16 M4 Max 128GB 2TB")                      # 128 counts as RAM next to a Max chip
    assert it.verdict == "MATCH" and it.ram_gb == 128
    assert run("MacBook Pro 16 M3 Max 128GB RAM 1TB").ram_gb == 128
    # without a Max chip, a bare "128GB" is a drive size, not RAM
    it = run("MacBook Air M2 128GB")
    assert it.verdict == "POSSIBLE" and it.ram_gb is None and "RAM not stated" in it.reasons
    # not wanted unless listed in ram_options
    assert evaluate(Listing(source="t", title="MacBook Pro 16 M3 Max 64GB 1TB", url="u", price=700.0, shipping=0.0),
                    Criteria(max_total=1000)).reasons[0].startswith("RAM 64GB")
    # bigger RAM ranks higher; an M3 Max at $200 is still not a whole working Mac
    assert run("MacBook Pro 16 M3 Max 64GB 1TB").score > run("MacBook Pro 16 M3 Max 24GB 1TB").score
    assert run("MacBook Pro 16 M3 Max 64GB 1TB", price=200).verdict == "REJECT"
