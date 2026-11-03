# Small-Cap Momentum Stock Screener

A Python stock screener for small-cap momentum stocks.

**Default Engine**: **Yahoo Finance (`screener.py`)** — **100% Free**, requires **NO API key**, no paid subscriptions, and no credit cards.

---

## Screening Criteria

The screener filters the US equity market based on these exact rules:
- **Price**: Between `$2.00` and `$10.00`
- **Volume**: Greater than or equal to `500,000` shares
- **Float**: Less than or equal to `10,000,000` shares (10M)
- **Market Cap**: Less than or equal to `$100M` ($100,000,000)
- **Gap / Change**: Greater than or equal to `+5.0%`

Results are automatically sorted by **Volume in descending order** and displayed as a clean, formatted Pandas DataFrame in your terminal.

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

## How to Run

### 1. Run the Screener (Free, Live Data)
No keys or setup needed:
```bash
python screener.py
```

#### Real Live Output Example:
```
================================================================================
                SMALL-CAP MOMENTUM SCREENER (YAHOO FINANCE)
================================================================================
Rules: Price: $2-$10 | Vol: >=500K | Float: <=10M | MktCap: <=$100M | Gap: >=+5%
--------------------------------------------------------------------------------
Ticker Price   Gap %     Volume Market Cap ($M) Est. Float (M)
  CLRO $5.93 +73.90% 32,990,241          $15.87           0.89
  FTFT $3.54 +21.27%    981,659          $28.60           5.39
  CENN $2.13 +15.76%    548,519          $37.46           2.34
--------------------------------------------------------------------------------
Total matching stocks: 3
================================================================================
```

### 2. Run the Midday Momentum Screener (11:30 AM – 2:00 PM EST)
Targets sustained intraday runners and momentum consolidations (Rules: Price $2–$10, Float <= 10M, MktCap <= $100M, Change >= +10%, **RVOL >= 5.0x**):
```bash
# Demo mock data mode
python midday_screener.py --demo

# Sort by Relative Volume (RVOL) descending
python midday_screener.py --demo --sort-by rvol

# Sort by percentage change descending
python midday_screener.py --demo --sort-by change

# Free live Yahoo Finance engine
python midday_screener.py --source yfinance

# Live Polygon.io engine (requires setting MASSIVE_API_KEY or POLYGON_API_KEY in .env/environment, or passing --api-key):
python midday_screener.py --source polygon --api-key "your_api_key_here"
# (or `python midday_screener.py --source polygon` if configured in .env)
```

### 3. Custom Parameters (Optional)
Tune any threshold directly via CLI flags:
```bash
python screener.py --min-price 3.00 --max-price 8.00 --min-gap 10.0
```

---

## Polygon.io / Massive Scripts (Optional / Paid)

If you ever upgrade to a paid Polygon.io / Massive plan (Starter at \$29/mo or Developer at \$79/mo with market-wide snapshot permissions), those scripts remain available:

- `python massive_screener.py` (uses official `massive` SDK)
- `python momentum_screener.py` (REST client with `--demo` mode)

---

## Running Tests

```bash
python -m pytest tests/test_screener.py -v
```
