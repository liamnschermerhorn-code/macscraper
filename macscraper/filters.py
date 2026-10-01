"""Decide whether a listing matches: M2/M3/M4 Mac, 24 or 32 GB RAM, fully working, within budget.

Every listing gets one of three verdicts:
  MATCH    - chip, RAM and price all confirmed from the listing text, no red flags
  POSSIBLE - nothing disqualifying, but chip or RAM (or price) couldn't be confirmed;
             open it and check / ask the seller
  REJECT   - wrong chip or RAM, over budget, accessory, or a red flag (locked, parts, damage...)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import Listing


@dataclass
class Criteria:
    max_total: float = 500.0
    min_price: float = 250.0  # anything cheaper is almost always a part, an accessory, a scam or a box
    # A Pro/Max/Ultra chip never sells this cheap as a whole working Mac (parts, scams, mislabels).
    min_price_pro: float = 350.0
    chips: tuple[str, ...] = ("M2", "M3", "M4")
    ram_options: tuple[int, ...] = (24, 32)
    allow_auctions: bool = True
    # Assume this much shipping when a listing doesn't say (eBay usually shows it; others don't).
    assumed_shipping: float = 0.0
    # Negotiable listings up to this much over budget are kept as POSSIBLE ("make an offer").
    offer_stretch: float = 75.0
    extra_red_flags: list[str] = field(default_factory=list)
    # Which kinds of Mac to keep: any of "macbook", "mac mini", "imac", "mac studio".
    models: tuple[str, ...] = ("macbook", "mac mini", "mac studio")
    # Score penalty for desktops (Mac mini / Mac Studio), so MacBooks rank first at a similar price. 0 = equal.
    mini_penalty: int = 5
    # Facebook Marketplace city used in the report's links (the part after /marketplace/).
    fb_city: str = "chicago"
    # Posts older than this many days are kept, but only as POSSIBLE.
    stale_days: float = 10
    # Keep listings that state neither chip nor RAM, as POSSIBLE: just ask the seller. False drops them.
    loose: bool = True


MAC_RE = re.compile(r"\b(mac\s?book|macbook|mac\s?mini|imac|mac\s?studio)\b", re.I)

MODEL_RES = {
    "macbook": re.compile(r"\bmac\s?book", re.I),
    "mac mini": re.compile(r"\bmac\s?mini\b", re.I),
    "imac": re.compile(r"\bimac\b", re.I),
    "mac studio": re.compile(r"\bmac\s?studio\b", re.I),
}

# "M2", "M3 Pro", "Apple M4 Max" ... but not "M.2" (SSD form factor) or "M2 NVMe"/"M.2 SSD".
CHIP_RE = re.compile(r"(?<![\w.])m\s?([1-5])(?:\s?(pro|max|ultra))?(?![\w.])", re.I)
NOT_CHIP_AFTER = re.compile(r"^\s*(nvme|ssd|sata|slot|drive|2280|key)", re.I)

# Intel "Core m" processors (12" MacBook, 2015-2017): "Core m3", "m3-7Y32", "m5-6Y54", "m3-8100Y".
# They must never be read as Apple's M3 chip. (The Y-series letter keeps "M2-24GB" safe.)
INTEL_CORE_M_RE = re.compile(r"\bcore\s?m[3579]\b|\bm[3579][-\s]?\d{1,4}y\d{0,2}\b", re.I)

INTEL_RE = re.compile(r"\b(intel|core\s?i[3579]|i[3579][-\s]\d{4}|i[3579]\b|xeon|2012|2013|2014|2015|2016|2017|2018|2019)\b", re.I)

# Intel wording without model years: safe to look for in a long description, where a bare year
# could be a purchase date ("bought in 2020").
INTEL_WORDS_RE = re.compile(r"\b(intel|core\s?i[3579]|i[3579][-\s]\d{4}|xeon)\b", re.I)

# Numbers followed by GB/G (e.g. "24GB", "24 GB", "24G", "24gb ram").
GB_RE = re.compile(r"\b(\d{1,4})\s?(gb|g)\b(?!\s?(?:ps|bps|hz))", re.I)
TB_RE = re.compile(r"\b\d\s?tb\b", re.I)
RAM_SIZES = {8, 16, 18, 24, 32, 36, 48, 64, 96, 128, 192}
STORAGE_ONLY = {256, 512, 1000, 1024, 2000, 2048}
# Words that, right after a size, mean it's storage rather than memory.
STORAGE_WORDS = re.compile(r"^\s*(ssd|storage|hd|hdd|flash|disk|drive|nvme|rom)", re.I)
RAM_WORDS = re.compile(r"^\s*(ram|memory|unified|mem|ddr|lpddr)", re.I)

# Model-year -> chip inference, used only when the listing never names the chip.
YEAR_HINTS = [
    (re.compile(r"mac\s?studio.*\b2023\b|\b2023\b.*mac\s?studio", re.I), "M2"),
    (re.compile(r"mac\s?studio.*\b2025\b|\b2025\b.*mac\s?studio", re.I), "M4"),
    (re.compile(r"macbook\s?air.*\b(2022|2023)\b|\b(2022|2023)\b.*macbook\s?air", re.I), "M2"),
    (re.compile(r"macbook\s?air.*\b2024\b|\b2024\b.*macbook\s?air", re.I), "M3"),
    (re.compile(r"macbook\s?air.*\b2025\b|\b2025\b.*macbook\s?air", re.I), "M4"),
    (re.compile(r"mac\s?mini.*\b2023\b|\b2023\b.*mac\s?mini", re.I), "M2"),
    (re.compile(r"mac\s?mini.*\b2024\b|\b2024\b.*mac\s?mini", re.I), "M4"),
    (re.compile(r"imac.*\b2023\b|\b2023\b.*imac", re.I), "M3"),
    (re.compile(r"imac.*\b2024\b|\b2024\b.*imac", re.I), "M4"),
    (re.compile(r"macbook\s?pro.*\b2024\b|\b2024\b.*macbook\s?pro", re.I), "M4"),
]

# Model years that can only be M1 or Intel.
OLD_YEAR_RE = re.compile(
    r"(macbook\s?air|mac\s?mini).{0,40}\b(20(0\d|1\d|20))\b|\b(20(0\d|1\d|20))\b.{0,40}(macbook\s?air|mac\s?mini)|"
    r"imac.{0,40}\b(20(0\d|1\d|21))\b|\b(20(0\d|1\d|21))\b.{0,40}imac|"
    r"macbook\s?pro.{0,40}\b(20(0\d|1\d|20|21))\b|\b(20(0\d|1\d|20|21))\b.{0,40}macbook\s?pro|"
    r"mac\s?studio.{0,40}\b2022\b|\b2022\b.{0,40}mac\s?studio",
    re.I,
)

# Hard disqualifiers. Each is checked for a nearby negation ("not locked", "no damage").
RED_FLAGS = [
    r"for\s+parts", r"parts\s+only", r"as[\s-]is", r"repair", r"broken", r"cracked", r"crack",
    r"damaged?", r"damage", r"dead\s+pixels?", r"lines?\s+on\s+(the\s+)?screen", r"screen\s+issue",
    r"water", r"liquid", r"spill", r"icloud\s+lock(ed)?", r"activation\s+lock(ed)?", r"locked",
    r"lock", r"mdm", r"remote\s+management", r"managed\s+by", r"enterprise", r"bypass",
    r"blacklist(ed)?", r"stolen", r"password\s+(protected|locked)", r"(bios|efi|firmware)\s+(lock|password)",
    r"won'?t\s+(turn|power|boot)", r"doesn'?t\s+(turn|power|boot|work)", r"not\s+working",
    r"no\s+power", r"no\s+display", r"does\s+not\s+(turn|power|boot|work)", r"untested",
    r"no\s+(ssd|logic\s*board|motherboard|board)", r"missing\s+(keys?|parts?|screen|board)",
    r"swollen", r"bad\s+battery", r"service\s+battery", r"kernel\s+panic", r"flickering",
    r"read\s+(the\s+)?description", r"see\s+description", r"box\s+only", r"empty\s+box",
    r"logic\s*board\s+only", r"removed\s+from\s+(a\s+)?(working|functional|donor)", r"pulled\s+from", r"screen\s+only", r"housing\s+only", r"replica", r"fake",
]
RED_FLAG_RE = [re.compile(r"\b" + p + r"\b", re.I) for p in RED_FLAGS]

# Things that can appear harmlessly next to a red-flag word.
SAFE_CONTEXT = re.compile(
    r"(no|not|never|zero|without|free\s+of|nothing|isn'?t|is\s+not|none|0)\s+(\w+\s+){0,2}$", re.I
)
SAFE_PHRASES = re.compile(
    r"(icloud|activation|mdm)[\s-]*(free|unlocked|clean|removed|off|signed\s+out)|"
    r"unlocked|lock\s+screen|screen\s+lock|caps\s+lock|touch\s+id|water\s*proof|"
    r"clean\s+(icloud|mdm)|(apple|official)\s+repair(ed)?|repair\s+program|"
    r"never\s+(been\s+)?repaired",
    re.I,
)

# Words that mean the listing is a component, not a computer. Always disqualifying, even
# next to "with" ("Logic Board 24GB w/ Touch ID" is still just a board).
PART_RE = re.compile(
    r"\b(logic\s*board|mother\s*board|main\s*board|system\s*board|board\s+only|"
    r"top\s*case|bottom\s*case|lower\s*case|upper\s*case|palm\s*rest|chassis|housing|enclosure|"
    r"(lcd|display|screen|retina)\s+(assembly|panel|replacement)|lcd|"
    r"replacement\s+(screen|battery|keyboard|display|part)|battery\s+(for|replacement)|"
    r"heat\s*sink|hinge|donor|a\d{4}\s+board|parts?\s+(lot|unit|machine)|"
    r"(i/?o|charging|power|usb[-\s]?c)\s+board|power\s+button)\b",
    re.I,
)
# Component words that also show up in genuine spec-heavy titles ("Force Touch trackpad", "6-speaker
# sound system"). A whole Mac's title states its RAM; a part listing usually doesn't, so these only
# count as a part when no RAM size is given.
WEAK_PART_RE = re.compile(
    r"\b(track\s*pad|touch\s*pad|speakers?|web\s*cam|camera\s+module|flex\s+cable|"
    r"original\s+(keyboard|battery|screen|display|fan|logic))\b",
    re.I,
)
# Add-ons that are fine when they come *with* a Mac ("MacBook Air M2 24GB with charger")
# but mean an accessory listing otherwise ("MacBook Air M2 Hard Shell Case").
ACCESSORY_RE = re.compile(
    r"\b(case|shell|skin|sleeve|cover|protector|charger|adapter|cable|dock|docking|stand|hub|fan|"
    r"keyboard\s+cover|decal|sticker|bag|backpack|compatible\s+with|fits?)\b",
    re.I,
)
WITH_RE = re.compile(r"\b(with|w/|incl(udes?|uding)?|plus|and)\b|\+|w/", re.I)


def is_accessory(title: str) -> bool:
    for m in ACCESSORY_RE.finditer(title):
        if m.group(0).lower() in ("compatible with", "fits", "fit"):
            return True
        if not WITH_RE.search(title[: m.start()]):
            return True
    return False


FOR_MAC_RE = re.compile(r"\bfor\s+(apple\s+)?(mac\s?book|mac\s?mini|imac)", re.I)
WANTED_RE = re.compile(r"\b(wtb|want\s+to\s+buy|looking\s+for|iso|in\s+search\s+of|wanted)\b", re.I)


SHIPS_RE = re.compile(
    r"\b((will|can|could|happy\s+to|willing\s+to|able\s+to|open\s+to|ok\s+to|glad\s+to)\s+(ship|mail|deliver)|"
    r"shipping\s+(is\s+)?(available|ok|okay|possible|offered|included|avail)|"
    r"ships?\s+(anywhere|nationwide|to\s+you|within|in\s+the\s+us|free|via|usps|ups|fedex)|"
    r"(free|paid|buyer\s+pays(\s+for)?|plus|\+)\s+shipping|delivery\s+available|"
    r"(fedex|ups|usps)|shipped\b)",
    re.I,
)
NO_SHIP_RE = re.compile(
    r"\b(no\s+shipping|(will\s+)?not\s+ship|won'?t\s+ship|don'?t\s+ship|do\s+not\s+ship|can'?t\s+ship|"
    r"cannot\s+ship|no\s+ship|local\s+(pick\s*up\s+)?only|pick\s*up\s+only|in\s+person\s+only|"
    r"cash\s+(only\s+)?in\s+person)\b",
    re.I,
)
SHIP_REJECT = "not local and seller doesn't offer shipping"


def seller_ships(text: str) -> bool | None:
    """True if the post offers shipping, False if it rules it out, None if it doesn't say."""
    if NO_SHIP_RE.search(text):
        return False
    if SHIPS_RE.search(text):
        return True
    return None


