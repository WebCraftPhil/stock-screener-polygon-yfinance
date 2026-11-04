import pandas as pd

from scan_io import load_watchlist, missing_symbols, scan_metadata, write_scan


def test_watchlist_validates_deduplicates_and_ignores_comments(tmp_path):
    path = tmp_path / "watchlist.txt"
    path.write_text("aapl\nMSFT, AAPL\n# note\nBAD.TO\n", encoding="utf-8")

    symbols, invalid = load_watchlist(path)

    assert symbols == ["AAPL", "MSFT"]
    assert invalid == ["BAD.TO"]
    assert missing_symbols(symbols, ["MSFT"]) == ["AAPL"]


def test_export_and_history_include_scan_metadata_and_append(tmp_path):
    path = tmp_path / "history.csv"
    rows = pd.DataFrame([{"Ticker": "ABC", "RVOL": 5.2}])
    metadata = scan_metadata("yfinance", {"min_rvol": 5})

    write_scan(rows, path, metadata, append=True)
    write_scan(rows.assign(Ticker="XYZ"), path, metadata, append=True)

    saved = pd.read_csv(path)
    assert saved["Ticker"].tolist() == ["ABC", "XYZ"]
    assert saved["Provider"].tolist() == ["yfinance", "yfinance"]
    assert saved["Filters"].str.contains("min_rvol=5").all()
    assert saved["Run Timestamp (UTC)"].notna().all()
