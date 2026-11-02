# Small-Cap Momentum Stock Screener (Polygon.io)

A Python screener utilizing the [Polygon.io](https://polygon.io) REST API to identify high-momentum small-cap stocks setting up during premarket trading.

## Screening Criteria

The screener filters the US equity market based on these exact rules:
- **Price**: Between `$2.00` and `$10.00`
- **Premarket Volume**: Greater than or equal to `500,000` shares
- **Float**: Less than or equal to `10,000,000` shares (10M)
- **Market Cap**: Less than or equal to `$100M` ($100,000,000)
- **Premarket Gap**: Greater than or equal to `+5.0%`

Results are automatically sorted by **Volume in descending order** and displayed as a clean, formatted Pandas DataFrame in the terminal.

---

## Output Columns

| Column | Description | Format |
| :--- | :--- | :--- |
| **Ticker** | Stock symbol | `ABCD` |
| **Price** | Current / premarket trade price | `$4.50` |
| **Gap %** | Percentage change from previous close | `+14.62%` |
| **Volume** | Current session cumulative volume | `1,850,000` |
| **Market Cap ($M)** | Market capitalization in millions | `$25.00` |
| **Est. Float (M)** | Estimated public float in millions | `7.20` |

---

## Installation & Setup

1. **Clone & Navigate:**
   ```bash
   cd stock-screener-polygon-yfinance
   ```

2. **Create and Activate Virtual Environment:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure API Key:**
   The screener supports keys configured under either `MASSIVE_API_KEY` or `POLYGON_API_KEY`.
   
   Create or edit the `.env` file in the project root:
   ```env
   MASSIVE_API_KEY=your_api_key_here
   ```
   *(or `POLYGON_API_KEY=your_api_key_here`)*

   Alternatively, export it directly in your terminal:
   ```bash
   export MASSIVE_API_KEY="your_api_key_here"
   ```

---

## Usage

### 1. Live Screening
Run the screener against the live Polygon.io API:
```bash
python momentum_screener.py
```

Pass the API key explicitly if not using environment variables:
```bash
python momentum_screener.py --api-key "your_api_key_here"
```

### 2. Demonstration / Mock Mode
Test the script and verify the output formatting and filtering rules without needing an active API key:
```bash
python momentum_screener.py --demo
```

### 3. Custom Thresholds
All screening parameters can be adjusted via CLI flags:
```bash
python momentum_screener.py \
  --min-price 3.00 \
  --max-price 8.00 \
  --min-volume 1000000 \
  --max-float 8000000 \
  --max-market-cap 80000000 \
  --min-gap 10.0
```

---

## Running Tests

Execute the unit test suite:
```bash
python -m pytest tests/test_screener.py -v
```
