#!/usr/bin/env python3
"""
Small-Cap Momentum Stock Screener using Finnhub API.
https://finnhub.io/docs/api

Screening Rules:
  - Price: $2.00 to $10.00
  - Float: <= 10,000,000 shares (10M)
  - Market Cap: <= $100M ($100,000,000)
  - Price Change: >= +10.0% (midday) or >= +5.0% (morning)
  - Active Intraday Volume / RVOL >= 5.0x

Fetches live quotes and company profile data (market cap, float, 10-day avg volume)
using Finnhub API, filters matching candidates, and displays a formatted Pandas DataFrame.
"""

import os
import sys
import argparse
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from dotenv import load_dotenv
from scan_io import load_watchlist, missing_symbols, scan_metadata, write_scan

load_dotenv()

try:
    import finnhub
    FINNHUB_AVAILABLE = True
except ImportError:
    FINNHUB_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("FinnhubScreener")

# Active momentum candidate universe for small-cap screening
ACTIVE_WATCHLIST = [
    "CLRO", "FTFT", "CENN", "VORT", "APEX", "RONI", "ZGNL",
    "SINT", "BBIG", "TRKA", "INUV", "MULN", "MVIS", "BIMI",
    "GME", "AMC", "KOSS", "MARA", "RIOT", "SOUN", "WISA"
]

DEMO_DATA = [
    {"ticker": "RONI", "price": 4.55, "change_pct": 14.20, "volume": 850000, "avg_volume": 100000, "market_cap": 42.0, "float": 6.2},
    {"ticker": "APEX", "price": 3.10, "change_pct": 22.50, "volume": 1420000, "avg_volume": 200000, "market_cap": 28.0, "float": 4.5},
    {"ticker": "ZGNL", "price": 7.80, "change_pct": 11.10, "volume": 620000, "avg_volume": 100000, "market_cap": 75.0, "float": 8.9},
    {"ticker": "VORT", "price": 2.45, "change_pct": 35.80, "volume": 3100000, "avg_volume": 250000, "market_cap": 19.0, "float": 3.1},
    {"ticker": "BLZE", "price": 6.20, "change_pct": 8.50, "volume": 400000, "avg_volume": 200000, "market_cap": 54.0, "float": 7.2},
]


