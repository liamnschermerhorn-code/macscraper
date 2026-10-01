# macscraper

Searches eBay, Craigslist and r/appleswap for an **Apple Silicon MacBook (M2/M3/M4, any variant; `models` in `settings.toml` can add Mac mini / Mac Studio) with 24, 32, 64 or 128 GB RAM (`ram_options`),
fully working, ≤ $700 delivered** (change `max_total` in `settings.toml`). It sorts every listing into:

| Verdict | Meaning |
|---|---|
| **MATCH** | Chip, RAM and price all confirmed from the listing, no red flags |
| **POSSIBLE** | Nothing disqualifying, but something needs checking (chip and/or RAM not stated - just ask the seller, auction, Best Offer slightly over budget, a warning word in the description) |
| **REJECT** | iMac, wrong chip/RAM, over budget, accessory, Intel/M1 model year, or a red flag: locked / iCloud / MDM / parts / as-is / cracked / water / won't boot, etc. Phrases like "not locked" or "no damage" are recognized as fine. |

## Run it (on your Mac)

```sh
brew install uv            # if you don't have it
git clone <this repo> && cd macscraper
uv run macscraper                     # settings come from settings.toml (updated by git pull)
                                      # your own overrides go in config.local.toml
# one pass, opens nothing, prints a table
open results/report.html              # clickable report, also results.csv / results.json
```

Each run starts by asking two questions (press Enter to keep the default from `settings.toml`):

```
Include auctions? (current bid, final price will be higher) [Y/n]
Include flexible prices? (Best Offer / local listings a bit over $700 you could negotiate down) [Y/n]
  How far over $700 is OK? [$75]
```

Useful flags:

```sh
uv run macscraper --deep                     # open each candidate page to read specs + seller description (slower, better)
uv run macscraper --watch 20 --ntfy my-topic # re-check every 20 min, push NEW matches to your phone (ntfy app)
uv run macscraper --cl-sites sfbay,sacramento
uv run macscraper --stretch 0 --no-auctions  # strictly ≤ budget, fixed price only (no questions)
uv run macscraper --no-ask                   # skip the questions, use the settings files
uv run macscraper --strict                   # drop listings that state neither chip nor RAM (normally kept as POSSIBLE)
```

When the run finishes you get a live results screen that reflows as you resize the window (wide: list plus a
detail pane; narrow: the detail pane drops underneath). Keys: **↑/↓** move, **Enter** or **o** open the link,
**c** copy it, **m** matches only, **x** reject the highlighted listing (see below), **u** undo, **r** show rejected
listings (with the reason), **q** quit. `--no-tui` (or
`--watch`, or piping the output) prints a plain table instead; `results/report.html` is written either way.

**Rejecting by hand.** When the detector lets through something that isn't right, press **x** on it. It disappears,
and it stays gone on later runs (saved in `results/rejected.json`, keyed by the listing's link). **u** undoes the
last rejection; press **r** to see everything rejected, and **x** on one you rejected earlier brings it back. When you
quit, it prints what you rejected: paste those lines to Claude and each one becomes a new rule, so the detector
catches that kind of listing itself next time. Without the screen: `--reject URL [--why "..."]` / `--unreject URL`.

`results/seen.json` remembers what you've already seen, so the report and alerts mark only new listings as **NEW**.

### Settings

`settings.toml` is part of the repo, so `git pull` brings in the latest settings (budget, cities, models...).
To change something only on your machine, create `config.local.toml` with just those lines, e.g.
`max_total = 600` or `ntfy_topic = "my-private-topic"`. It overrides `settings.toml` and git never touches it.
An old `config.toml` is no longer read.

### Reading the text in photos (`--ocr`)

Titles often don't say what a listing is, but the photos do: an **About This Mac** screenshot shows the chip,
memory and serial, and a photo of the underside shows the model number. With `--ocr` (or `ocr = true` in
`settings.toml`) the scraper downloads the photos of every POSSIBLE listing, reads the text in them, and judges the
listing again, so "Chip Apple M2 / Memory 24 GB" turns a POSSIBLE into a MATCH, and "Intel Core i7" rejects one.

On a Mac it uses Apple's Vision text recognition (the engine behind Live Text): free, runs on your machine, nothing
is uploaded. One-time setup: `uv sync --extra ocr`. Then `uv run macscraper --ocr`. (Elsewhere:
`brew install tesseract` and `uv add pytesseract pillow`.) It only helps when the seller posted a screenshot or a
readable label, and it makes the run slower (a page and several photos per possible listing); `--ocr-max-images`
sets how many photos per listing (default 6).

### Craigslist: local or ships

- **Local** (`craigslist_sites`, optionally within `max_distance_miles` of `home_zip`): every listing counts, as pickup.
- **Other cities** (`craigslist_ship_sites`): a listing is kept only if the seller's post says they'll ship
  ("will ship", "shipping available", "+ shipping", "shipped"...). "Local pickup only" or silent posts are dropped.
  These are always POSSIBLE, since shipping cost isn't known - pay with PayPal Goods & Services, never Zelle/cash app.

### eBay API (optional, recommended)

eBay's HTML sometimes throws a bot check. For reliable results, create a free key at
[developer.ebay.com](https://developer.ebay.com) (Production keyset) and:

```sh
export EBAY_CLIENT_ID=... EBAY_CLIENT_SECRET=...
```

The scraper then uses the official Browse API automatically.

### Not scraped

Facebook Marketplace, OfferUp, Mercari, Swappa, Back Market and Apple Refurbished need a login or JavaScript.
The report has a "Check by hand" section with pre-filled search links for them.

## Before you pay

Ask the seller for photos of **About This Mac** (chip + memory) and **System Settings → General → Device Management**
(should be empty), and confirm **Find My is off**. In person: boot it, check the serial on checkcoverage.apple.com,
and watch them sign out of iCloud. Use eBay/PayPal Goods & Services, never Zelle/wire to a stranger.

## Tests

```sh
uv run pytest
```
