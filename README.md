# macscraper

Searches eBay, Craigslist and r/appleswap (plus any Facebook Marketplace pages you saved) for an **Apple Silicon MacBook (M2/M3/M4, any variant; `models` in `settings.toml` can add Mac mini / Mac Studio) with 24, 32, 64 or 128 GB RAM (`ram_options`),
fully working, ≤ $700 delivered** (change `max_total` in `settings.toml`). It sorts every listing into:

| Verdict | Meaning |
|---|---|
| **MATCH** | Chip, RAM and price all confirmed, the **description read** and clean, no red flags. A negotiable listing (Best Offer / local) a little over budget counts too, with a "make an offer" note |
| **POSSIBLE** | Nothing disqualifying, but something needs checking (chip and/or RAM not stated - just ask the seller, auction, shipping unknown, a warning word in the description) |
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
uv run macscraper --no-deep                  # titles only: faster, but descriptions aren't read (the default is to read them)
uv run macscraper --watch 20 --ntfy my-topic # re-check every 20 min, push NEW matches to your phone (ntfy app)
uv run macscraper --cl-sites sfbay,sacramento
uv run macscraper --stretch 0 --no-auctions  # strictly ≤ budget, fixed price only (no questions)
uv run macscraper --no-ask                   # skip the questions, use the settings files
uv run macscraper --strict                   # drop listings that state neither chip nor RAM (normally kept as POSSIBLE)
```

When the run finishes you get a live results screen that reflows as you resize the window (wide: list plus a
detail pane; narrow: the detail pane drops underneath). Keys: **↑/↓** move, **Enter** or **o** open the link,
**c** copy it, **click a column heading** (or press **1**-**6**) to sort by it, and click it again to flip the order,
**m** matches only, **x** reject the highlighted listing (see below), **u** undo, **r** show rejected
listings (with the reason), **q** quit. `--no-tui` (or
`--watch`, or piping the output) prints a plain table instead; `results/report.html` is written either way.

**Rejecting by hand.** When the detector lets through something that isn't right, press **x** on it. It disappears,
and it stays gone on later runs (saved in `results/rejected.json`, keyed by the listing's link). **u** undoes the
last rejection; press **r** to see everything rejected, and **x** on one you rejected earlier brings it back. When you
quit, it prints what you rejected: paste those lines to Claude and each one becomes a new rule, so the detector
catches that kind of listing itself next time. Without the screen: `--reject URL [--why "..."]` / `--unreject URL`.

`results/seen.json` remembers what you've already seen, so the report and alerts mark only new listings as **NEW**.

### Descriptions

By default the scraper opens every candidate listing and reads the seller's description (and eBay's item specifics, like
"Processor" and "RAM Size"), not just the title. A description that says the Mac is broken or locked ("for parts",
"iCloud locked", "won't turn on", "cracked screen", "water damage", "bad logic board"...) rejects the listing, unless the
same sentence says the opposite ("we never sell iCloud locked items", "Activation Lock is off"). A description that
disagrees with the title (24GB in the title, 16GB in the text) is flagged for you to read. A **MATCH needs its description
read**: if a page couldn't be fetched (eBay refuses some), the listing stays POSSIBLE with "description not read yet".
The results screen shows what the seller wrote. `--no-deep` skips all of this for speed; `require_description = false`
in `settings.toml` lets unread listings be MATCH.

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

### Facebook Marketplace (pages you save)

The scraper never contacts Facebook, but it can read Marketplace pages **you** saved. In your browser, search
Marketplace (set your city and radius), **scroll down** to load more listings, then save the page: Chrome / Edge /
Firefox: **Cmd+S → Format: "Webpage, Complete"**; Safari: **File → Save As → Format: "Web Archive"** (not "Page Source" / "HTML only",
which save the page before its listings load). You don't have to remember any of this: **at startup the scraper offers to do it with you**. It opens the Marketplace
searches in your browser, waits while you scroll and save each page, and reads every file you **drag into the terminal**
(telling you at once how many listings it found). `--no-facebook` skips the question. You can also just keep files in
the `marketplace/` folder (read on every run) or pass them: `uv run macscraper --import saved.html`.
Every run reads them as one more source, with the same checks.
Saved pages are a snapshot, so listings are marked "saved N days ago - may be sold" once they're a day old; replace
the files with fresh ones to refresh. The folder is git-ignored, so nothing you save is ever uploaded.

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