class FinnhubScreener:
    """Screener using Finnhub REST API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        min_price: float = 2.00,
        max_price: float = 10.00,
        min_change_pct: float = 10.0,
        max_float: float = 10.0,  # in Millions
        max_market_cap: float = 100.0,  # in Millions
        min_rvol: float = 1.0,
        min_volume: int = 500_000,
        max_workers: int = 5,
        float_mode: str = "strict",
    ):
        self.api_key = api_key or os.getenv("FINNHUB_API_KEY")
        self.min_price = min_price
        self.max_price = max_price
        self.min_change_pct = min_change_pct
        self.max_float = max_float
        self.max_market_cap = max_market_cap
        self.min_rvol = min_rvol
        self.min_volume = min_volume
        self.max_workers = max_workers
        self.float_mode = float_mode
        self.last_status = "ok"
        self.last_error = None

        if not FINNHUB_AVAILABLE:
            logger.warning("finnhub-python package not installed. Run: pip install finnhub-python")
            self.client = None
        elif self.api_key:
            self.client = finnhub.Client(api_key=self.api_key)
        else:
            self.client = None

    def fetch_ticker_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch quote, company profile, and basic metrics for a ticker via Finnhub."""
        if not self.client:
            return None

        try:
            # 1. Real-time quote
            quote = self.client.quote(symbol)
            if not quote or not quote.get("c"):
                return None

            price = float(quote["c"])
            change_pct = float(quote.get("dp", 0.0))
            quote_timestamp = quote.get("t")
            now_epoch = int(datetime.now(timezone.utc).timestamp())
            if not isinstance(quote_timestamp, (int, float)) or quote_timestamp <= 0 or now_epoch - quote_timestamp > 15 * 60:
                self.last_status = "stale"
                self.last_error = f"Finnhub quote was missing a current timestamp or stale for {symbol}."
                return None

            # Quick price and change pre-filter
            if not (self.min_price <= price <= self.max_price):
                return None
            if change_pct < self.min_change_pct:
                return None

            # 2. Company profile (Market Cap & Float)
            profile = self.client.company_profile2(symbol=symbol) or {}
            mcap_m = profile.get("marketCapitalization")  # Already in Millions USD
            float_m = profile.get("floatingShare")  # Explicit public float only, in millions
            if not isinstance(mcap_m, (int, float)) or not math.isfinite(mcap_m) or mcap_m <= 0:
                self.last_status = "incomplete"
                self.last_error = f"Finnhub market capitalization was unavailable for {symbol}."
                return None
            if not isinstance(float_m, (int, float)) or not math.isfinite(float_m) or float_m <= 0:
                float_m = None

            # Filter market cap and float
            if mcap_m is None or mcap_m > self.max_market_cap:
                return None
            if float_m is not None and float_m > self.max_float:
                return None
            if float_m is None and self.float_mode == "strict":
                self.last_status = "incomplete"
                self.last_error = f"Finnhub public float was unavailable for {symbol}; strict mode excluded it."
                return None
            if float_m is None:
                self.last_status = "incomplete"
                self.last_error = f"Finnhub public float is unknown for {symbol}; discovery mode retained it as unverified."

            # Finnhub quote has no session volume. Use daily candles only when
            # available, calculating RVOL against prior full-day candles.
            now = int(datetime.now(timezone.utc).timestamp())
            start = int((datetime.now(timezone.utc) - timedelta(days=20)).timestamp())
            candles = self.client.stock_candles(symbol, "D", start, now) or {}
            volumes = candles.get("v") if candles.get("s") == "ok" else None
            timestamps = candles.get("t") if candles.get("s") == "ok" else None
            if not isinstance(volumes, list) or len(volumes) < 2 or not isinstance(timestamps, list) or len(timestamps) != len(volumes):
                self.last_status = "incomplete"
                self.last_error = "Finnhub daily candles were unavailable; candidates without observed volume and baseline were excluded."
                return None
            if now - int(timestamps[-1]) > 24 * 60 * 60:
                self.last_status = "incomplete"
                self.last_error = "Finnhub daily candle volume was stale; candidate was excluded."
                return None
            current_volume = int(volumes[-1])
            baseline_values = [float(value) for value in volumes[:-1] if isinstance(value, (int, float)) and value > 0]
            if current_volume <= 0 or not baseline_values:
                self.last_status = "incomplete"
                self.last_error = "Finnhub daily candles did not contain valid volume data."
                return None
            avg_vol = sum(baseline_values) / len(baseline_values)
            rvol = current_volume / avg_vol
            if current_volume < self.min_volume or rvol < self.min_rvol:
                return None

            return {
                "Ticker": symbol,
                "Price": price,
                "Today's Change %": change_pct,
                "Volume": current_volume,
                "RVOL": rvol,
                "Market Cap ($M)": round(float(mcap_m), 2),
                "Float (M)": round(float(float_m), 2) if float_m is not None else None,
                "Float Status": "verified" if float_m is not None else "unverified",
                "Quote Source": "Finnhub",
                "Volume Source": "Finnhub daily candles",
                "RVOL Type": "daily",
                "Quote Timestamp": datetime.fromtimestamp(quote_timestamp, timezone.utc).isoformat(),
                "Data Freshness": "current (under 15 minutes)",
            }

        except Exception as e:
            self.last_status = "incomplete"
            self.last_error = f"Finnhub data unavailable for {symbol} ({type(e).__name__})."
            logger.debug(f"Error fetching Finnhub data for {symbol}: {e}")
            return None

    def scan(self, watchlist: Optional[List[str]] = None, demo: bool = False) -> pd.DataFrame:
        """Run the Finnhub screener."""
        self.last_status = "ok"
        self.last_error = None
        if demo:
            return self._run_demo()
        if not self.client:
            self.last_status = "failed"
            self.last_error = "Finnhub client or API key is unavailable."
            return pd.DataFrame()

        symbols = watchlist or ACTIVE_WATCHLIST
        logger.info(f"Scanning {len(symbols)} symbols via Finnhub API...")

        matches = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(self.fetch_ticker_data, sym): sym for sym in symbols}
            for future in as_completed(futures):
                res = future.result()
                if res:
                    matches.append(res)

        if not matches:
            logger.info("No symbols currently matched the exact momentum criteria on Finnhub.")
            return pd.DataFrame(columns=["Ticker", "Price", "Today's Change %", "Volume", "RVOL", "Market Cap ($M)", "Float (M)"])

        df = pd.DataFrame(matches)
        df = df.sort_values(by="Today's Change %", ascending=False).reset_index(drop=True)
        return df

    def _run_demo(self) -> pd.DataFrame:
        filtered = []
        for d in DEMO_DATA:
            rvol = round(d["volume"] / d["avg_volume"], 1) if d["avg_volume"] > 0 else 1.0
            if (self.min_price <= d["price"] <= self.max_price) and (d["change_pct"] >= self.min_change_pct) and (rvol >= self.min_rvol):
                if d["float"] <= self.max_float and d["market_cap"] <= self.max_market_cap:
                    filtered.append({
                        "Ticker": d["ticker"],
                        "Price": d["price"],
                        "Today's Change %": d["change_pct"],
                        "Volume": d["volume"],
                        "RVOL": rvol,
                        "Market Cap ($M)": d["market_cap"],
                        "Float (M)": d["float"],
                    })
        df = pd.DataFrame(filtered)
        if not df.empty:
            df = df.sort_values(by="Volume", ascending=False).reset_index(drop=True)
        return df

    @staticmethod
    def format_dataframe(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        display_df = pd.DataFrame()
        display_df["Ticker"] = df["Ticker"]
        display_df["Price"] = df["Price"].apply(lambda p: f"${p:,.2f}")
        display_df["Today's Change %"] = df["Today's Change %"].apply(lambda c: f"{c:+.2f}%")
        display_df["Volume"] = df["Volume"].apply(lambda v: f"{int(v):,}")
        display_df["RVOL"] = df["RVOL"].apply(lambda r: f"{r:.1f}x")
        display_df["Market Cap ($M)"] = df["Market Cap ($M)"].apply(lambda m: f"${m:,.2f}")
        if "Float (M)" in df:
            display_df["Float (M)"] = df["Float (M)"].apply(lambda f: f"{f:,.2f}" if pd.notna(f) else "N/A")
        return display_df


def print_results(df: pd.DataFrame):
    print("\n" + "=" * 85)
    print(" " * 20 + "SMALL-CAP MOMENTUM SCREENER (FINNHUB API)")
    print("=" * 85)
    print("Rules: Price: $2-$10 | Change: >=+10% | Float: <=10M | MktCap: <=$100M | RVOL: >=1.0x")
    print("-" * 85)

    if df.empty:
        print("No stocks matched all criteria at this time.")
    else:
        fdf = FinnhubScreener.format_dataframe(df)
        pd.set_option("display.max_columns", None)
        pd.set_option("display.max_rows", None)
        pd.set_option("display.width", 1000)
        pd.set_option("display.colheader_justify", "right")
        print(fdf.to_string(index=False))

    print("-" * 85)
    print(f"Total matching stocks: {len(df)}")
    print("=" * 85 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Finnhub Small-Cap Momentum Screener")
    parser.add_argument("--demo", action="store_true", help="Run with sample mock data")
    parser.add_argument("--min-price", type=float, default=2.00, help="Minimum stock price")
    parser.add_argument("--max-price", type=float, default=10.00, help="Maximum stock price")
    parser.add_argument("--min-change", type=float, default=10.0, help="Minimum percentage change")
    parser.add_argument("--max-float", type=float, default=10.0, help="Maximum float in Millions")
    parser.add_argument("--max-market-cap", type=float, default=100.0, help="Maximum market cap in Millions")
    parser.add_argument("-k", "--api-key", default=os.getenv("FINNHUB_API_KEY"), help="Finnhub API Key")
    parser.add_argument("--float-mode", choices=["strict", "discovery"], default="strict")
    parser.add_argument("--watchlist", help="Ticker list file (one symbol per line or comma-separated)")
    parser.add_argument("--export", help="Write scan results and metadata to CSV")
    parser.add_argument("--history", help="Append scan results and metadata to a CSV history file")

    args = parser.parse_args()

    screener = FinnhubScreener(
        api_key=args.api_key,
        min_price=args.min_price,
        max_price=args.max_price,
        min_change_pct=args.min_change,
        max_float=args.max_float,
        max_market_cap=args.max_market_cap,
        float_mode=args.float_mode,
    )
    watchlist, invalid = load_watchlist(args.watchlist) if args.watchlist else (None, [])
    if invalid:
        print("[WARNING] Ignoring invalid watchlist entries: " + ", ".join(invalid))
    if args.watchlist and not watchlist:
        parser.error("watchlist contains no valid ticker symbols")
    df = screener.scan(watchlist=watchlist, demo=args.demo)
    print_results(df)
    if screener.last_status != "ok":
        print(f"[SCAN STATUS: {screener.last_status}] {screener.last_error or ''}")
    if watchlist:
        missing = missing_symbols(watchlist, df.get("Ticker", []))
        if missing:
            print("[WARNING] No qualifying provider result for: " + ", ".join(missing))
    metadata = scan_metadata("finnhub", {"min_price": args.min_price, "max_price": args.max_price, "min_change": args.min_change, "min_volume": screener.min_volume, "min_rvol": screener.min_rvol, "max_float_m": args.max_float, "max_market_cap_m": args.max_market_cap, "float_mode": args.float_mode, "watchlist": args.watchlist or "built-in universe"}, status=screener.last_status, message=screener.last_error)
    if args.export:
        write_scan(df, args.export, metadata)
        print(f"CSV export saved: {args.export}")
    if args.history:
        write_scan(df, args.history, metadata, append=True)
        print(f"Scan appended to history: {args.history}")


if __name__ == "__main__":
    main()