# A serial written in the listing: "Serial: C02XG0FDH03Q", "S/N FVFGK0XXQ6L4", "SN#...".
# Must contain a digit, so words like "information" aren't mistaken for one.
SERIAL_RE = re.compile(
    r"(?:serial(?:\s*(?:number|no\.?|#))?|s/n|\bsn)\s*[:#\-]?\s*(?=[A-Z0-9]*\d)([A-Z0-9]{10,12})\b", re.I
)


def find_serial(text: str) -> str | None:
    m = SERIAL_RE.search(text)
    return m.group(1).upper() if m else None


def serial_is_pre_m2(serial: str | None) -> bool:
    """Apple's old 11/12-character serials (factory/year/week/model code) were used on every Intel
    and first-generation M1 Mac. M2 and newer Macs have randomized 10-character serials."""
    return serial is not None and len(serial) in (11, 12)


# Apple model numbers ("A1993" is printed on the case). Every Mac numbered A1xxx predates Apple
# Silicon (the first M1 Mac is A2337). A few A2xxx numbers are Intel or M1 too. NOT included:
# A2338, which Apple used for both the M1 (2020) and M2 (2022) 13" MacBook Pro.
OLD_MODEL_NUMBER_RE = re.compile(r"\bA(1\d{3}|2141|2159|2179|2251|2289|2337|2348|2442|2485|2615)\b", re.I)
# Intel-style clock speed ("3.2GHz", "2.3 GHz"); Apple Silicon listings name the chip instead.
GHZ_RE = re.compile(r"\b\d\.\d{1,2}\s?GHz\b", re.I)
# The only gray Mac mini was the 2018 Intel one; every Apple Silicon mini is silver.
GRAY_RE = re.compile(r"\b(space\s*)?gr[ae]y\b", re.I)


