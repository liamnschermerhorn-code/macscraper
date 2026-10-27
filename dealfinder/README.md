# dealfinder

A website where you say what you want to buy. Claude interviews you (specs, budget, how flexible you are),
turns the answers into a search, pulls listings, then judges each one MATCH / POSSIBLE / REJECT with reasons and
questions to ask the seller. Same idea as the `macscraper` tool in the parent folder, for any product.

## Run locally

```sh
cd dealfinder
export ANTHROPIC_API_KEY=sk-ant-...      # never commit this
export DEALFINDER_DEMO=1                 # fake listings; or set EBAY_CLIENT_ID / EBAY_CLIENT_SECRET for real eBay
uv run uvicorn dealfinder.app:app --reload
```

## Settings (environment variables)

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | required; stays on the server |
| `ACCESS_CODE` | if set, the site asks for it; set this on any public deploy |
| `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET` | eBay Browse API (official). Without them, no real listings |
| `DEALFINDER_MODEL`, `DEALFINDER_JUDGE_MODEL` | default `claude-sonnet-5-5` |
| `PER_IP_PER_HOUR`, `DAILY_LLM_CALLS` | rate limits that cap your API bill |
| `DEALFINDER_DEMO=1` | fake listings |

## Notes

- Only official APIs are used (eBay). Craigslist, Facebook and OfferUp have no public search API, so they aren't included.
- Listing text is untrusted: it's fenced as data in the judge prompt, results default to POSSIBLE (never MATCH) when
  Claude gives no verdict, and the frontend only uses `textContent`.
- Tests use a fake Claude client; real Claude and eBay calls are not covered by them. `uv run pytest`.
