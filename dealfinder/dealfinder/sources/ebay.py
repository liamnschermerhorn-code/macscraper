"""eBay Browse API (official). Needs EBAY_CLIENT_ID / EBAY_CLIENT_SECRET."""
import base64
import httpx
from ..models import Listing

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"


def _num(d, *path) -> float:
    for p in path:
        d = (d or {}).get(p) if isinstance(d, dict) else None
    try:
        return float(d)
    except (TypeError, ValueError):
        return 0.0


def parse(item: dict) -> Listing:
    opts = item.get("shippingOptions") or [{}]
    return Listing(
        id="ebay:" + str(item.get("itemId", "")),
        source="ebay",
        title=item.get("title", ""),
        url=item.get("itemWebUrl", ""),
        price=_num(item, "price", "value"),
        shipping=_num(opts[0], "shippingCost", "value"),
        condition=item.get("condition", ""),
        description=item.get("shortDescription", ""),
        is_auction="AUCTION" in (item.get("buyingOptions") or []) and "FIXED_PRICE" not in (item.get("buyingOptions") or []),
        image=(item.get("image") or {}).get("imageUrl", ""),
    )


async def search(client: httpx.AsyncClient, cid: str, secret: str, query: str, limit: int = 30) -> list[Listing]:
    basic = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    t = await client.post(TOKEN_URL, headers={"Authorization": f"Basic {basic}"},
                          data={"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"})
    t.raise_for_status()
    r = await client.get(SEARCH_URL, params={"q": query, "limit": limit},
                         headers={"Authorization": f"Bearer {t.json()['access_token']}"})
    r.raise_for_status()
    return [parse(i) for i in r.json().get("itemSummaries", [])]