# 15" MacBook Pros are all Intel: Apple Silicon Pros are 13", 14" and 16". (15" Airs are fine.)
_INCH = r"(?:[\"”″]|'{2}|-?\s?inch)"
PRO_15_RE = re.compile(
    r"mac\s?book\s*pro[^0-9]{0,15}\b15(?:\.\d)?\s?" + _INCH + r"|\b15(?:\.\d)?\s?" + _INCH + r"\s*(?:apple\s+)?mac\s?book\s*pro",
    re.I,
)
# The Touch Bar was on 2016-2020 Intel MacBook Pros and, on the 13", on the M1 (2020) and M2 (2022)
# versions - never on an M3/M4 Mac. Intel Macs never came with 24GB (8/16/32/64 only) and the M2 13"
# tops out at 24GB, so a Touch Bar Pro with 24GB is an M2 and one with 32GB is Intel.
TOUCH_BAR_RE = re.compile(r"\btouch\s*-?\s*bar\b", re.I)

# 11" and 12" MacBooks (Air 11", the 12" MacBook) were only ever made with Intel chips.
SMALL_MACBOOK_RE = re.compile(
    r"mac\s?book[^\n]{0,30}?\b1[12]\s?" + _INCH + r"|\b1[12]\s?" + _INCH + r"\s*(?:apple\s+)?mac\s?book", re.I
)
# Apple custom-configuration numbers like Z0V10001W / Z0W200042. Z0xx numbers predate the first M1
# Mac (late 2020). Inferred pattern from observed listings, not an Apple-published rule.
OLD_CTO_RE = re.compile(r"\bZ0[A-Z0-9]{5,8}\b", re.I)


