#!/usr/bin/env python3
"""
Backtest Engine for Leveraged All-Weather Portfolio (strategy_botspot.py)

Models the exact mechanics of the strategy:
  - Assets: TQQQ (20%), UPRO (20%), UDOW (10%), TMF (25%), UGL (10%), DIG (14.9%)
  - Daily tracking and portfolio drift evaluation
  - Rebalance triggered when total drift > threshold (default: 26%)
  - 0.1% transaction fee on rebalanced volume
  - Compares against SPY benchmark

Usage:
  python backtest_leveraged_allweather.py
  python backtest_leveraged_allweather.py --years 5 --drift 0.26
"""

import argparse
import sys
import warnings
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

# Suppress library deprecation warnings for clean output
warnings.filterwarnings("ignore")

# Target allocation from strategy_botspot.py
TARGET_PORTFOLIO = [
    {"symbol": "TQQQ", "weight": 0.200},  # 3x Nasdaq 100
    {"symbol": "UPRO", "weight": 0.200},  # 3x S&P 500
    {"symbol": "UDOW", "weight": 0.100},  # 3x Dow Jones
    {"symbol": "TMF",  "weight": 0.250},  # 3x 20+ Year Treasuries
    {"symbol": "UGL",  "weight": 0.100},  # 2x Gold
    {"symbol": "DIG",  "weight": 0.149},  # 2x Oil & Gas
]
# Remaining ~0.001 allocated as cash buffer


def fetch_historical_prices(symbols: List[str], start_date: str, end_date: str) -> pd.DataFrame:
    """Download daily adjusted close prices for all portfolio assets and SPY benchmark."""
    all_symbols = list(set(symbols + ["SPY"]))
    print(f"[*] Downloading daily historical data for {', '.join(all_symbols)} from {start_date} to {end_date}...")

    data = yf.download(all_symbols, start=start_date, end=end_date, progress=False)

    if isinstance(data.columns, pd.MultiIndex):
        if "Close" in data.columns.levels[0]:
            prices = data["Close"]
        elif "Adj Close" in data.columns.levels[0]:
            prices = data["Adj Close"]
        else:
            prices = data.xs(data.columns.levels[0][0], axis=1)
    else:
        prices = data

    # Drop symbols with missing data or forward-fill
    prices = prices.ffill().dropna()
    return prices


def run_simulation(
    prices: pd.DataFrame,
    target_weights: Dict[str, float],
    drift_threshold: float = 0.26,
    initial_capital: float = 100_000.0,
    fee_pct: float = 0.001,
) -> Tuple[pd.DataFrame, List[Dict]]:
    """Simulate daily portfolio tracking, drift evaluation, and rebalancing."""
    dates = prices.index
    symbols = list(target_weights.keys())

    # State variables
    portfolio_value = initial_capital
    holdings = {}  # symbol -> shares
    rebalance_log = []
    daily_records = []

    # Initial allocation on Day 0
    first_prices = prices.iloc[0]
    for sym, weight in target_weights.items():
        val = initial_capital * weight
        shares = val / first_prices[sym]
        holdings[sym] = shares

    # Benchmark initial shares
    spy_start_price = prices["SPY"].iloc[0]
    spy_shares = initial_capital / spy_start_price

    for i, date in enumerate(dates):
        current_prices = prices.loc[date]

        # Calculate current asset values and total portfolio value
        asset_values = {sym: holdings[sym] * current_prices[sym] for sym in symbols}
        portfolio_value = sum(asset_values.values())
        spy_value = spy_shares * current_prices["SPY"]

        # Calculate current weights and total drift
        current_weights = {sym: asset_values[sym] / portfolio_value for sym in symbols}
        total_drift = sum(abs(current_weights[sym] - target_weights[sym]) for sym in symbols)

        rebalanced_today = False
        rebalance_cost = 0.0

        # Check rebalance condition
        if total_drift > drift_threshold and i > 0:
            rebalanced_today = True
            # Rebalance to target weights
            turnover_value = 0.0
            for sym, tgt_weight in target_weights.items():
                target_val = portfolio_value * tgt_weight
                diff_val = abs(target_val - asset_values[sym])
                # Skip tiny adjustments under 1% of portfolio
                if diff_val / portfolio_value >= 0.01:
                    turnover_value += diff_val
                    holdings[sym] = target_val / current_prices[sym]

            # Deduct fee on turnover
            rebalance_cost = turnover_value * fee_pct
            portfolio_value -= rebalance_cost

            rebalance_log.append({
                "Date": date.strftime("%Y-%m-%d"),
                "Portfolio Value": portfolio_value,
                "Drift": total_drift,
                "Turnover ($)": turnover_value,
                "Fee ($)": rebalance_cost,
            })

            # Recalculate weights after rebalance
            current_weights = {sym: (holdings[sym] * current_prices[sym]) / portfolio_value for sym in symbols}
            total_drift = sum(abs(current_weights[sym] - target_weights[sym]) for sym in symbols)

        daily_records.append({
            "Date": date,
            "Portfolio Value": portfolio_value,
            "SPY Value": spy_value,
            "Total Drift": total_drift,
            "Rebalanced": rebalanced_today,
            "Fee": rebalance_cost,
        })

    df_daily = pd.DataFrame(daily_records).set_index("Date")
    return df_daily, rebalance_log


