from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Listing:
    source: str
    title: str
    url: str
    price: float | None = None  # item price in USD
    shipping: float | None = None  # None = unknown, 0 = free / local pickup
    location: str = ""
    condition: str = ""  # marketplace-provided condition text, if any
    description: str = ""  # body text / item specifics, when available
    is_auction: bool = False
    negotiable: bool = False  # eBay Best Offer, or a local/private sale
    price_is_range: bool = False  # eBay "$450 to $900" listings with several configurations
    posted: str = ""
    # Craigslist listing from a city that isn't yours: only useful if the seller ships.
    needs_shipping: bool = False

    # Filled in by filters.evaluate()
    verdict: str = ""  # MATCH / POSSIBLE / REJECT
    chip: str = ""
    ram_gb: int | None = None
    score: int = 0
    reasons: list[str] = field(default_factory=list)

    @property
    def total(self) -> float | None:
        if self.price is None:
            return None
        return self.price + (self.shipping or 0)

    @property
    def key(self) -> str:
        return self.url.split("?")[0]
