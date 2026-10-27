"""Fake listings so the whole pipeline can be tried without any marketplace keys."""
from ..models import Listing


def search(query: str) -> list[Listing]:
    rows = [
        ("Sony WH-1000XM5 headphones black, great shape", 210, 0, "Used", "Works perfectly, original box, no scratches."),
        ("Sony WH-1000XM5 FOR PARTS left cup dead", 60, 8, "For parts", "Left side no sound. Selling as is."),
        ("Sony WH-1000XM5 new sealed", 330, 0, "New", "Brand new in sealed box."),
        ("Sony WH-1000XM5 headphones", 190, 6, "Used", ""),
        ("Sony headphone replacement ear pads XM5", 15, 0, "New", "Ear pads only."),
    ]
    return [Listing(id=f"demo:{i}", source="demo", title=t, url=f"https://example.com/demo/{i}",
                    price=p, shipping=s, condition=c, description=d) for i, (t, p, s, c, d) in enumerate(rows)]