def compute_performance_metrics(df_daily: pd.DataFrame, initial_capital: float = 100_000.0) -> Dict:
    """Calculate CAGR, Max Drawdown, Sharpe, Sortino, and volatility."""
    port_series = df_daily["Portfolio Value"]
    spy_series = df_daily["SPY Value"]

    total_return_strat = (port_series.iloc[-1] - initial_capital) / initial_capital
    total_return_spy = (spy_series.iloc[-1] - initial_capital) / initial_capital

    days = (port_series.index[-1] - port_series.index[0]).days
    years = days / 365.25

    cagr_strat = (port_series.iloc[-1] / initial_capital) ** (1 / years) - 1 if years > 0 else 0
    cagr_spy = (spy_series.iloc[-1] / initial_capital) ** (1 / years) - 1 if years > 0 else 0

    # Daily returns
    port_returns = port_series.pct_change().dropna()
    spy_returns = spy_series.pct_change().dropna()

    # Drawdown
    cum_max_strat = port_series.cummax()
    drawdowns_strat = (port_series - cum_max_strat) / cum_max_strat
    max_dd_strat = drawdowns_strat.min()

    cum_max_spy = spy_series.cummax()
    drawdowns_spy = (spy_series - cum_max_spy) / cum_max_spy
    max_dd_spy = drawdowns_spy.min()

    # Sharpe ratio (assuming 3% risk-free rate)
    rf_daily = 0.03 / 252
    excess_returns_strat = port_returns - rf_daily
    excess_returns_spy = spy_returns - rf_daily

    sharpe_strat = (excess_returns_strat.mean() / excess_returns_strat.std()) * np.sqrt(252) if port_returns.std() > 0 else 0
    sharpe_spy = (excess_returns_spy.mean() / excess_returns_spy.std()) * np.sqrt(252) if spy_returns.std() > 0 else 0

    # Downside deviation for Sortino
    downside_returns = port_returns[port_returns < 0]
    sortino_strat = (excess_returns_strat.mean() / downside_returns.std()) * np.sqrt(252) if len(downside_returns) > 0 and downside_returns.std() > 0 else 0

    volatility_strat = port_returns.std() * np.sqrt(252)
    volatility_spy = spy_returns.std() * np.sqrt(252)

    return {
        "Years": years,
        "Start Date": port_series.index[0].strftime("%Y-%m-%d"),
        "End Date": port_series.index[-1].strftime("%Y-%m-%d"),
        "Initial Capital": initial_capital,
        "Final Strategy Value": port_series.iloc[-1],
        "Final SPY Value": spy_series.iloc[-1],
        "Strategy Total Return": total_return_strat,
        "SPY Total Return": total_return_spy,
        "Strategy CAGR": cagr_strat,
        "SPY CAGR": cagr_spy,
        "Strategy Max Drawdown": max_dd_strat,
        "SPY Max Drawdown": max_dd_spy,
        "Strategy Annualized Volatility": volatility_strat,
        "SPY Annualized Volatility": volatility_spy,
        "Strategy Sharpe": sharpe_strat,
        "SPY Sharpe": sharpe_spy,
        "Strategy Sortino": sortino_strat,
    }


def compute_annual_returns(df_daily: pd.DataFrame) -> pd.DataFrame:
    """Breakdown returns year-by-year."""
    port_series = df_daily["Portfolio Value"]
    spy_series = df_daily["SPY Value"]

    years = sorted(list(set(df_daily.index.year)))
    records = []
    for yr in years:
        sub_port = port_series[port_series.index.year == yr]
        sub_spy = spy_series[spy_series.index.year == yr]
        if len(sub_port) < 2:
            continue
        p_ret = (sub_port.iloc[-1] - sub_port.iloc[0]) / sub_port.iloc[0]
        s_ret = (sub_spy.iloc[-1] - sub_spy.iloc[0]) / sub_spy.iloc[0]

        sub_cum = sub_port.cummax()
        sub_dd = ((sub_port - sub_cum) / sub_cum).min()

        records.append({
            "Year": yr,
            "Strategy Return": f"{p_ret * 100:+.2f}%",
            "SPY Return": f"{s_ret * 100:+.2f}%",
            "Strategy Max DD": f"{sub_dd * 100:.2f}%",
        })

    return pd.DataFrame(records)


