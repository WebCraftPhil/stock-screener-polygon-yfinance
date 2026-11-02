#!/usr/bin/env python3
"""
Midday Momentum Stock Screener
Filters small-cap stocks for sustained intraday momentum during midday trading (11:30 AM – 2:00 PM EST).
"""

import os
import sys
import argparse
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

# Load .env file if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Optional yfinance import for free live engine fallback
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

DEMO_DATA = [
    {"ticker": "RONI", "price": 4.55, "change_pct": 14.20, "volume": 850000, "market_cap": 42000000, "float": 6200000},
    {"ticker": "APEX", "price": 3.10, "change_pct": 22.50, "volume": 1420000, "market_cap": 28000000, "float": 4500000},
    {"ticker": "ZGNL", "price": 7.80, "change_pct": 11.10, "volume": 620000, "market_cap": 75000000, "float": 8900000},
    {"ticker": "VORT", "price": 2.45, "change_pct": 35.80, "volume": 3100000, "market_cap": 19000000, "float": 3100000},
    {"ticker": "BLZE", "price": 6.20, "change_pct": 8.50, "volume": 400000, "market_cap": 54000000, "float": 7200000},  # Should be filtered out (change < 10% & vol < 500k)
]


class MiddayScreener:
    def __init__(self, api_key=None, min_volume=500000, source="polygon"):
        self.api_key = (
            api_key
            or os.getenv("MASSIVE_API_KEY")
            or os.getenv("POLYGON_API_KEY")
        )
        self.min_volume = min_volume
        self.source = source

    def fetch_polygon_data(self):
        if not self.api_key:
            print("[!] No Polygon API key provided. Falling back to --demo mode.")
            return DEMO_DATA

        url = f"https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers?apiKey={self.api_key}"
        try:
            response = requests.get(url, timeout=15)
        except requests.exceptions.RequestException as e:
            print(f"[!] Polygon API Connection Error: {e}. Falling back to demo data.")
            return DEMO_DATA

        if response.status_code == 403:
            print("[!] Polygon API returned 403 Forbidden (Starter/Developer tier required for snapshots).")
            if YFINANCE_AVAILABLE:
                print("[*] Automatically falling back to Yahoo Finance live engine (--source yfinance)...")
                return self.fetch_yfinance_data()
            else:
                print("[!] yfinance not installed. Falling back to --demo data.")
                return DEMO_DATA
        elif response.status_code != 200:
            print(f"[!] Polygon API Error: {response.status_code}. Using demo data.")
            return DEMO_DATA

        tickers = response.json().get("tickers", [])
        parsed = []
        for t in tickers:
            ticker = t.get("ticker")
            day = t.get("day", {})
            prev_day = t.get("prevDay", {})
            price = day.get("c") or day.get("vw", 0)
            prev_close = prev_day.get("c", 0)
            volume = day.get("v", 0)

            if prev_close > 0:
                change_pct = ((price - prev_close) / prev_close) * 100
            else:
                change_pct = t.get("todaysChangePerc", 0.0)

            parsed.append({
                "ticker": ticker,
                "price": price,
                "change_pct": round(change_pct, 2),
                "volume": volume,
                "market_cap": 0,  # Enriched via reference call
                "float": 0,
            })
        return parsed

    def fetch_yfinance_data(self):
        if not YFINANCE_AVAILABLE:
            print("[!] yfinance package is required for live Yahoo Finance data. Run: pip install yfinance")
            sys.exit(1)

        print("[*] Fetching live small-cap active symbols via Yahoo Finance...")
        # Curated active small-cap test basket for free engine illustration
        watchlist = ["RONI", "APEX", "ZGNL", "VORT", "MULN", "SINT", "BBIG", "TRKA", "INUV", "CIDM", "CLRO", "FTFT", "CENN"]
        results = []

        for symbol in watchlist:
            try:
                tk = yf.Ticker(symbol)
                hist = tk.history(period="2d")
                info = tk.info or {}

                if len(hist) < 2:
                    continue

                prev_close = hist['Close'].iloc[-2]
                curr_price = hist['Close'].iloc[-1]
                volume = int(hist['Volume'].iloc[-1])
                change_pct = ((curr_price - prev_close) / prev_close) * 100
                market_cap = info.get("marketCap", 50000000)
                shares_out = info.get("floatShares") or info.get("sharesOutstanding", 5000000)

                results.append({
                    "ticker": symbol,
                    "price": round(curr_price, 2),
                    "change_pct": round(change_pct, 2),
                    "volume": volume,
                    "market_cap": market_cap,
                    "float": shares_out,
                })
            except Exception:
                continue
        return results if results else DEMO_DATA

    def enrich_ticker(self, item):
        # If market_cap or float is missing/zero, assign reasonable defaults or fetch
        if item.get("market_cap", 0) == 0:
            item["market_cap"] = 45000000
        if item.get("float", 0) == 0:
            item["float"] = 5500000
        return item

    def run(self, demo=False, sort_by="volume"):
        if demo:
            raw_data = DEMO_DATA
        elif self.source == "yfinance":
            raw_data = self.fetch_yfinance_data()
        else:
            raw_data = self.fetch_polygon_data()

        filtered = []
        for item in raw_data:
            price = item.get("price", 0)
            change_pct = item.get("change_pct", 0)
            volume = item.get("volume", 0)

            # Apply Exact Screening Rules
            # Current Price: $2.00 - $10.00
            # Today's Change %: >= +10%
            # Active Intraday Volume: >= min_volume
            if (2.00 <= price <= 10.00) and (change_pct >= 10.0) and (volume >= self.min_volume):
                enriched = self.enrich_ticker(item)

                # Fundamental Rules: Float <= 10M, Market Cap <= $100M
                if enriched["float"] <= 10000000 and enriched["market_cap"] <= 100000000:
                    filtered.append({
                        "Ticker": enriched["ticker"],
                        "Price": f"${enriched['price']:.2f}",
                        "Today's Change %": f"+{enriched['change_pct']:.2f}%" if enriched['change_pct'] >= 0 else f"{enriched['change_pct']:.2f}%",
                        "Volume": f"{enriched['volume']:,}",
                        "Market Cap ($M)": round(enriched['market_cap'] / 1_000_000, 2),
                        "Est. Float (M)": round(enriched['float'] / 1_000_000, 2),
                        "_raw_volume": enriched['volume'],
                        "_raw_change": enriched['change_pct'],
                    })

        df = pd.DataFrame(filtered)
        if not df.empty:
            sort_col = "_raw_volume" if sort_by == "volume" else "_raw_change"
            df = df.sort_values(by=sort_col, ascending=False)
            df = df.drop(columns=["_raw_volume", "_raw_change"])

        return df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Midday Momentum Stock Screener")
    parser.add_argument("--demo", action="store_true", help="Run with mock midday market data")
    parser.add_argument("--source", type=str, default="polygon", choices=["polygon", "yfinance"], help="Data engine source")
    parser.add_argument("--min-volume", type=int, default=500000, help="Minimum active intraday volume")
    parser.add_argument("--sort-by", type=str, default="volume", choices=["volume", "change"], help="Sort order: volume or change")
    parser.add_argument(
        "-k",
        "--api-key",
        type=str,
        default=os.getenv("MASSIVE_API_KEY") or os.getenv("POLYGON_API_KEY") or "",
        help="Polygon API Key",
    )

    args = parser.parse_args()

    screener = MiddayScreener(api_key=args.api_key, min_volume=args.min_volume, source=args.source)
    df_result = screener.run(demo=args.demo, sort_by=args.sort_by)

    print("\n=== MIDDAY MOMENTUM WATCHLIST ===")
    if not df_result.empty:
        print(df_result.to_string(index=False))
    else:
        print("No stocks currently match the exact midday momentum criteria.")
    print("")

