# Small-Cap Momentum Stock Screener

This project screens candidates for manual research. Defaults are price $2–$10, volume at least 500,000, public float at most 10 million, market cap at most $100 million, and gain/gap at least 5%. Midday defaults are +10% and 5x daily RVOL. These filters are not validated trading signals.

## Install and run

```bash
python -m pip install -r requirements.txt
python screener.py
python midday_screener.py --source yfinance
python midday_screener.py --source yfinance --float-mode discovery --sort-by rvol
python midday_screener.py --source finnhub --float-mode discovery
```

For API-backed sources, create `.env` from the template if you do not already have one, then add the key for the provider you plan to use:

```bash
cp -n .env.example .env
```

`.env` is ignored by Git. Keep real credentials there or in environment variables; do not commit them. `python-dotenv` loads `.env` for the scripts. VS Code users can enable terminal injection with `python.terminal.useEnvFile` and point `python.envFile` at `${workspaceFolder}/.env`.

Yahoo is free and needs no key. Its screener returns a provider-selected, limited result set, not comprehensive US market coverage. Yahoo does not provide a dependable extended-hours tape through this implementation, so it uses regular-market fields and does not claim premarket price, volume, or gap. Timestamped stale Yahoo quotes are skipped. Quote delay can be unknown.

Optional Massive/Polygon implementations:

```bash
python momentum_screener.py --api-key "$MASSIVE_API_KEY"
python momentum_screener.py --demo
python massive_screener.py
python midday_screener.py --source polygon
```

Configure `MASSIVE_API_KEY` or `POLYGON_API_KEY` in the environment or `.env`. Market snapshots and fundamentals may be plan-limited. Providers do not consistently expose public float or a separate extended-hours tape. Unknown values remain unknown; float is never derived from shares outstanding or market cap. Use `--float-mode strict|discovery`: strict excludes unknown float; discovery retains unknown float flagged `unverified`. Public float means shares available for public trading. Shares outstanding includes restricted and insider holdings. Market capitalization is equity value. These fields are distinct.

The optional Finnhub midday source reads `FINNHUB_API_KEY` from `.env`. It uses Yahoo Finance's dynamically discovered results as a capped candidate list (up to 20 symbols), then requests Finnhub quote and company-profile data. This is not a full-market Finnhub scan. Finnhub profile data includes market capitalization and shares outstanding; public float is only populated if Yahoo provides its explicit `floatShares` field, otherwise strict mode excludes it or discovery mode flags it unknown. Quote and volume sources are shown separately because Finnhub's quote endpoint does not supply session volume in the quote response. Delayed status can be unknown. Finnhub calls are paced and transient failures are bounded; API access still depends on your account entitlement.

## Sessions and relative volume

Premarket gap is the latest valid premarket trade versus the prior regular close. Regular-session gain is current regular-session price versus prior regular close. They are different measures. Current Yahoo paths report regular-session gain only. Aggregate daily snapshot volume must not be presented as premarket volume without extended-hours trade data. `market_data.py` provides ET clock labels and an NYSE calendar helper; this does not create premarket prices or volume, and a session label does not verify market-wide holiday coverage.

Midday RVOL is labelled **daily**: current cumulative session volume divided by the mean of available historical full-day volumes. It is not time-of-day-adjusted RVOL. Missing or invalid history excludes a candidate. No fixed baseline is substituted. Intraday historical baselines are not currently implemented.

Missing market cap excludes a candidate. Missing, zero, negative, non-finite, or unavailable float is unknown. Float source and timestamp are retained if supplied. `N/A` and `unverified` indicate incomplete fundamentals. Free Yahoo may rate-limit, delay, omit fundamentals, and change result coverage. An empty scan and a provider failure are different states; check terminal error/status messages.

## Configurable thresholds

```bash
python screener.py --min-price 3 --max-price 8 --min-volume 500000 --max-float 10000000 --max-market-cap 100000000 --min-gap 10
python midday_screener.py --demo --min-rvol 5 --sort-by volume
```

### Finnhub Engine (Live Quotes & Fundamentals)
If you have `FINNHUB_API_KEY` set in `.env`:
```bash
python midday_screener.py --source finnhub
# Or run the standalone Finnhub screener:
python finnhub_screener.py
```

Results sort by volume by default. DataFrames retain numeric values; terminal output formats values for readability. Output labels public float as `Float`, never estimated float.

## Tests

```bash
python -m pytest -v
```
