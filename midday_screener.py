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
import math
import time
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
    {"ticker": "RONI", "price": 4.55, "change_pct": 14.20, "volume": 850000, "avg_volume": 100000, "market_cap": 42000000, "float": 6200000},  # rvol = 8.5x
    {"ticker": "APEX", "price": 3.10, "change_pct": 22.50, "volume": 1420000, "avg_volume": 200000, "market_cap": 28000000, "float": 4500000},  # rvol = 7.1x
    {"ticker": "ZGNL", "price": 7.80, "change_pct": 11.10, "volume": 620000, "avg_volume": 100000, "market_cap": 75000000, "float": 8900000},  # rvol = 6.2x
    {"ticker": "VORT", "price": 2.45, "change_pct": 35.80, "volume": 3100000, "avg_volume": 250000, "market_cap": 19000000, "float": 3100000},  # rvol = 12.4x
    {"ticker": "BLZE", "price": 6.20, "change_pct": 8.50, "volume": 400000, "avg_volume": 200000, "market_cap": 54000000, "float": 7200000},  # Filtered out (change < 10% & rvol < 5x)
    {"ticker": "SLOW", "price": 5.00, "change_pct": 15.00, "volume": 300000, "avg_volume": 150000, "market_cap": 30000000, "float": 5000000},  # Filtered out (rvol = 2.0x < 5.0x)
]


