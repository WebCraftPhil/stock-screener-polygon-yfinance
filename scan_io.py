"""Shared helpers for watchlists and opt-in scan output."""

from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9-]{0,9}$")


def load_watchlist(path: str | Path) -> tuple[list[str], list[str]]:
    """Read one symbol per line (or comma-separated) and return valid, invalid values."""
    symbols: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.reader(stream):
            for value in row:
                symbol = value.strip().upper()
                if not symbol or symbol.startswith("#"):
                    continue
                if not SYMBOL_RE.fullmatch(symbol):
                    invalid.append(value.strip())
                elif symbol not in seen:
                    seen.add(symbol)
                    symbols.append(symbol)
    return symbols, invalid


def scan_metadata(provider: str, filters: dict, *, status: str = "ok", message: str | None = None) -> dict:
    metadata = {
        "Run Timestamp (UTC)": datetime.now(timezone.utc).isoformat(),
        "Provider": provider,
        "Scan Status": status,
        "Filters": "; ".join(f"{key}={value}" for key, value in sorted(filters.items())),
    }
    if message:
        metadata["Scan Message"] = message
    return metadata


def write_scan(df: pd.DataFrame, path: str | Path, metadata: dict, *, append: bool = False) -> None:
    """Write a scan CSV, optionally appending rows and metadata to history."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    output = df.copy()
    for key, value in metadata.items():
        output.insert(0, key, value)
    if append and path.exists():
        prior = pd.read_csv(path)
        output = pd.concat([prior, output], ignore_index=True, sort=False)
    output.to_csv(path, index=False)


def missing_symbols(requested: Iterable[str], returned: Iterable[str]) -> list[str]:
    returned_set = {str(symbol).upper() for symbol in returned}
    return [symbol for symbol in requested if symbol not in returned_set]