def find_chips(text: str) -> set[str]:
    chips = set()
    text = INTEL_CORE_M_RE.sub(" ", text)
    for m in CHIP_RE.finditer(text):
        if NOT_CHIP_AFTER.match(text[m.end():]):
            continue
        chip = f"M{m.group(1)}"
        if m.group(2):
            chip += " " + m.group(2).capitalize()
        chips.add(chip)
    return chips


def find_ram(text: str) -> set[int]:
    """Return GB values that look like memory sizes (not SSD sizes)."""
    found = set()
    # 128GB RAM exists only on Max/Ultra chips, whose machines never have a 128GB drive.
    maxed = bool(re.search(r"\bm[1-5]\s?(max|ultra)\b", text, re.I))
    for m in GB_RE.finditer(text):
        n = int(m.group(1))
        after = text[m.end(): m.end() + 20]
        before = text[max(0, m.start() - 20): m.start()]
        if n in STORAGE_ONLY or STORAGE_WORDS.match(after):
            continue
        if n not in RAM_SIZES:
            continue
        # "128GB" is usually a drive size unless called RAM (or the chip is a Max/Ultra).
        if n in (128, 192) and not (maxed or RAM_WORDS.match(after) or re.search(r"(ram|memory)\s*:?\s*$", before, re.I)):
            continue
        found.add(n)
    return found