class MiddayScreener:
    def __init__(self, api_key=None, min_volume=500000, source="polygon", min_rvol=5.0, float_mode="strict"):
        self.api_key = (
            api_key
            or os.getenv("MASSIVE_API_KEY")
            or os.getenv("POLYGON_API_KEY")
        )
        self.min_volume = min_volume
        if isinstance(source, (int, float)) and min_rvol == 5.0:
            min_rvol = source
            source = "polygon"
        self.source = source
        self.float_mode = float_mode
        try:
            self.min_rvol = float(min_rvol)
        except (ValueError, TypeError):
            self.min_rvol = 5.0
        self.last_error = None
        self.last_status = "ok"
        self._avg_volume_cache = {}

    def _get(self, url, **kwargs):
        """Bounded retry for transient rate-limit/server/network failures."""
        for attempt in range(3):
            try:
                response = requests.get(url, **kwargs)
                if response.status_code == 429 or 500 <= response.status_code < 600:
                    if attempt < 2:
                        time.sleep(0.25 * (2 ** attempt))
                        continue
                return response
            except requests.exceptions.RequestException:
                if attempt == 2:
                    raise
                time.sleep(0.25 * (2 ** attempt))

    def fetch_polygon_data(self):
        if not self.api_key:
            self.last_status = "failed"
            self.last_error = "No Polygon API key provided. Set MASSIVE_API_KEY or POLYGON_API_KEY, or pass --api-key."
            print(f"[!] {self.last_error}")
            return []

        url = "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            response = self._get(url, headers=headers, timeout=15)
        except requests.exceptions.RequestException as e:
            safe_err = str(e).replace(self.api_key, "[REDACTED]") if self.api_key else str(e)
            self.last_status = "failed"
            self.last_error = f"Polygon API Connection Error: {safe_err}"
            print(f"[!] {self.last_error}")
            return []

        if response.status_code == 403:
            print("[!] Polygon API returned 403 Forbidden (Starter/Developer tier required for snapshots).")
            if YFINANCE_AVAILABLE:
                print("[*] Automatically falling back to Yahoo Finance live engine (--source yfinance)...")
                return self.fetch_yfinance_data()
            else:
                self.last_status = "failed"
                self.last_error = "Polygon API returned 403 Forbidden and yfinance is not available."
                print(f"[!] {self.last_error}")
                return []
        elif response.status_code != 200:
            self.last_status = "failed"
            self.last_error = f"Polygon API Error: HTTP {response.status_code}."
            print(f"[!] {self.last_error}")
            return []

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

            avg_vol = None
            avg_vol_attempted = False
            if (2.00 <= price <= 10.00) and (change_pct >= 10.0) and (volume >= self.min_volume):
                avg_vol = self.fetch_polygon_historical_avg_volume(ticker, days=10)
                avg_vol_attempted = True

            parsed.append({
                "ticker": ticker,
                "price": price,
                "change_pct": round(change_pct, 2),
                "volume": volume,
                "avg_volume": avg_vol,
                "avg_volume_attempted": avg_vol_attempted,
                "market_cap": None,  # Enriched via reference call
                "float": None,
            })
        return parsed

    def fetch_yfinance_data(self):
        if not YFINANCE_AVAILABLE:
            self.last_status = "failed"
            self.last_error = "yfinance package is required for live Yahoo Finance data."
            print(f"[!] {self.last_error} Run: pip install yfinance")
            return []

        print("[*] Fetching live small-cap active symbols via Yahoo Finance...")
        results = []
        # Yahoo's screener provides dynamic discovery but has limited, opaque
        # coverage and is not a guaranteed market-wide feed.
        try:
            query = yf.EquityQuery("and", [
                yf.EquityQuery("gte", ["intradayprice", 2.0]),
                yf.EquityQuery("lte", ["intradayprice", 10.0]),
                yf.EquityQuery("gte", ["dayvolume", self.min_volume]),
                yf.EquityQuery("gte", ["percentchange", 10.0]),
            ])
            quotes = yf.screen(query, size=250).get("quotes", [])
        except Exception as exc:
            self.last_status = "failed"
            self.last_error = f"Yahoo Finance discovery failed ({type(exc).__name__})."
            print(f"[!] {self.last_error}")
            return []

        for quote in quotes:
            symbol = quote.get("symbol")
            if not symbol or "." in symbol:
                continue
            try:
                tk = yf.Ticker(symbol)
                info = tk.info or {}
                curr_price = quote.get("regularMarketPrice")
                change_pct = quote.get("regularMarketChangePercent")
                volume = quote.get("regularMarketVolume")
                market_cap = info.get("marketCap")
                float_shares = info.get("floatShares")
                avg_vol = info.get("averageVolume10days") or info.get("averageVolume")
                if not curr_price or change_pct is None or volume is None:
                    continue

                results.append({
                    "ticker": symbol,
                    "price": round(curr_price, 2),
                    "change_pct": round(change_pct, 2),
                    "volume": volume,
                    "avg_volume": avg_vol,
                    "market_cap": market_cap,
                    "float": float_shares,
                })
            except Exception:
                continue
        return results

    def fetch_polygon_historical_avg_volume(self, ticker: str, days: int = 10):
        if not self.api_key:
            return None
        if hasattr(self, "_avg_volume_cache") and ticker in self._avg_volume_cache:
            return self._avg_volume_cache[ticker]

        from datetime import datetime, timedelta
        try:
            from zoneinfo import ZoneInfo
            now_et = datetime.now(ZoneInfo("America/New_York"))
        except Exception:
            from datetime import timezone
            now_et = datetime.now(timezone(timedelta(hours=-5)))

        end_date = (now_et.date() - timedelta(days=1)).strftime("%Y-%m-%d")
        start_date = (now_et.date() - timedelta(days=days * 3)).strftime("%Y-%m-%d")
        url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{start_date}/{end_date}"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        params = {"adjusted": "true", "sort": "desc", "limit": 10}
        try:
            resp = self._get(url, headers=headers, params=params, timeout=10)
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                volumes = [bar.get("v") for bar in results if bar.get("v") is not None]
                if volumes:
                    avg_vol = float(sum(volumes) / len(volumes))
                    if hasattr(self, "_avg_volume_cache"):
                        self._avg_volume_cache[ticker] = avg_vol
                    return avg_vol
        except requests.exceptions.RequestException:
            pass

        if hasattr(self, "_avg_volume_cache"):
            self._avg_volume_cache[ticker] = None
        return None

    def fetch_polygon_ticker_details(self, ticker: str):
        if not self.api_key:
            return None
        url = f"https://api.polygon.io/v3/reference/tickers/{ticker}"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            resp = self._get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                return resp.json().get("results", {})
        except requests.exceptions.RequestException:
            pass
        return None

    def enrich_ticker(self, item):
        ticker = item.get("ticker")
        market_cap = item.get("market_cap")
        float_shares = item.get("float")

        # If fundamentals are not populated and we are using Polygon, fetch reference data
        if (market_cap is None or float_shares is None) and self.api_key and self.source == "polygon":
            details = self.fetch_polygon_ticker_details(ticker)
            if details:
                if market_cap is None:
                    market_cap = details.get("market_cap")
                if float_shares is None:
                    float_shares = details.get("free_float")

        # Normalize None or invalid values
        try:
            item["market_cap"] = float(market_cap) if market_cap is not None else None
        except (ValueError, TypeError):
            item["market_cap"] = None

        try:
            numeric_float = float(float_shares) if float_shares is not None else None
            item["float"] = numeric_float if numeric_float is not None and math.isfinite(numeric_float) and numeric_float > 0 else None
        except (ValueError, TypeError):
            item["float"] = None

        return item

    def run(self, demo=False, sort_by="volume", min_rvol=None):
        self.last_error = None
        self.last_status = "ok"
        self._avg_volume_cache = {}
        try:
            rvol_threshold = float(self.min_rvol if min_rvol is None else min_rvol)
        except (ValueError, TypeError):
            rvol_threshold = 5.0

        if demo:
            raw_data = DEMO_DATA
        elif self.source == "yfinance":
            raw_data = self.fetch_yfinance_data()
        else:
            raw_data = self.fetch_polygon_data()

        filtered = []
        for item in raw_data:
            price = item.get("price") or 0
            change_pct = item.get("change_pct") or 0
            current_volume = item.get("volume") or 0

            # Ensure avg_volume is calculated from historical daily volumes before applying RVOL gate
            avg_baseline_volume = item.get("avg_volume")
            ticker = item.get("ticker")
            attempted = item.get("avg_volume_attempted", False) or (
                hasattr(self, "_avg_volume_cache") and ticker in self._avg_volume_cache
            )
            if (
                not demo
                and avg_baseline_volume is None
                and not attempted
                and self.source == "polygon"
                and self.api_key
            ):
                if (2.00 <= price <= 10.00) and (change_pct >= 10.0) and (current_volume >= self.min_volume):
                    avg_baseline_volume = self.fetch_polygon_historical_avg_volume(ticker, days=10)
                    item["avg_volume"] = avg_baseline_volume
                    item["avg_volume_attempted"] = True

            if not isinstance(avg_baseline_volume, (int, float)) or not math.isfinite(avg_baseline_volume) or avg_baseline_volume <= 0:
                continue

            # Calculate Relative Volume multiplier
            rvol = current_volume / avg_baseline_volume if avg_baseline_volume > 0 else 0

            # Apply exact rules including price, change, volume, and 5x RVOL
            if (2.00 <= price <= 10.00) and (change_pct >= 10.0) and (current_volume >= self.min_volume) and (rvol >= rvol_threshold):
                enriched = self.enrich_ticker(item)

                mcap = enriched.get("market_cap")
                fl = enriched.get("float")

                # Fundamental Rules: Float <= 10M, Market Cap <= $100M
                # Candidates with unknown fundamentals are excluded
                if isinstance(mcap, (int, float)) and math.isfinite(mcap) and mcap > 0 and (fl is not None or self.float_mode == "discovery"):
                    if (fl is None or fl <= 10000000) and mcap <= 100000000:
                        filtered.append({
                            "Ticker": enriched["ticker"],
                            "Price": enriched["price"],
                            "Today's Change %": enriched["change_pct"],
                            "Volume": enriched["volume"],
                            "RVOL": rvol,
                            "Market Cap ($M)": round(enriched['market_cap'] / 1_000_000, 2),
                            "Float (M)": round(enriched['float'] / 1_000_000, 2) if enriched['float'] is not None else "N/A",
                            "Float Status": "verified" if enriched['float'] is not None else "unverified",
                            "RVOL Type": "daily",
                            "_raw_volume": enriched['volume'],
                            "_raw_change": enriched['change_pct'],
                            "_raw_rvol": rvol,
                        })

        df = pd.DataFrame(filtered)
        if not df.empty:
            if sort_by == "change":
                sort_col = "_raw_change"
            elif sort_by == "rvol":
                sort_col = "_raw_rvol"
            else:
                sort_col = "_raw_volume"
            df = df.sort_values(by=sort_col, ascending=False)
            df = df.drop(columns=["_raw_volume", "_raw_change", "_raw_rvol"])

        return df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Midday Momentum Stock Screener")
    parser.add_argument("--demo", action="store_true", help="Run with mock midday market data")
    parser.add_argument("--source", type=str, default="polygon", choices=["polygon", "yfinance"], help="Data engine source")
    parser.add_argument("--min-volume", type=int, default=500000, help="Minimum active intraday volume")
    parser.add_argument("--min-rvol", type=float, default=5.0, help="Minimum Relative Volume (RVOL) multiplier (default: 5.0x)")
    parser.add_argument("--float-mode", choices=["strict", "discovery"], default="strict", help="Strictly require public float or include unknown float flagged")
    parser.add_argument("--sort-by", type=str, default="volume", choices=["volume", "change", "rvol"], help="Sort order: volume, change, or rvol")
    parser.add_argument(
        "-k",
        "--api-key",
        type=str,
        default=os.getenv("MASSIVE_API_KEY") or os.getenv("POLYGON_API_KEY") or "",
        help="Polygon API Key",
    )

    args = parser.parse_args()

    screener = MiddayScreener(
        api_key=args.api_key,
        min_volume=args.min_volume,
        source=args.source,
        min_rvol=args.min_rvol,
        float_mode=args.float_mode,
    )
    df_result = screener.run(demo=args.demo, sort_by=args.sort_by)

    print("\n=== MIDDAY MOMENTUM WATCHLIST ===")
    if screener.last_error and not args.demo:
        print(f"[ERROR] Live scan failed: {screener.last_error}")
    elif not df_result.empty:
        display = df_result.copy()
        display["Price"] = display["Price"].map(lambda v: f"${v:,.2f}")
        display["Today's Change %"] = display["Today's Change %"].map(lambda v: f"{v:+.2f}%")
        display["Volume"] = display["Volume"].map(lambda v: f"{int(v):,}")
        display["RVOL"] = display["RVOL"].map(lambda v: f"{v:.1f}x")
        print(display.to_string(index=False))
    else:
        print("No stocks currently match the exact midday momentum criteria.")
    print("")

