#!/usr/bin/env python3
"""
Small-Cap Momentum Stock Screener.

Default Engine: Yahoo Finance (yfinance) — 100% Free, NO API key required.

Rules:
  - Price: $2.00 to $10.00
  - Volume: >= 500,000 shares
  - Float: <= 10,000,000 shares (10M)
  - Market Cap: <= $100M ($100,000,000)
  - Gap / Gain: >= +5.0%

Usage:
  python screener.py
"""

import sys
from yfinance_screener import main

if __name__ == "__main__":
    main()

