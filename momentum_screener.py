#!/usr/bin/env python3
"""
Small-Cap Momentum Stock Screener using Polygon.io API.

Filters US equities matching the following criteria:
  - Price: $2.00 to $10.00
  - Premarket Volume: >= 500,000 shares
  - Float: <= 10,000,000 shares (10M)
  - Market Cap: <= $100,000,000 ($100M)
  - Premarket Gap: >= +5.0%

Fetches the market snapshot followed by ticker reference details,
sorts matching candidates by volume descending, and prints a formatted
Pandas DataFrame to the terminal.
"""

import os
import sys
import time
import argparse
import logging
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd

# Load environment variables from .env file if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("PolygonScreener")


class PolygonScreener:
    """Screener for small-cap momentum stocks using Polygon.io API."""

    BASE_URL = "https://api.polygon.io"

    def __init__(
        self,
        api_key: Optional[str] = None,
        min_price: float = 2.00,
        max_price: float = 10.00,
        min_volume: int = 500_000,
        max_float: float = 10_000_000,
        max_market_cap: float = 100_000_000,
        min_gap_pct: float = 5.0,
        timeout: int = 20,
        max_workers: int = 5,
    ):
        self.api_key = (
            api_key
            or os.getenv("MASSIVE_API_KEY")
            or os.getenv("POLYGON_API_KEY")
        )
        self.min_price = min_price
        self.max_price = max_price
        self.min_volume = min_volume
        self.max_float = max_float
        self.max_market_cap = max_market_cap
        self.min_gap_pct = min_gap_pct
        self.timeout = timeout
        self.max_workers = max_workers

        self.session = self._create_resilient_session()

    def _create_resilient_session(self) -> requests.Session:
        """Create a requests session with retries for transient errors and rate limits."""
        session = requests.Session()
        retries = Retry(
            total=4,
            backoff_factor=1.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=20)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _validate_api_key(self):
        """Validate that an API key is provided."""
        if not self.api_key or self.api_key.strip() == "":
            raise ValueError(
                "API Key is required. Please set MASSIVE_API_KEY or POLYGON_API_KEY in your .env file "
                "or environment, or pass it via --api-key / -k argument."
            )

    def fetch_all_tickers_snapshot(self) -> List[Dict[str, Any]]:
        """
        Fetch the current market snapshot for all US stock tickers.
        Endpoint: /v2/snapshot/locale/us/markets/stocks/tickers
        """
        self._validate_api_key()
        url = f"{self.BASE_URL}/v2/snapshot/locale/us/markets/stocks/tickers"
        params = {"apiKey": self.api_key}

        logger.info("Fetching US market snapshot from Polygon.io...")
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)

            if response.status_code == 401:
                raise PermissionError("HTTP 401 Unauthorized: Invalid Polygon.io API key.")
            elif response.status_code == 403:
                raise PermissionError(
                    "HTTP 403 Forbidden: Access to US stock snapshots is not allowed on your Polygon.io plan."
                )
            elif response.status_code == 429:
                raise RuntimeError("HTTP 429 Too Many Requests: Polygon.io rate limit reached.")

            response.raise_for_status()
            data = response.json()

            tickers = data.get("tickers", [])
            logger.info(f"Successfully retrieved snapshot for {len(tickers):,} tickers.")
            return tickers

        except requests.exceptions.Timeout:
            logger.error(f"Request timed out while fetching snapshot after {self.timeout}s.")
            raise
        except requests.exceptions.ConnectionError as ce:
            logger.error(f"Network connection error while contacting Polygon.io: {ce}")
            raise
        except requests.exceptions.RequestException as re:
            logger.error(f"API request failed while fetching snapshot: {re}")
            raise

    def fetch_ticker_details(self, ticker: str) -> Optional[Dict[str, Any]]:
        """
        Fetch reference data for a specific ticker to retrieve market cap and share count.
        Endpoint: /v3/reference/tickers/{ticker}
        """
        self._validate_api_key()
        url = f"{self.BASE_URL}/v3/reference/tickers/{ticker}"
        params = {"apiKey": self.api_key}

        try:
            response = self.session.get(url, params=params, timeout=self.timeout)

            if response.status_code == 429:
                # Rate limit handling: backoff briefly and retry once
                retry_after = int(response.headers.get("Retry-After", 12))
                logger.warning(f"Rate limited (429) on {ticker}. Pausing for {retry_after}s...")
                time.sleep(retry_after)
                response = self.session.get(url, params=params, timeout=self.timeout)

            if response.status_code == 404:
                logger.debug(f"Ticker details not found for {ticker} (404).")
                return None

            response.raise_for_status()
            data = response.json()
            return data.get("results")

        except requests.exceptions.RequestException as e:
            logger.warning(f"Failed to fetch reference details for {ticker}: {e}")
            return None

    def filter_snapshot_candidates(self, tickers_snapshot: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Pre-filter snapshot data based on price, premarket volume, and premarket gap.
        This dramatically reduces the number of ticker reference API calls needed.
        """
        candidates = []

        for item in tickers_snapshot:
            ticker = item.get("ticker", "")
            if not ticker:
                continue

            # Price extraction: prefer current session close/last price, then minute bar, then last trade
            day_data = item.get("day") or {}
            min_data = item.get("min") or {}
            prev_day_data = item.get("prevDay") or {}
            last_trade = item.get("lastTrade") or {}

            current_price = (
                day_data.get("c")
                or min_data.get("c")
                or last_trade.get("p")
            )
            if current_price is None or current_price <= 0:
                continue

            # 1. Price rule: $2.00 <= price <= $10.00
            if not (self.min_price <= current_price <= self.max_price):
                continue

            # 2. Volume rule: volume >= 500,000
            # During premarket, day.v represents accumulated premarket session volume
            volume = day_data.get("v") or 0
            if volume < self.min_volume:
                continue

            # 3. Premarket gap rule: gap >= +5.0%
            prev_close = prev_day_data.get("c")
            if prev_close and prev_close > 0:
                gap_pct = ((current_price - prev_close) / prev_close) * 100.0
            else:
                # Fallback to Polygon's todaysChangePerc if prevDay close is not populated
                gap_pct = item.get("todaysChangePerc")

            if gap_pct is None or gap_pct < self.min_gap_pct:
                continue

            candidates.append({
                "ticker": ticker,
                "price": float(current_price),
                "volume": int(volume),
                "gap_pct": float(gap_pct),
                "prev_close": float(prev_close) if prev_close else None,
            })

        logger.info(f"Found {len(candidates)} candidate(s) meeting price, volume, and gap criteria.")
        return candidates

    def enrich_and_filter_fundamentals(
        self, candidates: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Fetch reference data for candidate tickers and apply market cap and float rules:
          - Market Cap: <= $100M ($100,000,000)
          - Float: <= 10M shares (10,000,000)
        """
        if not candidates:
            return []

        logger.info(
            f"Fetching reference data (market cap and float) for {len(candidates)} candidate(s)..."
        )
        enriched_results = []

        def process_candidate(candidate: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            ticker = candidate["ticker"]
            details = self.fetch_ticker_details(ticker)
            if not details:
                return None

            # Extract market cap
            market_cap = details.get("market_cap")

            # Extract estimated float / shares outstanding
            # Polygon provides share_class_shares_outstanding, weighted_shares_outstanding,
            # or dedicated free float if available.
            est_float = (
                details.get("free_float")
                or details.get("float")
                or details.get("share_class_shares_outstanding")
                or details.get("weighted_shares_outstanding")
            )

            # Fallback estimation if market_cap is present but float is missing
            if est_float is None and market_cap and candidate["price"] > 0:
                est_float = market_cap / candidate["price"]

            # Fallback estimation if float is present but market_cap is missing
            if market_cap is None and est_float and candidate["price"] > 0:
                market_cap = est_float * candidate["price"]

            # Check market cap rule: <= $100M
            if market_cap is None or market_cap > self.max_market_cap:
                return None

            # Check float rule: <= 10M shares
            if est_float is None or est_float > self.max_float:
                return None

            return {
                "Ticker": ticker,
                "Price": candidate["price"],
                "Gap %": candidate["gap_pct"],
                "Volume": candidate["volume"],
                "Market Cap": market_cap,
                "Est. Float": est_float,
                "Market Cap ($M)": market_cap / 1_000_000.0,
                "Est. Float (M)": est_float / 1_000_000.0,
            }

        # Concurrently fetch reference details to minimize latency
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_cand = {
                executor.submit(process_candidate, cand): cand for cand in candidates
            }
            for future in as_completed(future_to_cand):
                try:
                    res = future.result()
                    if res:
                        enriched_results.append(res)
                except Exception as ex:
                    cand = future_to_cand[future]
                    logger.warning(f"Error enriching {cand.get('ticker')}: {ex}")

        return enriched_results

    def scan(self) -> pd.DataFrame:
        """
        Execute the full screening workflow:
          1. Fetch market snapshot
          2. Filter on price, volume, and gap
          3. Enrich candidates with reference data (market cap & float)
          4. Filter on market cap and float
          5. Sort by volume in descending order
          6. Construct formatted output DataFrame
        """
        snapshot = self.fetch_all_tickers_snapshot()
        candidates = self.filter_snapshot_candidates(snapshot)
        matches = self.enrich_and_filter_fundamentals(candidates)

        if not matches:
            logger.info("No tickers matched all screening criteria.")
            # Return empty DataFrame with specified columns
            return pd.DataFrame(
                columns=["Ticker", "Price", "Gap %", "Volume", "Market Cap ($M)", "Est. Float (M)"]
            )

        df = pd.DataFrame(matches)

        # Sort by volume in descending order
        df = df.sort_values(by="Volume", ascending=False).reset_index(drop=True)

        return df

    @staticmethod
    def format_dataframe_for_display(df: pd.DataFrame) -> pd.DataFrame:
        """
        Format values cleanly for terminal display:
          - Price: $X.XX
          - Gap %: +X.XX%
          - Volume: 1,234,567
          - Market Cap ($M): $X.XX
          - Est. Float (M): X.XX
        """
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


def get_mock_snapshot_data() -> List[Dict[str, Any]]:
    """Generate realistic mock snapshot data for testing and demonstrations."""
    return [
        {
            "ticker": "MOMN",
            "todaysChangePerc": 14.5,
            "day": {"c": 3.45, "v": 1_850_000},
            "prevDay": {"c": 3.01},
        },
        {
            "ticker": "RUNR",
            "todaysChangePerc": 8.2,
            "day": {"c": 5.20, "v": 2_450_000},
            "prevDay": {"c": 4.80},
        },
        {
            "ticker": "ROCK",
            "todaysChangePerc": 22.0,
            "day": {"c": 8.10, "v": 620_000},
            "prevDay": {"c": 6.64},
        },
        {
            "ticker": "BIGC",  # Large cap - should be excluded by market cap filter
            "todaysChangePerc": 6.5,
            "day": {"c": 4.50, "v": 3_100_000},
            "prevDay": {"c": 4.22},
        },
        {
            "ticker": "HIGHF",  # Huge float - should be excluded by float filter
            "todaysChangePerc": 11.0,
            "day": {"c": 6.80, "v": 950_000},
            "prevDay": {"c": 6.12},
        },
        {
            "ticker": "LOWV",  # Low volume - should be excluded by volume filter
            "todaysChangePerc": 15.0,
            "day": {"c": 3.00, "v": 120_000},
            "prevDay": {"c": 2.60},
        },
        {
            "ticker": "EXPNS",  # High price - should be excluded by price filter
            "todaysChangePerc": 7.0,
            "day": {"c": 15.50, "v": 800_000},
            "prevDay": {"c": 14.48},
        },
        {
            "ticker": "NGAP",  # Gap < 5% - should be excluded
            "todaysChangePerc": 2.1,
            "day": {"c": 4.00, "v": 750_000},
            "prevDay": {"c": 3.92},
        },
    ]


def get_mock_ticker_details(ticker: str) -> Optional[Dict[str, Any]]:
    """Return mock fundamental reference data for demo tickers."""
    mock_db = {
        "MOMN": {
            "market_cap": 25_000_000,
            "share_class_shares_outstanding": 7_200_000,
        },
        "RUNR": {
            "market_cap": 48_000_000,
            "share_class_shares_outstanding": 9_100_000,
        },
        "ROCK": {
            "market_cap": 18_500_000,
            "share_class_shares_outstanding": 2_300_000,
        },
        "BIGC": {
            "market_cap": 450_000_000,  # Fails market cap <= 100M
            "share_class_shares_outstanding": 8_000_000,
        },
        "HIGHF": {
            "market_cap": 60_000_000,
            "share_class_shares_outstanding": 35_000_000,  # Fails float <= 10M
        },
    }
    return mock_db.get(ticker)


def run_demo():
    """Run a simulated demonstration of the screener using mock data."""
    logger.info("Running in DEMO mode with realistic sample market data...")
    screener = PolygonScreener(api_key="DEMO_KEY")

    snapshot = get_mock_snapshot_data()
    candidates = screener.filter_snapshot_candidates(snapshot)

    # Enrich candidates using mock details
    matches = []
    for cand in candidates:
        details = get_mock_ticker_details(cand["ticker"])
        if not details:
            continue
        m_cap = details.get("market_cap")
        fl = details.get("share_class_shares_outstanding")

        if m_cap and m_cap <= screener.max_market_cap and fl and fl <= screener.max_float:
            matches.append({
                "Ticker": cand["ticker"],
                "Price": cand["price"],
                "Gap %": cand["gap_pct"],
                "Volume": cand["volume"],
                "Market Cap": m_cap,
                "Est. Float": fl,
                "Market Cap ($M)": m_cap / 1_000_000.0,
                "Est. Float (M)": fl / 1_000_000.0,
            })

    df = pd.DataFrame(matches)
    if not df.empty:
        df = df.sort_values(by="Volume", ascending=False).reset_index(drop=True)

    print_screener_results(df)


def print_screener_results(df: pd.DataFrame):
    """Print the formatted DataFrame to the terminal with header decorations."""
    columns_to_show = ["Ticker", "Price", "Gap %", "Volume", "Market Cap ($M)", "Est. Float (M)"]

    print("\n" + "=" * 80)
    print(" " * 20 + "SMALL-CAP MOMENTUM SCREENER RESULTS")
    print("=" * 80)
    print("Rules: Price: $2-$10 | Vol: >=500K | Float: <=10M | MktCap: <=$100M | Gap: >=+5%")
    print("-" * 80)

    if df.empty:
        print("No stocks matched all criteria at this time.")
    else:
        formatted_df = PolygonScreener.format_dataframe_for_display(df)[columns_to_show]

        # Configure Pandas display options so the terminal doesn't truncate or wrap awkwardly
        pd.set_option("display.max_columns", None)
        pd.set_option("display.max_rows", None)
        pd.set_option("display.width", 1000)
        pd.set_option("display.colheader_justify", "right")

        # Print using to_string for consistent, clean terminal formatting
        print(formatted_df.to_string(index=False))

    print("-" * 80)
    print(f"Total matching stocks: {len(df)}")
    print("=" * 80 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Scan Polygon.io / Massive for small-cap momentum stocks matching exact premarket rules."
    )
    parser.add_argument(
        "-k",
        "--api-key",
        type=str,
        default=os.getenv("MASSIVE_API_KEY") or os.getenv("POLYGON_API_KEY"),
        help="Massive / Polygon.io API Key (defaults to MASSIVE_API_KEY or POLYGON_API_KEY env var)",
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
        help="Minimum premarket volume (default: 500,000 shares)",
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
        help="Maximum market capitalization in USD (default: $100,000,000)",
    )
    parser.add_argument(
        "--min-gap",
        type=float,
        default=5.0,
        help="Minimum premarket gap percentage (default: 5.0%%)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=5,
        help="Max concurrent worker threads for ticker reference lookups (default: 5)",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run screener with sample mock data to demonstrate output without an API key",
    )

    args = parser.parse_args()

    if args.demo:
        run_demo()
        return

    if not args.api_key:
        print("\n[ERROR] Missing API Key!")
        print("Please provide your API key in one of these ways:")
        print("  1. In your .env file:")
        print("     MASSIVE_API_KEY=your_api_key_here")
        print("     (or POLYGON_API_KEY=your_api_key_here)")
        print("  2. Export the environment variable:")
        print("     export MASSIVE_API_KEY='your_api_key_here'")
        print("  3. Pass it as a command line argument:")
        print("     python momentum_screener.py --api-key 'your_api_key_here'")
        print("\nTip: To see a test run with mock data, run:")
        print("     python momentum_screener.py --demo\n")
        sys.exit(1)

    try:
        screener = PolygonScreener(
            api_key=args.api_key,
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

    except PermissionError as pe:
        logger.error(f"Authentication / Permissions Error: {pe}")
        sys.exit(1)
    except requests.exceptions.RequestException as re:
        logger.error(f"Network / HTTP Error communicating with Polygon.io: {re}")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Unexpected error during screening: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

