"""
Unit tests for Small-Cap Momentum Screener (Polygon.io).
"""

import pytest
import pandas as pd
from unittest.mock import Mock, patch
from requests.exceptions import Timeout, ConnectionError

from momentum_screener import (
    PolygonScreener,
    get_mock_snapshot_data,
    get_mock_ticker_details,
    print_screener_results,
    run_demo,
)


@pytest.fixture
def screener():
    """Create a PolygonScreener instance with default rules."""
    return PolygonScreener(api_key="TEST_KEY")


def test_api_key_validation():
    """Ensure missing or empty API keys raise ValueError."""
    screener_no_key = PolygonScreener(api_key=None)
    with patch.dict("os.environ", {}, clear=True):
        screener_no_key.api_key = None
        with pytest.raises(ValueError, match="API Key is required"):
            screener_no_key.fetch_all_tickers_snapshot()


def test_massive_api_key_env_var():
    """Ensure MASSIVE_API_KEY is detected when set in environment."""
    with patch.dict("os.environ", {"MASSIVE_API_KEY": "massive_key_123"}, clear=True):
        screener_massive = PolygonScreener(api_key=None)
        assert screener_massive.api_key == "massive_key_123"


def test_snapshot_filtering_exact_rules(screener):
    """
    Test that snapshot filtering correctly applies:
      - Price: $2.00 to $10.00
      - Volume: >= 500,000
      - Gap: >= +5.0%
    """
    raw_snapshot = [
        # Match: $5.00 price, 1M vol, +10% gap
        {
            "ticker": "GOOD1",
            "day": {"c": 5.00, "v": 1_000_000},
            "prevDay": {"c": 4.545},  # ~+10.01%
        },
        # Match boundary: exactly $2.00 price, 500,000 vol, +5% gap
        {
            "ticker": "BOUND_MIN",
            "day": {"c": 2.00, "v": 500_000},
            "prevDay": {"c": 1.9047},  # ~+5.00%
        },
        # Match boundary: exactly $10.00 price, 800,000 vol, +5.5% gap
        {
            "ticker": "BOUND_MAX",
            "day": {"c": 10.00, "v": 800_000},
            "prevDay": {"c": 9.478},  # ~+5.5%
        },
        # Fail: Price too low ($1.99)
        {
            "ticker": "FAIL_LOW_PRICE",
            "day": {"c": 1.99, "v": 2_000_000},
            "prevDay": {"c": 1.50},
        },
        # Fail: Price too high ($10.01)
        {
            "ticker": "FAIL_HIGH_PRICE",
            "day": {"c": 10.01, "v": 1_000_000},
            "prevDay": {"c": 9.00},
        },
        # Fail: Volume too low (499,999)
        {
            "ticker": "FAIL_LOW_VOL",
            "day": {"c": 4.00, "v": 499_999},
            "prevDay": {"c": 3.50},
        },
        # Fail: Gap too low (+4.9%)
        {
            "ticker": "FAIL_LOW_GAP",
            "day": {"c": 5.00, "v": 600_000},
            "prevDay": {"c": 4.77},  # +4.82%
        },
    ]

    candidates = screener.filter_snapshot_candidates(raw_snapshot)
    candidate_tickers = [c["ticker"] for c in candidates]

    assert "GOOD1" in candidate_tickers
    assert "BOUND_MIN" in candidate_tickers
    assert "BOUND_MAX" in candidate_tickers
    assert "FAIL_LOW_PRICE" not in candidate_tickers
    assert "FAIL_HIGH_PRICE" not in candidate_tickers
    assert "FAIL_LOW_VOL" not in candidate_tickers
    assert "FAIL_LOW_GAP" not in candidate_tickers