def print_report(metrics: Dict, rebalance_log: List[Dict], annual_df: pd.DataFrame, drift_threshold: float):
    """Print comprehensive performance comparison to terminal."""
    print("\n" + "=" * 80)
    print(" " * 18 + "LEVERAGED ALL-WEATHER STRATEGY BACKTEST")
    print("=" * 80)
    print(f"Period: {metrics['Start Date']} to {metrics['End Date']} ({metrics['Years']:.1f} years)")
    print(f"Starting Capital: ${metrics['Initial Capital']:,.2f}  |  Drift Threshold: {drift_threshold * 100:.1f}%")
    print("Portfolio: TQQQ 20% | UPRO 20% | UDOW 10% | TMF 25% | UGL 10% | DIG 14.9%")
    print("-" * 80)

    # Core Comparison Table
    print(f"{'Metric':<30} | {'Strategy (3x All-Weather)':<24} | {'SPY Benchmark':<18}")
    print("-" * 80)
    print(f"{'Final Portfolio Value':<30} | ${metrics['Final Strategy Value']:>22,.2f} | ${metrics['Final SPY Value']:>16,.2f}")
    print(f"{'Total Return':<30} | {metrics['Strategy Total Return'] * 100:>23.2f}% | {metrics['SPY Total Return'] * 100:>17.2f}%")
    print(f"{'CAGR (Annualized Return)':<30} | {metrics['Strategy CAGR'] * 100:>23.2f}% | {metrics['SPY CAGR'] * 100:>17.2f}%")
    print(f"{'Maximum Drawdown':<30} | {metrics['Strategy Max Drawdown'] * 100:>23.2f}% | {metrics['SPY Max Drawdown'] * 100:>17.2f}%")
    print(f"{'Annualized Volatility':<30} | {metrics['Strategy Annualized Volatility'] * 100:>23.2f}% | {metrics['SPY Annualized Volatility'] * 100:>17.2f}%")
    print(f"{'Sharpe Ratio (Rf=3%)':<30} | {metrics['Strategy Sharpe']:>24.2f} | {metrics['SPY Sharpe']:>18.2f}")
    print(f"{'Sortino Ratio':<30} | {metrics['Strategy Sortino']:>24.2f} | {'N/A':>18}")
    print(f"{'Rebalances Triggered':<30} | {len(rebalance_log):>24} | {'0':>18}")
    print("-" * 80)

    # Year by year breakdown
    print("\n" + "-" * 40 + " ANNUAL BREAKDOWN " + "-" * 40)
    print(annual_df.to_string(index=False))

    # Rebalance event log summary
    print("\n" + "-" * 40 + " REBALANCE EVENTS " + "-" * 40)
    if rebalance_log:
        df_rebal = pd.DataFrame(rebalance_log)
        df_rebal["Portfolio Value"] = df_rebal["Portfolio Value"].apply(lambda v: f"${v:,.2f}")
        df_rebal["Drift"] = df_rebal["Drift"].apply(lambda d: f"{d * 100:.1f}%")
        df_rebal["Turnover ($)"] = df_rebal["Turnover ($)"].apply(lambda t: f"${t:,.2f}")
        df_rebal["Fee ($)"] = df_rebal["Fee ($)"].apply(lambda f: f"${f:,.2f}")
        print(df_rebal.head(10).to_string(index=False))
        if len(rebalance_log) > 10:
            print(f"... and {len(rebalance_log) - 10} more rebalance events.")
    else:
        print("No rebalances triggered during this timeframe.")

    print("=" * 80 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Backtest Leveraged All-Weather Portfolio Strategy")
    parser.add_argument("--years", type=float, default=5.0, help="Years of historical data to backtest (default: 5.0)")
    parser.add_argument("--drift", type=float, default=0.26, help="Drift threshold to trigger rebalance (default: 0.26)")
    parser.add_argument("--capital", type=float, default=100_000.0, help="Initial capital (default: $100,000)")
    parser.add_argument("--fee", type=float, default=0.001, help="Transaction fee rate (default: 0.001 / 0.1%)")

    args = parser.parse_args()

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=int(args.years * 365.25))).strftime("%Y-%m-%d")

    target_weights = {item["symbol"]: item["weight"] for item in TARGET_PORTFOLIO}
    symbols = list(target_weights.keys())

    prices = fetch_historical_prices(symbols, start_date, end_date)
    if prices.empty:
        print("[!] No price data downloaded. Exiting.")
        sys.exit(1)

    df_daily, rebalance_log = run_simulation(
        prices=prices,
        target_weights=target_weights,
        drift_threshold=args.drift,
        initial_capital=args.capital,
        fee_pct=args.fee,
    )

    metrics = compute_performance_metrics(df_daily, initial_capital=args.capital)
    annual_df = compute_annual_returns(df_daily)
    print_report(metrics, rebalance_log, annual_df, drift_threshold=args.drift)


if __name__ == "__main__":
    main()
