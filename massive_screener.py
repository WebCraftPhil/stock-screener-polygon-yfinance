#!/usr/bin/env python3
"""
Small-Cap Momentum Stock Screener using the official Massive Python Client.
Repository: https://github.com/massive-com/client-python

Screening Rules:
  - Price: $2.00 to $10.00
  - Premarket Volume: >= 500,000 shares
  - Float: <= 10,000,000 shares (10M)
  - Market Cap: <= $100M ($100,000,000)
  - Premarket Gap: >= +5.0%

Note: Querying full market snapshots requires a paid Massive/Polygon plan
(Starter or Developer). For free tier accounts, use yfinance_screener.py.
"""

import os
import sys
import argparse
import logging
import math
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

try:
    from massive import RESTClient
    from massive.exceptions import BadResponse, AuthError
except ImportError:
    print("[ERROR] The 'massive' package is not installed.")
    print("Run: pip install massive")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("MassiveScreener")


class MassiveMomentumScreener:
    """Screener using the official Massive (massive-com/client-python) SDK."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        min_price: float = 2.00,
        max_price: float = 10.00,
        min_volume: int = 500_000,
        max_float: float = 10_000_000,
        max_market_cap: float = 100_000_000,
        min_gap_pct: float = 5.0,
        max_workers: int = 5,
        float_mode: str = "strict",
    ):
        self.api_key = (
            api_key
            or os.getenv("MASSIVE_API_KEY")
            or os.getenv("POLYGON_API_KEY")
        )
        if not self.api_key:
            raise ValueError(
                "API Key is required. Please set MASSIVE_API_KEY in your .env file "
                "or pass it via --api-key / -k."
            )

        self.min_price = min_price
        self.max_price = max_price
        self.min_volume = min_volume
        self.max_float = max_float
        self.max_market_cap = max_market_cap
        self.min_gap_pct = min_gap_pct
        self.max_workers = max_workers
        self.float_mode = float_mode

        self.client = RESTClient(api_key=self.api_key)

    def fetch_all_snapshots(self) -> List[Any]:
        """Fetch US stock market snapshot via official Massive SDK."""
        logger.info("Fetching US market snapshot using Massive SDK (get_snapshot_all)...")
        try:
            snapshots = self.client.get_snapshot_all(market_type="stocks")
            logger.info(f"Retrieved {len(snapshots):,} ticker snapshots.")
            return snapshots
        except BadResponse as br:
            if "NOT_AUTHORIZED" in str(br) or "not entitled" in str(br):
                logger.error(
                    "\n[PLAN RESTRICTION] Your Massive API key is active, but your plan does not include "
                    "the market-wide real-time snapshot dataset.\n"
                    "Massive requires an upgraded plan (Starter or Developer) for this endpoint: "
                    "https://massive.com/pricing\n"
                    "To screen without a paid plan, use: python yfinance_screener.py\n"
                )
            raise
        except AuthError as ae:
            logger.error(f"Authentication failed: {ae}")
            raise

    def filter_snapshot_candidates(self, snapshots: List[Any]) -> List[Dict[str, Any]]:
        """Filter snapshot results by price, volume, and gap."""
        candidates = []
        for s in snapshots:
            ticker = getattr(s, "ticker", "")
            if not ticker:
                continue

            day = getattr(s, "day", None)
            min_bar = getattr(s, "min", None)
            prev_day = getattr(s, "prev_day", None)

            current_price = getattr(day, "close", None) or getattr(min_bar, "close", None)
            if not current_price or not (self.min_price <= current_price <= self.max_price):
                continue

            volume = getattr(day, "volume", 0) or 0
            if volume < self.min_volume:
                continue

            prev_close = getattr(prev_day, "close", None)
            if prev_close and prev_close > 0:
                gap_pct = ((current_price - prev_close) / prev_close) * 100.0
            else:
                gap_pct = getattr(s, "todays_change_percent", None)

            if gap_pct is None or gap_pct < self.min_gap_pct:
                continue

            candidates.append({
                "ticker": ticker,
                "price": float(current_price),
                "volume": int(volume),
                "gap_pct": float(gap_pct),
            })

        logger.info(f"Found {len(candidates)} candidate(s) meeting price, volume, and gap criteria.")
        return candidates

    def enrich_fundamentals(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Fetch ticker reference details and filter by market cap and float."""
        if not candidates:
            return []

        logger.info(f"Enriching reference data for {len(candidates)} candidates using Massive SDK...")
        results = []

        def process_cand(cand: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            ticker = cand["ticker"]
            try:
                details = self.client.get_ticker_details(ticker)
                if not details:
                    return None

                m_cap = getattr(details, "market_cap", None)
                float_shares = getattr(details, "free_float", None)
                shares_outstanding = getattr(details, "share_class_shares_outstanding", None) or getattr(details, "weighted_shares_outstanding", None)
                if not isinstance(float_shares, (int, float)) or not math.isfinite(float_shares) or float_shares <= 0:
                    float_shares = None
                if not isinstance(m_cap, (int, float)) or not math.isfinite(m_cap) or m_cap <= 0:
                    m_cap = None

                if m_cap is None or m_cap > self.max_market_cap:
                    return None
                if float_shares is None and self.float_mode == "strict":
                    return None
                if float_shares is not None and float_shares > self.max_float:
                    return None

                return {
                    "Ticker": ticker,
                    "Price": cand["price"],
                    "Gap %": cand["gap_pct"],
                    "Volume": cand["volume"],
                    "Market Cap": m_cap,
                    "Float": float_shares,
                    "Shares Outstanding": shares_outstanding,
                    "Float Status": "verified" if float_shares is not None else "unverified",
                    "Float Source": "Massive free_float" if float_shares is not None else None,
                    "Float Timestamp": getattr(details, "float_last_updated", None),
                    "Market Cap ($M)": m_cap / 1_000_000.0,
                    "Float (M)": float_shares / 1_000_000.0 if float_shares is not None else None,
                }
            except Exception as e:
                logger.debug(f"Failed to fetch details for {ticker}: {e}")
                return None

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = [executor.submit(process_cand, c) for c in candidates]
            for f in as_completed(futures):
                res = f.result()
                if res:
                    results.append(res)

        return results

    def scan(self) -> pd.DataFrame:
        """Run the full screening workflow."""
        snapshots = self.fetch_all_snapshots()
        candidates = self.filter_snapshot_candidates(snapshots)
        matches = self.enrich_fundamentals(candidates)

        if not matches:
            return pd.DataFrame(
                columns=["Ticker", "Price", "Gap %", "Volume", "Market Cap ($M)", "Float (M)"]
            )

        df = pd.DataFrame(matches)
        df = df.sort_values(by="Volume", ascending=False).reset_index(drop=True)
        return df

    @staticmethod
    def format_dataframe_for_display(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        disp = pd.DataFrame()
        disp["Ticker"] = df["Ticker"]
        disp["Price"] = df["Price"].apply(lambda p: f"${p:,.2f}")
        disp["Gap %"] = df["Gap %"].apply(lambda g: f"{g:+.2f}%")
        disp["Volume"] = df["Volume"].apply(lambda v: f"{int(v):,}")
        disp["Market Cap ($M)"] = df["Market Cap ($M)"].apply(lambda mc: f"${mc:,.2f}")
        disp["Float (M)"] = df["Float (M)"].apply(lambda fl: f"{fl:,.2f}" if pd.notna(fl) else "N/A")
        return disp


def print_results(df: pd.DataFrame):
    cols = ["Ticker", "Price", "Gap %", "Volume", "Market Cap ($M)", "Float (M)"]
    print("\n" + "=" * 80)
    print(" " * 18 + "MOMENTUM SCREENER (MASSIVE SDK)")
    print("=" * 80)
    print("Rules: Price: $2-$10 | Vol: >=500K | Float: <=10M | MktCap: <=$100M | Gap: >=+5%")
    print("-" * 80)

    if df.empty:
        print("No stocks matched all criteria at this time.")
    else:
        fdf = MassiveMomentumScreener.format_dataframe_for_display(df)[cols]
        pd.set_option("display.max_columns", None)
        pd.set_option("display.max_rows", None)
        pd.set_option("display.width", 1000)
        pd.set_option("display.colheader_justify", "right")
        print(fdf.to_string(index=False))

    print("-" * 80)
    print(f"Total matching stocks: {len(df)}")
    print("=" * 80 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Massive SDK Momentum Screener")
    parser.add_argument("-k", "--api-key", default=os.getenv("MASSIVE_API_KEY") or os.getenv("POLYGON_API_KEY"))
    args = parser.parse_args()

    try:
        screener = MassiveMomentumScreener(api_key=args.api_key)
        df = screener.scan()
        print_results(df)
    except Exception as e:
        sys.exit(1)


if __name__ == "__main__":
    main()