def test_fundamentals_filtering_market_cap_and_float(screener):
    """
    Test that reference enrichment filters out:
      - Market Cap > $100M
      - Float > 10,000,000 shares
    """
    candidates = [
        {"ticker": "PASS_ALL", "price": 4.00, "volume": 1_000_000, "gap_pct": 12.0},
        {"ticker": "FAIL_MCAP", "price": 8.00, "volume": 900_000, "gap_pct": 8.0},
        {"ticker": "FAIL_FLOAT", "price": 3.00, "volume": 700_000, "gap_pct": 15.0},
    ]

    def mock_fetch_details(ticker):
        if ticker == "PASS_ALL":
            return {
                "market_cap": 25_000_000,
                "share_class_shares_outstanding": 6_250_000,
            }
        elif ticker == "FAIL_MCAP":
            return {
                "market_cap": 150_000_000,  # Exceeds $100M
                "share_class_shares_outstanding": 8_000_000,
            }
        elif ticker == "FAIL_FLOAT":
            return {
                "market_cap": 36_000_000,
                "share_class_shares_outstanding": 12_000_000,  # Exceeds 10M
            }
        return None

    screener.fetch_ticker_details = mock_fetch_details
    results = screener.enrich_and_filter_fundamentals(candidates)

    result_tickers = [r["Ticker"] for r in results]
    assert result_tickers == ["PASS_ALL"]
    assert results[0]["Market Cap ($M)"] == 25.0
    assert results[0]["Est. Float (M)"] == 6.25


def test_sorting_by_volume_descending(screener):
    """Ensure the final scan results are sorted by volume in descending order."""
    screener.fetch_all_tickers_snapshot = get_mock_snapshot_data
    screener.fetch_ticker_details = get_mock_ticker_details

    df = screener.scan()

    volumes = df["Volume"].tolist()
    assert volumes == sorted(volumes, reverse=True)
    assert len(df) == 3
    assert df.iloc[0]["Ticker"] == "RUNR"  # 2,450,000 vol
    assert df.iloc[1]["Ticker"] == "MOMN"  # 1,850,000 vol
    assert df.iloc[2]["Ticker"] == "ROCK"  # 620,000 vol


def test_formatted_dataframe_columns_and_values():
    """Ensure output DataFrame has exact requested columns and formatting."""
    raw_df = pd.DataFrame([
        {
            "Ticker": "ABCD",
            "Price": 4.50,
            "Gap %": 14.523,
            "Volume": 1850000,
            "Market Cap ($M)": 25.0,
            "Est. Float (M)": 7.2,
        }
    ])

    formatted = PolygonScreener.format_dataframe_for_display(raw_df)

    expected_cols = ["Ticker", "Price", "Gap %", "Volume", "Market Cap ($M)", "Est. Float (M)"]
    assert list(formatted.columns) == expected_cols

    row = formatted.iloc[0]
    assert row["Ticker"] == "ABCD"
    assert row["Price"] == "$4.50"
    assert row["Gap %"] == "+14.52%"
    assert row["Volume"] == "1,850,000"
    assert row["Market Cap ($M)"] == "$25.00"
    assert row["Est. Float (M)"] == "7.20"


def test_http_error_handling(screener):
    """Test 401 and 403 HTTP status code handling."""
    mock_resp_401 = Mock()
    mock_resp_401.status_code = 401

    with patch.object(screener.session, "get", return_value=mock_resp_401):
        with pytest.raises(PermissionError, match="401 Unauthorized"):
            screener.fetch_all_tickers_snapshot()

    mock_resp_403 = Mock()
    mock_resp_403.status_code = 403

    with patch.object(screener.session, "get", return_value=mock_resp_403):
        with pytest.raises(PermissionError, match="403 Forbidden"):
            screener.fetch_all_tickers_snapshot()


