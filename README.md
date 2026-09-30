# macscraper

Searches eBay, Craigslist and r/appleswap for an **Apple Silicon MacBook or Mac mini (M2/M3/M4, any variant) with 24 or 32 GB RAM,
fully working, ≤ $700 delivered**. It sorts every listing into:

| Verdict | Meaning |
|---|---|
| **MATCH** | Chip, RAM and price all confirmed from the listing, no red flags |
| **POSSIBLE** | Nothing disqualifying, but something needs checking (RAM not stated, auction, Best Offer slightly over budget, a warning word in the description) |
| **REJECT** | iMac/Mac Studio, wrong chip/RAM, over budget, accessory, Intel/M1 model year, or a red flag: locked / iCloud / MDM / parts / as-is / cracked / water / won't boot, etc. Phrases like "not locked" or "no damage" are recognized as fine. |

## Run it (on your Mac)

```sh
brew install uv            # if you don't have it
git clone <this repo> && cd macscraper
cp config.example.toml config.toml   # set your local Craigslist city (and ZIP) here
uv run macscraper                     # one pass, opens nothing, prints a table
open results/report.html              # clickable report, also results.csv / results.json
```

Useful flags:

```sh
uv run macscraper --deep                     # open each candidate page to read specs + seller description (slower, better)
uv run macscraper --watch 20 --ntfy my-topic # re-check every 20 min, push NEW matches to your phone (ntfy app)
uv run macscraper --cl-sites sfbay,sacramento
uv run macscraper --stretch 0 --no-auctions  # strictly ≤ $700, fixed price only
uv run macscraper --loose                    # also keep listings that state neither chip nor RAM
```

`results/seen.json` remembers what you've already seen, so the report and alerts mark only new listings as **NEW**.

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
