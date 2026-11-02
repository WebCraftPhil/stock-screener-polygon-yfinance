# Small-Cap Momentum Stock Screener

A Python stock screener for small-cap momentum stocks, supporting three scripts:
1. **Yahoo Finance ([`yfinance_screener.py`](yfinance_screener.py))**: **100% Free** — requires NO API key or paid subscription.
2. **Massive Official SDK ([`massive_screener.py`](massive_screener.py))**: Uses [`massive`](https://github.com/massive-com/client-python) (`RESTClient`).
3. **Polygon.io / Massive REST ([`momentum_screener.py`](momentum_screener.py))**: Direct REST implementation with built-in `--demo` simulation mode.

---

## Screening Criteria

Both screeners enforce these exact momentum rules:
- **Price**: Between `$2.00` and `$10.00`
- **Volume**: Greater than or equal to `500,000` shares
- **Float**: Less than or equal to `10,000,000` shares (10M)
- **Market Cap**: Less than or equal to `$100M` ($100,000,000)
- **Gap / Change**: Greater than or equal to `+5.0%`

Results are sorted by **Volume in descending order** and outputted as a formatted Pandas DataFrame.

---

## Output Columns

| Column | Description | Format |
| :--- | :--- | :--- |
| **Ticker** | Stock symbol | `ABCD` |
| **Price** | Current / session trade price | `$4.50` |
| **Gap %** | Percentage change from previous close | `+14.62%` |
| **Volume** | Current session cumulative volume | `1,850,000` |
| **Market Cap ($M)** | Market capitalization in millions | `$25.00` |
| **Est. Float (M)** | Public float in millions | `7.20` |

---

## Quick Start (Free Yahoo Finance Screener)

No API key or account needed. Run directly:

```bash
python yfinance_screener.py
```

### Sample Live Output:
```
================================================================================
                SMALL-CAP MOMENTUM SCREENER (YAHOO FINANCE)
================================================================================
Rules: Price: $2-$10 | Vol: >=500K | Float: <=10M | MktCap: <=$100M | Gap: >=+5%
--------------------------------------------------------------------------------
Ticker Price   Gap %     Volume Market Cap ($M) Est. Float (M)
  CLRO $6.04 +77.38% 32,619,501          $16.17           0.89
  FTFT $3.57 +22.11%    905,515          $28.84           5.39
--------------------------------------------------------------------------------
Total matching stocks: 2
================================================================================
```

---

## Polygon.io / Massive Screener

### Why did you see "HTTP 403 Forbidden: Access to US stock snapshots is not allowed on your Polygon.io plan"?
Polygon.io (Massive) offers a free "Basic" plan, but **restricts the market-wide US snapshot endpoint (`/v2/snapshot/locale/us/markets/stocks/tickers`) to paid plans** (Starter at $29/mo or Developer at $79/mo).

If you have a paid plan, configure your key in `.env`:
```env
MASSIVE_API_KEY=your_key_here
```
*(or `POLYGON_API_KEY=your_key_here`)*

And run:
```bash
python momentum_screener.py
```

Or run the built-in simulated test:
```bash
python momentum_screener.py --demo
```

---

## Running Automated Tests

```bash
python -m pytest tests/test_screener.py -v
```
