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
    min_price: float = 150.0  # anything cheaper is almost always an accessory, a scam or a box
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
    # Posts older than this many days are kept, but only as POSSIBLE.
    stale_days: float = 10
    # Keep listings that state neither chip nor RAM (lots of noise, occasionally a steal).
    loose: bool = False


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

INTEL_RE = re.compile(r"\b(intel|core\s?i[3579]|i[3579][-\s]\d{4}|i[3579]\b|xeon|2012|2013|2014|2015|2016|2017|2018|2019)\b", re.I)

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
    r"heat\s*sink|trackpad|hinge|donor|a\d{4}\s+board|parts?\s+(lot|unit|machine))\b",
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


def find_chips(text: str) -> set[str]:
    chips = set()
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
    for m in GB_RE.finditer(text):
        n = int(m.group(1))
        after = text[m.end(): m.end() + 20]
        before = text[max(0, m.start() - 20): m.start()]
        if n in STORAGE_ONLY or STORAGE_WORDS.match(after):
            continue
        if n not in RAM_SIZES:
            continue
        # "128GB" is almost always storage on these machines unless called RAM.
        if n in (128, 192) and not (RAM_WORDS.match(after) or re.search(r"(ram|memory)\s*:?\s*$", before, re.I)):
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
    if FOR_MAC_RE.search(title) or is_accessory(title):
        return reject("looks like an accessory")

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
    elif OLD_YEAR_RE.search(title):
        return reject("model year means M1 or Intel")
    else:
        for rx, chip in YEAR_HINTS:
            if rx.search(title) and chip in wanted:
                item.chip = f"{chip}?"
                reasons.append(f"chip inferred from model year ({chip})")
                break
        else:
            reasons.append("chip not stated")

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

    if not item.chip and not ram_ok and not c.loose:
        return reject("can't tell chip or RAM")

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
            return reject(f"${item.price:.0f} is suspiciously cheap (accessory/scam?)")
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
        and not item.sold_note and not stale
    )
    item.verdict = "MATCH" if confirmed else "POSSIBLE"

    # Score: cheaper and newer/bigger is better; unknowns cost points.
    score = 50
    if item.total is not None:
        score += int((c.max_total - item.total) / 10)
    score += {"M4": 15, "M3": 8, "M2": 0}.get(item.chip[:2], 0)
    score += 10 if " " in item.chip.rstrip("?") else 0  # Pro/Max
    score += 8 if item.ram_gb == 32 else 0
    score -= 0 if chip_known else 15
    score -= 0 if ram_known else 20
    score -= 10 if item.is_auction else 0
    score -= 25 if desc_flags else 0
    score -= 20 if item.sold_note else 0
    score -= 10 if stale else 0
    score -= c.mini_penalty if is_mini else 0
    item.score = score
    item.reasons = reasons
    return item