def test_header_only_authentication(screener):
    """Verify that requests use the Authorization header without apiKey query params."""
    mock_resp = Mock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"tickers": []}

    with patch.object(screener.session, "get", return_value=mock_resp) as mock_get:
        screener.fetch_all_tickers_snapshot()
        mock_get.assert_called_once_with(
            f"{screener.BASE_URL}/v2/snapshot/locale/us/markets/stocks/tickers",
            timeout=screener.timeout,
        )
        assert screener.session.headers.get("Authorization") == f"Bearer {screener.api_key}"

    mock_resp_details = Mock()
    mock_resp_details.status_code = 200
    mock_resp_details.json.return_value = {"results": {"market_cap": 10_000_000}}

    with patch.object(screener.session, "get", return_value=mock_resp_details) as mock_get:
        screener.fetch_ticker_details("AAPL")
        mock_get.assert_called_once_with(
            f"{screener.BASE_URL}/v3/reference/tickers/AAPL",
            timeout=screener.timeout,
        )


def test_print_screener_results_rules_header(capsys):
    """Ensure print_screener_results displays active screener rules in the header."""
    custom_screener = PolygonScreener(
        api_key="TEST_KEY",
        min_price=3.50,
        max_price=8.50,
        min_volume=1_000_000,
        max_float=8_000_000,
        max_market_cap=80_000_000,
        min_gap_pct=10.0,
    )
    df = pd.DataFrame(
        columns=["Ticker", "Price", "Gap %", "Volume", "Market Cap ($M)", "Est. Float (M)"]
    )
    print_screener_results(df, screener=custom_screener)
    captured = capsys.readouterr()
    assert "Rules: Price: $3.5-$8.5 | Vol: >=1M | Float: <=8M | MktCap: <=$80M | Gap: >=+10%" in captured.out

    # Default / fallback header when screener is None
    print_screener_results(df, screener=None)
    captured_default = capsys.readouterr()
    assert "Rules: Price: $2-$10 | Vol: >=500K | Float: <=10M | MktCap: <=$100M | Gap: >=+5%" in captured_default.out


def test_run_demo_executes_shared_pipeline(capsys):
    """Ensure run_demo executes without error and prints expected demo results."""
    run_demo()
    captured = capsys.readouterr()
    assert "SMALL-CAP MOMENTUM SCREENER RESULTS" in captured.out
    assert "Total matching stocks: 3" in captured.out


def test_yfinance_screener_rules():
    """Test YFinanceScreener filtering rules on mock quotes and fundamentals."""
    from yfinance_screener import YFinanceScreener

    yf_screener = YFinanceScreener()

    mock_quotes = [
        {"symbol": "WIN1", "regularMarketPrice": 5.0, "regularMarketChangePercent": 15.0, "regularMarketVolume": 1_000_000, "marketCap": 25_000_000},
        {"symbol": "FAIL_HIGH_MCAP", "regularMarketPrice": 4.0, "regularMarketChangePercent": 10.0, "regularMarketVolume": 800_000, "marketCap": 150_000_000},
        {"symbol": "FAIL_LOW_VOL", "regularMarketPrice": 3.0, "regularMarketChangePercent": 20.0, "regularMarketVolume": 100_000, "marketCap": 10_000_000},
        {"symbol": "NON_US.TO", "regularMarketPrice": 4.0, "regularMarketChangePercent": 12.0, "regularMarketVolume": 900_000, "marketCap": 20_000_000},
    ]

    mock_fundamentals = {
        "WIN1": {"float_shares": 5_000_000, "market_cap": 25_000_000},
        "FAIL_HIGH_MCAP": {"float_shares": 6_000_000, "market_cap": 150_000_000},
        "FAIL_LOW_VOL": {"float_shares": 2_000_000, "market_cap": 10_000_000},
    }

    yf_screener.fetch_candidates = lambda: mock_quotes
    yf_screener.get_ticker_float_and_mcap = lambda sym: mock_fundamentals.get(sym, {"float_shares": None, "market_cap": None})

    df = yf_screener.scan()
    assert len(df) == 1
    assert df.iloc[0]["Ticker"] == "WIN1"
    assert df.iloc[0]["Price"] == 5.0
    assert df.iloc[0]["Est. Float (M)"] == 5.0
    assert df.iloc[0]["Market Cap ($M)"] == 25.0