def red_flags(text: str, extra: list[str] | None = None) -> list[str]:
    hits = []
    patterns = RED_FLAG_RE + [re.compile(r"\b" + p + r"\b", re.I) for p in (extra or [])]
    for rx in patterns:
        for m in rx.finditer(text):
            before = text[max(0, m.start() - 40): m.start()]
            window = text[max(0, m.start() - 25): m.end() + 25]
            if SAFE_CONTEXT.search(before):
                continue
            if SAFE_PHRASES.search(window):
                continue
            hits.append(m.group(0).strip().lower())
            break
    hits = set(hits)
    # "icloud locked" also matches "locked" - keep only the most specific phrase.
    return sorted(h for h in hits if not any(h != o and h in o for o in hits))


def evaluate(item: Listing, c: Criteria) -> Listing:
    title = item.title or ""
    body = " ".join([item.condition, item.description])
    text = f"{title} \n {body}"
    reasons: list[str] = []

    def reject(why: str) -> Listing:
        item.verdict = "REJECT"
        item.reasons = [why] + reasons
        item.score = -100
        return item

    if WANTED_RE.search(title):
        return reject("wanted/ISO post, not a sale")
    if not MAC_RE.search(text):
        return reject("not a Mac")
    kinds = {k for k, rx in MODEL_RES.items() if rx.search(title)} or {k for k, rx in MODEL_RES.items() if rx.search(text)}
    if kinds and not kinds & set(c.models):
        return reject(f"{'/'.join(sorted(kinds))} not wanted")
    is_mini = bool(kinds) and kinds <= {"mac mini", "mac studio"}  # desktop
    if m := PART_RE.search(title):
        return reject(f"part, not a whole computer ({m.group(0)})")
    if (m := WEAK_PART_RE.search(title)) and not find_ram(title):
        return reject(f"part, not a whole computer ({m.group(0)}, no RAM size given)")
    if FOR_MAC_RE.search(title) or is_accessory(title):
        return reject("looks like an accessory")

    # --- Intel / M1 giveaways that don't name the chip ---
    if m := OLD_MODEL_NUMBER_RE.search(text):
        return reject(f"model number {m.group(0).upper()} is an Intel/M1-era Mac")

    # --- chip ---
    chips = find_chips(title) or find_chips(body)
    families = {ch.split()[0] for ch in chips}
    wanted = set(c.chips)
    chip_known = False
    if chips:
        good = [ch for ch in chips if ch.split()[0] in wanted]
        if not good:
            return reject(f"chip {', '.join(sorted(chips))}")
        if len(families) > 1 and families - wanted:
            reasons.append(f"mentions several chips ({', '.join(sorted(chips))})")
        item.chip = sorted(good)[-1]
        chip_known = len(families) == 1
    elif INTEL_RE.search(title):
        return reject("Intel Mac")
    elif GHZ_RE.search(title):
        return reject("GHz clock speed and no M-series chip named - looks like an Intel Mac")
    elif kinds == {"mac mini"} and GRAY_RE.search(title):
        return reject("gray Mac mini - only the 2018 Intel model was gray")
    elif OLD_YEAR_RE.search(title):
        return reject("model year means M1 or Intel")
    elif INTEL_WORDS_RE.search(body):
        return reject("description says Intel")
    elif INTEL_CORE_M_RE.search(text):
        return reject("Intel Core m processor (not Apple's M-series)")
    else:
        for rx, chip in YEAR_HINTS:
            if rx.search(title) and chip in wanted:
                item.chip = f"{chip}?"
                reasons.append(f"chip inferred from model year ({chip})")
                break
        else:
            reasons.append("chip not stated")

    # --- older-Mac giveaways (no chip named in them) ---
    spec_conflict = False
    old_hint = None
    if PRO_15_RE.search(text):
        old_hint = "15-inch MacBook Pro - Apple Silicon never made one, so it's Intel"
    elif SMALL_MACBOOK_RE.search(text):
        old_hint = "11/12-inch MacBook - only Intel models were made that small"
    elif chips and (INTEL_RE.search(title) or OLD_YEAR_RE.search(title)):
        old_hint = "title also mentions an Intel-era year or chip"
    elif m := OLD_CTO_RE.search(text):
        old_hint = f"custom-config number {m.group(0).upper()} is from before the M1 era (Intel)"
    if old_hint:
        if not chips:
            return reject(old_hint)
        spec_conflict = True
        reasons.insert(0, f"!! {old_hint}, but the listing names {item.chip} - likely mislabeled, verify")

    # --- Touch Bar: mostly Intel, but also the 2022 M2 13" Pro ---
    if TOUCH_BAR_RE.search(text):
        ram_now = find_ram(title) or find_ram(body)
        if not chips:
            if 24 in ram_now:
                reasons.append("Touch Bar + 24GB: only the 2022 M2 13-inch Pro fits (Intel never had 24GB) - confirm the chip")
            else:
                return reject("Touch Bar MacBook Pro with no M2 named - Intel (2016-2020) unless it's the 2022 M2 13-inch")
        elif any(ch.split()[0] in ("M3", "M4") for ch in chips) and not any(ch.split()[0] == "M2" for ch in chips):
            spec_conflict = True
            reasons.insert(0, f"!! Touch Bar, but no {item.chip} MacBook Pro has one - likely mislabeled, verify")

    # --- serial number (when the seller wrote one) ---
    if serial_is_pre_m2(find_serial(text)):
        if not chip_known:
            return reject("serial number format means a pre-2021 Mac (Intel or M1)")
        spec_conflict = True
        reasons.insert(0, "!! serial number looks like an old Intel/M1 Mac but the listing says "
                          f"{item.chip} - likely mislabeled, verify before buying")

    # --- RAM ---
    ram = find_ram(title) or find_ram(body)
    ram_ok = [r for r in ram if r in c.ram_options]
    ram_known = False
    if ram_ok:
        item.ram_gb = max(ram_ok)
        other = ram - set(c.ram_options)
        if other:
            reasons.append(f"also mentions {', '.join(str(r) + 'GB' for r in sorted(other))} - verify config")
        else:
            ram_known = True
    elif ram:
        return reject(f"RAM {', '.join(str(r) + 'GB' for r in sorted(ram))}")
    else:
        reasons.append("RAM not stated")

    if not item.chip and not ram_ok:
        if not c.loose:
            return reject("can't tell chip or RAM")
        reasons.append("ask the seller for the chip and RAM (About This Mac)")

    # --- condition / red flags ---
    # In the title or marketplace condition field a red flag is disqualifying. In a long
    # description it may be seller boilerplate ("we never sell iCloud locked units"),
    # so there it's a loud warning instead.
    flags = red_flags(f"{title} \n {item.condition}", c.extra_red_flags)
    if flags:
        return reject("red flags: " + ", ".join(flags))
    desc_flags = red_flags(item.description, c.extra_red_flags)
    if desc_flags:
        reasons.insert(0, "!! description mentions: " + ", ".join(desc_flags) + " - read it")
    if re.search(r"parts|not\s+working", item.condition, re.I):
        return reject(f"condition: {item.condition}")

    # --- already sold? ---
    if item.sold:
        return reject("already sold: " + (item.sold_note or "marked sold"))
    if item.sold_note:
        reasons.insert(0, "!! " + item.sold_note)
    stale = item.age_days is not None and item.age_days > c.stale_days
    if stale:
        reasons.append(f"posted {item.age_days:.0f} days ago - may already be gone, check the comments")

    # --- out-of-town Craigslist: must ship ---
    if item.needs_shipping:
        ships = seller_ships(text)
        if ships is False:
            return reject(SHIP_REJECT + " (says local/pickup only)")
        if ships is None:
            return reject(SHIP_REJECT)
        reasons.append("out-of-town seller who ships - confirm cost, pay with PayPal Goods & Services")

    # --- price ---
    if item.price is None:
        reasons.append("price not found")
        price_known = False
    else:
        price_known = True
        ship = item.shipping if item.shipping is not None else c.assumed_shipping
        total = item.price + ship
        if item.price < c.min_price and not item.is_auction:
            return reject(f"${item.price:.0f} is suspiciously cheap (part/accessory/scam?)")
        if " " in item.chip.rstrip("?") and item.price < c.min_price_pro and not item.is_auction:
            return reject(f"${item.price:.0f} is far too cheap for a {item.chip} (part/scam/mislabeled?)")
        if total > c.max_total:
            over = total - c.max_total
            if not (item.negotiable and over <= c.offer_stretch):
                return reject(f"${total:.0f} over budget")
            reasons.append(f"${over:.0f} over budget - make an offer")
            price_known = False  # never a clean MATCH
        if item.shipping is None:
            reasons.append("shipping unknown")
        if item.price_is_range:
            reasons.append("listing has several configs/prices - lowest price may not be the 24/32GB one")
    if item.is_auction:
        if not c.allow_auctions:
            return reject("auction")
        reasons.append("auction - price will rise")

    confirmed = (
        chip_known and ram_known and price_known and item.shipping is not None
        and not item.is_auction and not item.price_is_range and not desc_flags
        and not item.sold_note and not stale and not spec_conflict
    )
    item.verdict = "MATCH" if confirmed else "POSSIBLE"

    # Score: cheaper and newer/bigger is better; unknowns cost points.
    score = 50
    if item.total is not None:
        score += int((c.max_total - item.total) / 10)
    score += {"M4": 15, "M3": 8, "M2": 0}.get(item.chip[:2], 0)
    score += 10 if " " in item.chip.rstrip("?") else 0  # Pro/Max
    score += 8 if (item.ram_gb or 0) >= 32 else 0
    score -= 0 if chip_known else 15
    score -= 0 if ram_known else 20
    score -= 10 if item.is_auction else 0
    score -= 25 if desc_flags else 0
    score -= 30 if spec_conflict else 0
    score -= 20 if item.sold_note else 0
    score -= 10 if stale else 0
    score -= c.mini_penalty if is_mini else 0
    item.score = score
    item.reasons = reasons
    return item
