import pytest

from macscraper.filters import Criteria, evaluate, find_chips, find_ram, red_flags
from macscraper.models import Listing

C = Criteria()


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
        ("Mac Studio M2 Max 32GB", "mac studio not wanted"),
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


def test_neither_chip_nor_ram_rejected_unless_loose():
    assert ev("MacBook Air 13 Midnight").verdict == "REJECT"
    it = evaluate(Listing(source="t", title="MacBook Air 13 Midnight", url="u", price=500, shipping=0), Criteria(loose=True))
    assert it.verdict == "POSSIBLE"


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
