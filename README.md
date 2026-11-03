# Small-Cap Momentum Stock Screener

This project screens candidates for manual research. Defaults are price $2–$10, volume at least 500,000, public float at most 10 million, market cap at most $100 million, and gain/gap at least 5%. Midday defaults are +10% and 5x daily RVOL. These filters are not validated trading signals.

## Install and run

```bash
python -m pip install -r requirements.txt
python screener.py
python midday_screener.py --source yfinance
python midday_screener.py --source yfinance --float-mode discovery --sort-by rvol
```

Yahoo is free and needs no key. Its screener returns a provider-selected, limited result set, not comprehensive US market coverage. Yahoo does not provide a dependable extended-hours tape through this implementation, so it uses regular-market fields and does not claim premarket price, volume, or gap. Timestamped stale Yahoo quotes are skipped. Quote delay can be unknown.

Optional Massive/Polygon implementations:

```bash
python momentum_screener.py --api-key "$MASSIVE_API_KEY"
python momentum_screener.py --demo
python massive_screener.py
python midday_screener.py --source polygon
```

Configure `MASSIVE_API_KEY` or `POLYGON_API_KEY` in the environment or `.env`. Market snapshots and fundamentals may be plan-limited. Providers do not consistently expose public float or a separate extended-hours tape. Unknown values remain unknown; float is never derived from shares outstanding or market cap. Use `--float-mode strict|discovery`: strict excludes unknown float; discovery retains unknown float flagged `unverified`. Public float means shares available for public trading. Shares outstanding includes restricted and insider holdings. Market capitalization is equity value. These fields are distinct.

## Sessions and relative volume

Premarket gap is the latest valid premarket trade versus the prior regular close. Regular-session gain is current regular-session price versus prior regular close. They are different measures. Current Yahoo paths report regular-session gain only. Aggregate daily snapshot volume must not be presented as premarket volume without extended-hours trade data. `market_data.py` labels ET session intervals; `exchange-calendars` supports holiday checks.

Midday RVOL is labelled **daily**: current cumulative session volume divided by the mean of available historical full-day volumes. It is not time-of-day-adjusted RVOL. Missing or invalid history excludes a candidate. No fixed baseline is substituted. Intraday historical baselines are not currently implemented.

Missing market cap excludes a candidate. Missing, zero, negative, non-finite, or unavailable float is unknown. Float source and timestamp are retained if supplied. `N/A` and `unverified` indicate incomplete fundamentals. Free Yahoo may rate-limit, delay, omit fundamentals, and change result coverage. An empty scan and a provider failure are different states; check terminal error/status messages.

## Configurable thresholds

```bash
python screener.py --min-price 3 --max-price 8 --min-volume 500000 --max-float 10000000 --max-market-cap 100000000 --min-gap 10
python midday_screener.py --demo --min-rvol 5 --sort-by volume
```

Results sort by volume by default. DataFrames retain numeric values; terminal output formats values for readability. Output labels public float as `Float`, never estimated float.

## Tests

```bash
python -m pytest -v
```
