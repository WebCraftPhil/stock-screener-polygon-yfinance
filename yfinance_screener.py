#!/usr/bin/env python3
"""
Small-Cap Momentum Stock Screener using Yahoo Finance (yfinance).

Completely free alternative to Polygon.io — requires NO paid subscription or API key.

Screening Rules:
  - Price: Between $2.00 and $10.00
  - Volume: >= 500,000 shares
  - Float: <= 10,000,000 shares (10M)
  - Market Cap: <= $100M ($100,000,000)
  - Gap / Gain: >= +5.0%

Fetches live market data from Yahoo Finance, filters against all rules,
sorts by volume in descending order, and displays a formatted Pandas DataFrame.
"""

import sys
import logging
import argparse
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import yfinance as yf

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("YFinanceScreener")


class YFinanceScreener:
    """Screener for small-cap momentum stocks using Yahoo Finance."""

    def __init__(
        self,
        min_price: float = 2.00,
        max_price: float = 10.00,
        min_volume: int = 500_000,
        max_float: float = 10_000_000,
        max_market_cap: float = 100_000_000,
        min_gap_pct: float = 5.0,
        max_workers: int = 6,
    ):
        self.min_price = min_price
        self.max_price = max_price
        self.min_volume = min_volume
        self.max_float = max_float
        self.max_market_cap = max_market_cap
        self.min_gap_pct = min_gap_pct
        self.max_workers = max_workers

    def fetch_candidates(self) -> List[Dict[str, Any]]:
        """
        Query Yahoo Finance equity screener with server-side filters on
        price, volume, market cap, and change percent.
        """
        logger.info("Querying Yahoo Finance screener for momentum candidates...")

        # Construct Yahoo Finance EquityQuery
        query = yf.EquityQuery("and", [
            yf.EquityQuery("gte", ["intradayprice", self.min_price]),
            yf.EquityQuery("lte", ["intradayprice", self.max_price]),
            yf.EquityQuery("gte", ["dayvolume", self.min_volume]),
            yf.EquityQuery("lte", ["intradaymarketcap", self.max_market_cap]),
            yf.EquityQuery("gte", ["percentchange", self.min_gap_pct]),
        ])

        try:
            res = yf.screen(query)
            quotes = res.get("quotes", [])
            logger.info(f"Retrieved {len(quotes)} candidate quote(s) from Yahoo Finance.")
            return quotes
        except Exception as e:
            logger.error(f"Error querying Yahoo Finance screener: {e}")
            return []

    def get_ticker_float_and_mcap(self, symbol: str) -> Dict[str, Optional[float]]:
        """Retrieve float shares and market cap for a given symbol."""
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info or {}
            float_shares = info.get("floatShares") or info.get("sharesOutstanding")
            market_cap = info.get("marketCap")
            return {
                "float_shares": float_shares,
                "market_cap": market_cap,
            }
        except Exception as e:
            logger.debug(f"Could not fetch info for {symbol}: {e}")
            return {"float_shares": None, "market_cap": None}

    def scan(self) -> pd.DataFrame:
        """Execute the screening pipeline and return the filtered DataFrame."""
        quotes = self.fetch_candidates()
        if not quotes:
            logger.info("No stocks matched the initial screener query.")
            return pd.DataFrame(
                columns=["Ticker", "Price", "Gap %", "Volume", "Market Cap ($M)", "Est. Float (M)"]
            )

        logger.info(f"Checking float and market cap fundamentals for {len(quotes)} candidate(s)...")
        matching_stocks = []

        def process_quote(q: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            symbol = q.get("symbol", "")
            # Filter to standard US tickers (exclude warrants, non-US suffixes like .AS, .XA)
            if not symbol or "." in symbol:
                return None

            price = q.get("regularMarketPrice") or q.get("preMarketPrice")
            gap_pct = q.get("regularMarketChangePercent") or q.get("preMarketChangePercent")
            volume = q.get("regularMarketVolume") or q.get("preMarketVolume") or 0
            m_cap = q.get("marketCap")

            if not price or price < self.min_price or price > self.max_price:
                return None
            if gap_pct is None or gap_pct < self.min_gap_pct:
                return None
            if volume < self.min_volume:
                return None

            # Fetch float details
            fundamentals = self.get_ticker_float_and_mcap(symbol)
            float_shares = fundamentals.get("float_shares")

            # Fallback for market cap if not in quote
            if not m_cap:
                m_cap = fundamentals.get("market_cap")

            # Fallback estimation if float is missing but market cap is present
            if float_shares is None and m_cap and price > 0:
                float_shares = m_cap / price

            # Fallback estimation if market cap is missing but float is present
            if m_cap is None and float_shares and price > 0:
                m_cap = float_shares * price

            # Enforce Market Cap <= $100M
            if m_cap is None or m_cap > self.max_market_cap:
                return None

            # Enforce Float <= 10M shares
            if float_shares is None or float_shares > self.max_float:
                return None

            return {
                "Ticker": symbol,
                "Price": float(price),
                "Gap %": float(gap_pct),
                "Volume": int(volume),
                "Market Cap": float(m_cap),
                "Est. Float": float(float_shares),
                "Market Cap ($M)": float(m_cap) / 1_000_000.0,
                "Est. Float (M)": float(float_shares) / 1_000_000.0,
            }

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = [executor.submit(process_quote, q) for q in quotes]
            for f in as_completed(futures):
                res = f.result()
                if res:
                    matching_stocks.append(res)

        if not matching_stocks:
            logger.info("No stocks matched all criteria after float and market cap verification.")
            return pd.DataFrame(
                columns=["Ticker", "Price", "Gap %", "Volume", "Market Cap ($M)", "Est. Float (M)"]
            )

        df = pd.DataFrame(matching_stocks)
        # Sort by volume in descending order
        df = df.sort_values(by="Volume", ascending=False).reset_index(drop=True)
        return df

    @staticmethod
    def format_dataframe_for_display(df: pd.DataFrame) -> pd.DataFrame:
        """Format values cleanly for terminal display."""
        if df.empty:
            return df

        display_df = pd.DataFrame()
        display_df["Ticker"] = df["Ticker"]
        display_df["Price"] = df["Price"].apply(lambda p: f"${p:,.2f}")
        display_df["Gap %"] = df["Gap %"].apply(lambda g: f"{g:+.2f}%")
        display_df["Volume"] = df["Volume"].apply(lambda v: f"{int(v):,}")
        display_df["Market Cap ($M)"] = df["Market Cap ($M)"].apply(lambda mc: f"${mc:,.2f}")
        display_df["Est. Float (M)"] = df["Est. Float (M)"].apply(lambda fl: f"{fl:,.2f}")
        return display_df


def print_screener_results(df: pd.DataFrame):
    """Print the formatted DataFrame to the terminal with header decorations."""
    columns_to_show = ["Ticker", "Price", "Gap %", "Volume", "Market Cap ($M)", "Est. Float (M)"]

    print("\n" + "=" * 80)
    print(" " * 16 + "SMALL-CAP MOMENTUM SCREENER (YAHOO FINANCE)")
    print("=" * 80)
    print("Rules: Price: $2-$10 | Vol: >=500K | Float: <=10M | MktCap: <=$100M | Gap: >=+5%")
    print("-" * 80)

    if df.empty:
        print("No stocks currently match all criteria.")
    else:
        formatted_df = YFinanceScreener.format_dataframe_for_display(df)[columns_to_show]

        pd.set_option("display.max_columns", None)
        pd.set_option("display.max_rows", None)
        pd.set_option("display.width", 1000)
        pd.set_option("display.colheader_justify", "right")

        print(formatted_df.to_string(index=False))

    print("-" * 80)
    print(f"Total matching stocks: {len(df)}")
    print("=" * 80 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Free small-cap momentum stock screener using Yahoo Finance."
    )
    parser.add_argument(
        "--min-price",
        type=float,
        default=2.00,
        help="Minimum stock price (default: $2.00)",
    )
    parser.add_argument(
        "--max-price",
        type=float,
        default=10.00,
        help="Maximum stock price (default: $10.00)",
    )
    parser.add_argument(
        "--min-volume",
        type=int,
        default=500_000,
        help="Minimum volume (default: 500,000 shares)",
    )
    parser.add_argument(
        "--max-float",
        type=float,
        default=10_000_000,
        help="Maximum float in shares (default: 10,000,000)",
    )
    parser.add_argument(
        "--max-market-cap",
        type=float,
        default=100_000_000,
        help="Maximum market cap in USD (default: $100,000,000)",
    )
    parser.add_argument(
        "--min-gap",
        type=float,
        default=5.0,
        help="Minimum gap / gain percentage (default: 5.0%%)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=6,
        help="Max worker threads (default: 6)",
    )

    args = parser.parse_args()

    screener = YFinanceScreener(
        min_price=args.min_price,
        max_price=args.max_price,
        min_volume=args.min_volume,
        max_float=args.max_float,
        max_market_cap=args.max_market_cap,
        min_gap_pct=args.min_gap,
        max_workers=args.workers,
    )
    df = screener.scan()
    print_screener_results(df)


if __name__ == "__main__":
    main()

