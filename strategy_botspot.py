#!/usr/bin/env python3
"""
Strategy Description:
This strategy is loosely based on Ray Dalio's All Weather Portfolio.
It owns a diversified portfolio of leveraged ETFs and rebalances when drift exceeds a threshold.
"""

from datetime import datetime
from decimal import Decimal

from lumibot.entities import TradingFee
from lumibot.entities.asset import Asset
from lumibot.strategies.strategy import Strategy
from lumibot.traders import Trader
from lumibot.credentials import IS_BACKTESTING


class StockDiversifiedLeverage(Strategy):
    parameters = {
        "portfolio": [
            {"symbol": "TQQQ", "weight": 0.20},   # 3x Nasdaq 100
            {"symbol": "UPRO", "weight": 0.20},   # 3x S&P 500
            {"symbol": "UDOW", "weight": 0.10},   # 3x Dow Jones
            {"symbol": "TMF", "weight": 0.25},    # 3x 20+ Year Treasuries
            {"symbol": "UGL", "weight": 0.10},    # 2x Gold
            {"symbol": "DIG", "weight": 0.149},   # 2x Oil & Gas
        ],
        "drift_threshold": 0.26,
    }

    def initialize(self):
        # Run once at start: set daily iterations and allow 1 minute before closing
        self.sleeptime = "1D"
        self.minutes_before_closing = 1

    def on_trading_iteration(self):
        # Called every day: calculate total drift and decide to rebalance
        portfolio = self.parameters["portfolio"]
        drift = self.calc_portfolio_drift(portfolio)

        if drift > self.parameters["drift_threshold"]:
            self.log_message(f"Drift is {drift:.2f}, rebalancing portfolio.", color="green")
            # Mark the rebalance event on the chart
            self.add_marker("Rebalance", self.portfolio_value, color="blue", symbol="star", size=8)
            self.rebalance_portfolio(portfolio)
        else:
            self.log_message(f"Drift is only {drift:.2f}, no rebalance needed.", color="yellow")

        # Draw a line of portfolio value for visualization
        self.add_line("Portfolio Value", self.portfolio_value, color="black", width=2)

    def calc_portfolio_drift(self, portfolio, tradeable_portfolio_pct=1):
        total_drift = Decimal(0)
        tradeable_value = Decimal(self.portfolio_value * tradeable_portfolio_pct)

        for item in portfolio:
            symbol = item["symbol"]
            target_weight = Decimal(str(item["weight"]))
            price = self.get_last_price(symbol)
            if price is None:
                self.log_message(f"No price for {symbol}, skipping.", color="red")
                continue

            # Calculate current holding value
            qty = Decimal(str(self.get_asset_potential_total(symbol)))
            value = qty * Decimal(price)
            current_weight = (value / tradeable_value) if tradeable_value > 0 else Decimal(0)
            drift = abs(target_weight - current_weight)
            self.log_message(
                f"{symbol}: current {current_weight:.2f}, target {target_weight:.2f}, drift {drift * 100:.2f}%"
            )
            total_drift += drift

        drift_float = float(total_drift)
        self.log_message(f"Total portfolio drift: {drift_float:.2f}")
        return drift_float

    def rebalance_portfolio(self, portfolio):
        orders = []
        # Build buy / sell orders to hit target weights
        for item in portfolio:
            symbol = item["symbol"]
            target_weight = item["weight"]
            price = self.get_last_price(symbol)
            if price is None:
                self.log_message(f"No price for {symbol}, skipping.", color="red")
                continue

            current_pos = self.get_position(symbol)
            current_qty = float(current_pos.quantity) if current_pos else 0.0
            target_value = self.portfolio_value * target_weight
            target_qty = int(target_value // price)
            diff = target_qty - current_qty

            # Skip tiny adjustments under 1%
            pct = (abs(diff) * price) / self.portfolio_value if self.portfolio_value else 0
            if pct < 0.01:
                continue

            side = "buy" if diff > 0 else "sell"
            self.log_message(
                f"{side.title()} {abs(diff)} of {symbol} (@{price:.2f}) to reach {target_weight * 100:.1f}%",
                color="blue",
            )
            # DAY orders: Alpaca rejects fractional GTC orders, and daily rebalances do not need GTC
            orders.append(self.create_order(symbol, abs(diff), side, time_in_force="day"))

        # Also clear out any assets not in portfolio
        orders.extend(self.sell_orders_for_assets_not_in_portfolio(portfolio))

        # Preserve execution order: sales free cash before buys
        for order in orders:
            if order.side == "sell":
                self.submit_order(order)

        # Settlement wait before placing buys
        self.sleep(15)

        for order in orders:
            if order.side == "buy":
                self.submit_order(order)
            self.sleep(1)

    def sell_orders_for_assets_not_in_portfolio(self, portfolio):
        orders = []
        desired = {item["symbol"] for item in portfolio}
        for pos in self.get_positions():
            asset = pos.asset
            # Skip cash
            if asset == self.quote_asset:
                continue
            sym = asset.symbol
            if sym not in desired:
                qty = abs(pos.quantity)
                side = "sell" if pos.quantity > 0 else "buy"
                self.log_message(f"Clearing {sym} ({side} {qty})", color="red")
                orders.append(self.create_order(asset, qty, side, time_in_force="day"))
        return orders


if __name__ == "__main__":
    if IS_BACKTESTING:
        # Backtesting setup with Yahoo data and SPY benchmark
        from lumibot.backtesting import YahooDataBacktesting

        fee = TradingFee(percent_fee=0.001)
        StockDiversifiedLeverage.backtest(
            datasource_class=YahooDataBacktesting,
            benchmark_asset=Asset("SPY", Asset.AssetType.STOCK),
            buy_trading_fees=[fee],
            sell_trading_fees=[fee],
            quote_asset=Asset("USD", Asset.AssetType.FOREX),
        )
    else:
        # Live trading: add strategy with USD quote asset
        trader = Trader()
        strat = StockDiversifiedLeverage(
            quote_asset=Asset("USD", Asset.AssetType.FOREX),
        )
        trader.add_strategy(strat)
        trader.run_all()
