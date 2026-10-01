"""Listings you rejected by hand, remembered between runs (results/rejected.json) so the same
listing doesn't keep coming back. Keyed by the listing's URL without its query string."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def key_of(url: str) -> str:
    return url.split("?")[0]


def load(path: Path | None) -> dict[str, dict]:
    if not path:
        return {}
    try:
        data = json.loads(Path(path).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(path: Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1))


def add(path: Path | None, item, was: str, reason: str = "") -> None:
    """Remember that you rejected `item` (a Listing); `was` is the verdict the detector had given it."""
    if not path:
        return
    data = load(path)
    data[item.key] = {
        "title": item.title, "url": item.url, "source": item.source, "price": item.price, "chip": item.chip,
        "was": was, "reason": reason, "when": datetime.now().isoformat(timespec="seconds"),
    }
    _save(path, data)


def add_url(path: Path, url: str, reason: str = "") -> None:
    data = load(path)
    data[key_of(url)] = {"title": "", "url": url, "was": "", "reason": reason, "when": datetime.now().isoformat(timespec="seconds")}
    _save(path, data)


def remove(path: Path | None, key: str) -> bool:
    if not path:
        return False
    data = load(path)
    if key_of(key) not in data:
        return False
    del data[key_of(key)]
    _save(path, data)
    return True
