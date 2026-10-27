from typing import Literal
from pydantic import BaseModel, Field


class Flex(BaseModel):
    allow_auctions: bool = False
    price_stretch: float = 0          # dollars over budget the user would negotiate
    ok_with_minor_issues: bool = False  # cosmetic wear etc.
    ok_with_unknown_specs: bool = True  # listing doesn't say; user can ask the seller
    notes: str = ""


class SearchSpec(BaseModel):
    product: str = Field(max_length=200)
    search_queries: list[str] = Field(min_length=1, max_length=6)
    max_total: float = Field(gt=0)
    min_price: float = 0              # below this is probably broken/scam
    must_have: list[str] = []
    deal_breakers: list[str] = []
    flex: Flex = Flex()


class Listing(BaseModel):
    id: str
    source: str
    title: str
    url: str
    price: float
    shipping: float = 0
    condition: str = ""
    description: str = ""
    is_auction: bool = False
    image: str = ""

    @property
    def total(self) -> float:
        return self.price + self.shipping


Verdict = Literal["MATCH", "POSSIBLE", "REJECT"]


class Judged(BaseModel):
    listing: Listing
    verdict: Verdict
    reasons: list[str] = []
    ask_seller: list[str] = []
