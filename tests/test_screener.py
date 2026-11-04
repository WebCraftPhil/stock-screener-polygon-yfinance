"""
Unit tests for Small-Cap Momentum Screener (Polygon.io).
"""

import pytest
import pandas as pd
from unittest.mock import Mock, patch
import requests
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
                "free_float": 5_250_000,
                "share_class_shares_outstanding": 6_250_000,
            }
        elif ticker == "FAIL_MCAP":
            return {
                "market_cap": 150_000_000,  # Exceeds $100M
                "free_float": 7_000_000,
                "share_class_shares_outstanding": 8_000_000,
            }
        elif ticker == "FAIL_FLOAT":
            return {
                "market_cap": 36_000_000,
                "free_float": 12_000_000,
                "share_class_shares_outstanding": 12_000_000,  # Exceeds 10M
            }
        return None

    screener.fetch_ticker_details = mock_fetch_details
    results = screener.enrich_and_filter_fundamentals(candidates)

    result_tickers = [r["Ticker"] for r in results]
    assert result_tickers == ["PASS_ALL"]
    assert results[0]["Market Cap ($M)"] == 25.0
    assert results[0]["Float (M)"] == 5.25


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
                "Float (M)": 7.2,
        }
    ])

    formatted = PolygonScreener.format_dataframe_for_display(raw_df)

    expected_cols = ["Ticker", "Price", "Gap %", "Volume", "Market Cap ($M)", "Float (M)"]
    assert list(formatted.columns) == expected_cols

    row = formatted.iloc[0]
    assert row["Ticker"] == "ABCD"
    assert row["Price"] == "$4.50"
    assert row["Gap %"] == "+14.52%"
    assert row["Volume"] == "1,850,000"
    assert row["Market Cap ($M)"] == "$25.00"
    assert row["Float (M)"] == "7.20"


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
        columns=["Ticker", "Price", "Gap %", "Volume", "Market Cap ($M)", "Float (M)"]
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
        "WIN1": {"float_shares": 5_000_000, "market_cap": 25_000_000, "shares_outstanding": 7_000_000},
        "FAIL_HIGH_MCAP": {"float_shares": 6_000_000, "market_cap": 150_000_000},
        "FAIL_LOW_VOL": {"float_shares": 2_000_000, "market_cap": 10_000_000},
    }

    yf_screener.fetch_candidates = lambda: mock_quotes
    yf_screener.get_ticker_float_and_mcap = lambda sym: mock_fundamentals.get(sym, {"float_shares": None, "market_cap": None})

    df = yf_screener.scan()
    assert len(df) == 1
    assert df.iloc[0]["Ticker"] == "WIN1"
    assert df.iloc[0]["Price"] == 5.0
    assert df.iloc[0]["Float (M)"] == 5.0
    assert df.iloc[0]["Market Cap ($M)"] == 25.0


def test_midday_boundaries():
    """Verify MiddayScreener exact rules on boundary conditions including 5x RVOL."""
    from midday_screener import MiddayScreener
    screener = MiddayScreener(min_volume=500000, min_rvol=5.0)
    df = screener.run(demo=True)

    assert not df.empty
    tickers = df["Ticker"].tolist()
    # BLZE (change < 10% & rvol 2.0x) and SLOW (rvol 2.0x) should be excluded
    assert "BLZE" not in tickers
    assert "SLOW" not in tickers

    for _, row in df.iterrows():
        price = float(row["Price"])
        change = float(row["Today's Change %"])
        volume = int(row["Volume"])
        rvol = float(row["RVOL"])
        mcap = float(row["Market Cap ($M)"])
        float_m = float(row["Float (M)"])

        assert 2.00 <= price <= 10.00
        assert change >= 10.0
        assert rvol >= 5.0
        assert volume >= 500000
        assert mcap <= 100.0
        assert float_m <= 10.0


def test_sorting_toggles():
    """Verify sorting toggles by volume vs change percentage in MiddayScreener."""
    from midday_screener import MiddayScreener
    screener = MiddayScreener(min_volume=500000)

    # Test volume sort
    df_vol = screener.run(demo=True, sort_by="volume")
    if len(df_vol) >= 2:
        v1 = int(df_vol.iloc[0]["Volume"])
        v2 = int(df_vol.iloc[1]["Volume"])
        assert v1 >= v2

    # Test change % sort
    df_change = screener.run(demo=True, sort_by="change")
    if len(df_change) >= 2:
        c1 = float(df_change.iloc[0]["Today's Change %"])
        c2 = float(df_change.iloc[1]["Today's Change %"])
        assert c1 >= c2


def test_midday_polygon_auth_and_safe_error():
    """Verify MiddayScreener uses Bearer header and sanitizes errors."""
    from midday_screener import MiddayScreener
    test_key = "SECRET_API_KEY_999"
    screener = MiddayScreener(api_key=test_key, source="polygon")

    with patch("requests.get") as mock_get:
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"tickers": []}
        mock_get.return_value = mock_resp

        res = screener.fetch_polygon_data()
        assert res == []
        mock_get.assert_called_once()
        url = mock_get.call_args[0][0]
        assert "apiKey=" not in url
        headers = mock_get.call_args[1].get("headers", {})
        assert headers.get("Authorization") == f"Bearer {test_key}"

    # Verify connection error does not expose the secret
    with patch("requests.get", side_effect=ConnectionError(f"Failed to connect: {test_key}")):
        res_err = screener.fetch_polygon_data()
        assert res_err == []
        assert screener.last_status == "failed"
        assert test_key not in screener.last_error
        assert "[REDACTED]" in screener.last_error


def test_midday_live_failure_never_returns_demo_data():
    """Verify live fetch failures never fall back to DEMO_DATA unless demo=True."""
    from midday_screener import MiddayScreener
    with patch.dict("os.environ", {}, clear=True):
        screener_no_key = MiddayScreener(api_key=None, source="polygon")
        screener_no_key.api_key = None
        df = screener_no_key.run(demo=False)
        assert df.empty
        assert screener_no_key.last_status == "failed"
        assert "No Polygon API key provided" in screener_no_key.last_error


def test_midday_fundamentals_normalization_and_exclusion():
    """Verify candidates with missing/None market cap or float are excluded."""
    from midday_screener import MiddayScreener
    screener = MiddayScreener(api_key="TEST_KEY", source="yfinance")

    raw_items = [
        # Pass: all criteria met
        {"ticker": "PASS", "price": 5.0, "change_pct": 15.0, "volume": 1_000_000, "avg_volume": 100_000, "market_cap": 25_000_000, "float": 5_000_000},
        # Fail: market_cap is None
        {"ticker": "NOMCAP", "price": 5.0, "change_pct": 15.0, "volume": 1_000_000, "avg_volume": 100_000, "market_cap": None, "float": 5_000_000},
        # Fail: float is None
        {"ticker": "NOFLOAT", "price": 5.0, "change_pct": 15.0, "volume": 1_000_000, "avg_volume": 100_000, "market_cap": 25_000_000, "float": None},
    ]

    screener.fetch_yfinance_data = lambda: raw_items
    df = screener.run(demo=False)
    assert len(df) == 1
    assert df.iloc[0]["Ticker"] == "PASS"


def test_run_demo_restores_fetch_ticker_details():
    """Verify run_demo restores the screener's original fetch_ticker_details method."""
    screener = PolygonScreener(api_key="TEST_KEY")
    orig_method = screener.fetch_ticker_details
    run_demo(screener=screener)
    assert screener.fetch_ticker_details == orig_method


def test_format_rule_number_preserves_exact_values():
    """Verify _format_rule_number preserves exact limits without loss of precision."""
    from momentum_screener import _format_rule_number
    assert _format_rule_number(500_000) == "500K"
    assert _format_rule_number(10_000_000) == "10M"
    assert _format_rule_number(100_000_000) == "100M"
    assert _format_rule_number(10_500_000) == "10.5M"
    assert _format_rule_number(10_000_001) == "10.000001M"
    # When compact representation cannot round-trip exactly, full value is shown
    assert _format_rule_number(10_000_000_000_001) == "10000000000001"
    # Fallback for non-compact float round-trips the exact float value
    assert _format_rule_number(10_000_000_000_001.25) == "10000000000001.25"


def test_midday_init_parameter_order_and_rvol():
    """Verify MiddayScreener 3rd positional argument selects source and min_rvol is configurable."""
    from midday_screener import MiddayScreener

    # 3rd positional arg selects source
    s1 = MiddayScreener("TEST_KEY", 500000, "yfinance")
    assert s1.api_key == "TEST_KEY"
    assert s1.min_volume == 500000
    assert s1.source == "yfinance"
    assert s1.min_rvol == 5.0

    # min_rvol configurable without shifting source
    s2 = MiddayScreener("TEST_KEY", 500000, "yfinance", min_rvol=3.0)
    assert s2.source == "yfinance"
    assert s2.min_rvol == 3.0

    s3 = MiddayScreener("TEST_KEY", 500000, "polygon", 2.5)
    assert s3.source == "polygon"
    assert s3.min_rvol == 2.5

    # run() accepts numeric RVOL override
    df = s1.run(demo=True, min_rvol=10.0)
    # Only VORT (rvol 12.4x) matches when min_rvol=10.0
    assert len(df) == 1
    assert df.iloc[0]["Ticker"] == "VORT"


def test_midday_both_volume_and_rvol_limits_enforced():
    """Verify both min_volume and min_rvol thresholds are enforced simultaneously."""
    from midday_screener import MiddayScreener

    items = [
        # Pass: volume 600K >= 500K and rvol 6.0 >= 5.0
        {"ticker": "PASS", "price": 5.0, "change_pct": 15.0, "volume": 600_000, "avg_volume": 100_000, "market_cap": 25_000_000, "float": 5_000_000},
        # Fail: rvol is 10.0 >= 5.0, but volume 400K < 500K
        {"ticker": "LOW_VOL", "price": 5.0, "change_pct": 15.0, "volume": 400_000, "avg_volume": 40_000, "market_cap": 25_000_000, "float": 5_000_000},
        # Fail: volume 1M >= 500K, but rvol is 2.0 < 5.0
        {"ticker": "LOW_RVOL", "price": 5.0, "change_pct": 15.0, "volume": 1_000_000, "avg_volume": 500_000, "market_cap": 25_000_000, "float": 5_000_000},
        # Fail: price out of range ($1.50)
        {"ticker": "LOW_PRICE", "price": 1.5, "change_pct": 15.0, "volume": 600_000, "avg_volume": 100_000, "market_cap": 25_000_000, "float": 5_000_000},
        # Fail: change_pct too low (5.0%)
        {"ticker": "LOW_CHANGE", "price": 5.0, "change_pct": 5.0, "volume": 600_000, "avg_volume": 100_000, "market_cap": 25_000_000, "float": 5_000_000},
    ]

    screener = MiddayScreener(api_key="TEST_KEY", min_volume=500_000, min_rvol=5.0)
    screener.fetch_polygon_data = lambda: items
    df = screener.run(demo=False)

    assert len(df) == 1
    assert df.iloc[0]["Ticker"] == "PASS"


def test_float_is_never_inferred_from_shares_or_market_cap(screener):
    candidate = [{"ticker": "UNKNOWN", "price": 5, "volume": 900000, "gap_pct": 8}]
    screener.fetch_ticker_details = lambda _: {"market_cap": 20_000_000, "share_class_shares_outstanding": 2_000_000}
    assert screener.enrich_and_filter_fundamentals(candidate) == []
    screener.float_mode = "discovery"
    row = screener.enrich_and_filter_fundamentals(candidate)[0]
    assert row["Float"] is None
    assert row["Shares Outstanding"] == 2_000_000
    assert row["Float Status"] == "unverified"


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_invalid_float_is_unknown(screener, value):
    candidate = [{"ticker": "BAD", "price": 5, "volume": 900000, "gap_pct": 8}]
    screener.fetch_ticker_details = lambda _: {"market_cap": 20_000_000, "free_float": value}
    assert screener.enrich_and_filter_fundamentals(candidate) == []


def test_missing_float_and_shares_only_yahoo_discovery_mode():
    from yfinance_screener import YFinanceScreener
    scanner = YFinanceScreener(float_mode="discovery")
    scanner.fetch_candidates = lambda: [{"symbol": "ABC", "regularMarketPrice": 5, "regularMarketChangePercent": 8, "regularMarketVolume": 900000, "marketCap": 20_000_000}]
    scanner.get_ticker_float_and_mcap = lambda _: {"float_shares": None, "shares_outstanding": 1_000_000, "market_cap": 20_000_000}
    row = scanner.scan().iloc[0]
    assert pd.isna(row["Float"])
    assert row["Shares Outstanding"] == 1_000_000
    assert row["Float Status"] == "unverified"


def test_market_session_timezone_dst_and_holiday():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from market_data import market_session, is_nyse_session
    ny = ZoneInfo("America/New_York")
    assert market_session(datetime(2026, 3, 9, 9, 0, tzinfo=ny)) == "premarket"
    assert market_session(datetime(2026, 3, 9, 9, 30, tzinfo=ny)) == "regular"
    assert market_session(datetime(2026, 3, 9, 17, 0, tzinfo=ny)) == "after-hours"
    assert is_nyse_session(datetime(2026, 11, 26, 12, 0, tzinfo=ny)) is False


def test_yahoo_does_not_substitute_premarket_quote_fields_or_use_stale_quotes():
    from datetime import datetime, timezone
    from yfinance_screener import YFinanceScreener
    scanner = YFinanceScreener(float_mode="discovery")
    scanner.fetch_candidates = lambda: [
        {"symbol": "PRE", "preMarketPrice": 5.0, "preMarketChangePercent": 20.0, "preMarketVolume": 900000, "marketCap": 10_000_000},
        {"symbol": "OLD", "regularMarketPrice": 5.0, "regularMarketChangePercent": 20.0, "regularMarketVolume": 900000, "regularMarketTime": 1, "marketCap": 10_000_000},
    ]
    scanner.get_ticker_float_and_mcap = lambda _: {"float_shares": 1_000_000, "market_cap": 10_000_000}
    assert scanner.scan().empty


def test_midday_missing_daily_baseline_is_not_fabricated():
    from midday_screener import MiddayScreener
    scanner = MiddayScreener(source="yfinance", float_mode="discovery")
    scanner.fetch_yfinance_data = lambda: [{"ticker": "A", "price": 5, "change_pct": 20, "volume": 2_000_000, "avg_volume": None, "market_cap": 10_000_000, "float": None}]
    assert scanner.run().empty


def test_midday_yahoo_uses_dynamic_equity_query():
    from midday_screener import MiddayScreener
    scanner = MiddayScreener(source="yfinance")
    quote = {"symbol": "NEW", "regularMarketPrice": 4.0, "regularMarketChangePercent": 15.0, "regularMarketVolume": 600_000}
    fake_ticker = Mock(info={"marketCap": 10_000_000, "floatShares": 1_000_000, "averageVolume": 100_000})
    with patch("midday_screener.yf.Ticker", return_value=fake_ticker), patch("midday_screener.yf.screen", return_value={"quotes": [quote]}) as screen:
        result = scanner.fetch_yfinance_data()
    assert result[0]["ticker"] == "NEW"
    screen.assert_called_once()


def test_midday_finnhub_quote_and_profile_are_bounded_and_attributed():
    from datetime import datetime, timezone
    from midday_screener import MiddayScreener
    scanner = MiddayScreener(api_key="TEST_FINNHUB_KEY", source="finnhub", float_mode="discovery")
    scanner.fetch_yfinance_data = lambda limit=250: [{
        "ticker": "ABC", "price": 5.0, "change_pct": 12.0, "volume": 1_000_000,
        "avg_volume": 100_000, "market_cap": None, "float": None,
    }]
    now = int(datetime.now(timezone.utc).timestamp())
    def response_for(url, **kwargs):
        response = Mock(status_code=200)
        response.json.return_value = (
            {"c": 5.2, "dp": 14, "t": now} if url.endswith("/quote") else
            {"ticker": "ABC", "marketCapitalization": 25, "shareOutstanding": 8}
        )
        return response
    with patch("midday_screener.requests.get", side_effect=response_for) as get, patch("midday_screener.time.sleep"):
        result = scanner.run()
    assert result.iloc[0]["Ticker"] == "ABC"
    assert result.iloc[0]["Quote Source"] == "Finnhub"
    assert result.iloc[0]["Volume Source"] == "Yahoo Finance"
    assert result.iloc[0]["Market Cap ($M)"] == 25
    assert result.iloc[0]["Shares Outstanding (M)"] == 8
    assert pd.isna(result.iloc[0]["Float (M)"])
    assert result.iloc[0]["Float Status"] == "unverified"
    assert len(get.call_args_list) == 2
    assert all(call.kwargs["params"]["token"] == "TEST_FINNHUB_KEY" for call in get.call_args_list)


def test_finnhub_request_errors_do_not_expose_token():
    from midday_screener import MiddayScreener
    scanner = MiddayScreener(api_key="TOP_SECRET", source="finnhub")
    with patch("midday_screener.requests.get", side_effect=requests.exceptions.ConnectionError("url contained TOP_SECRET")):
        with pytest.raises(RuntimeError) as exc:
            scanner._finnhub_json("quote", {"symbol": "ABC"})
    assert "TOP_SECRET" not in str(exc.value)


def test_finnhub_distinguishes_401_403_and_preserves_other_non_200():
    from midday_screener import MiddayScreener
    scanner = MiddayScreener(api_key="TEST_KEY", source="finnhub")

    for status_code in (401, 403):
        mock_resp = Mock(status_code=status_code)
        with patch.object(scanner, "_get", return_value=mock_resp), patch("midday_screener.time.sleep"):
            with pytest.raises(PermissionError) as exc:
                scanner._finnhub_json("quote", {"symbol": "ABC"})
            assert f"HTTP {status_code}" in str(exc.value)
            assert "authentication or entitlement" in str(exc.value)

    mock_resp_500 = Mock(status_code=500)
    with patch.object(scanner, "_get", return_value=mock_resp_500), patch("midday_screener.time.sleep"):
        with pytest.raises(RuntimeError) as exc:
            scanner._finnhub_json("quote", {"symbol": "ABC"})
        assert "HTTP 500" in str(exc.value)


def test_fetch_finnhub_data_stops_on_auth_failure_and_returns_collected_rows():
    from datetime import datetime, timezone
    from midday_screener import MiddayScreener

    scanner = MiddayScreener(api_key="TEST_KEY", source="finnhub")
    scanner.fetch_yfinance_data = lambda limit=250: [
        {"ticker": "FIRST", "price": 5.0, "change_pct": 12.0, "volume": 1_000_000, "avg_volume": 100_000, "market_cap": None, "float": None},
        {"ticker": "SECOND", "price": 6.0, "change_pct": 15.0, "volume": 2_000_000, "avg_volume": 200_000, "market_cap": None, "float": None},
        {"ticker": "THIRD", "price": 7.0, "change_pct": 20.0, "volume": 3_000_000, "avg_volume": 300_000, "market_cap": None, "float": None},
    ]

    now = int(datetime.now(timezone.utc).timestamp())
    calls = []

    def mock_finnhub_json(path, params):
        calls.append((path, params.get("symbol")))
        sym = params.get("symbol")
        if sym == "FIRST":
            if path == "quote":
                return {"c": 5.0, "dp": 12.0, "t": now}
            return {"marketCapitalization": 20, "shareOutstanding": 5}
        elif sym == "SECOND":
            raise PermissionError("Finnhub authentication or entitlement failed (HTTP 401).")
        raise RuntimeError("Should not be called for THIRD")

    with patch.object(scanner, "_finnhub_json", side_effect=mock_finnhub_json):
        rows = scanner.fetch_finnhub_data()

    # Returned first row already collected
    assert len(rows) == 1
    assert rows[0]["ticker"] == "FIRST"
    # THIRD candidate was never processed
    assert not any(sym == "THIRD" for _, sym in calls)
    # Failed status and authentication message recorded
    assert scanner.last_status == "failed"
    assert "authentication or entitlement" in scanner.last_error
    assert "HTTP 401" in scanner.last_error


def test_fetch_finnhub_data_failures_and_stale_quotes_accounting():
    from datetime import datetime, timezone, timedelta
    from midday_screener import MiddayScreener

    scanner = MiddayScreener(api_key="TEST_KEY", source="finnhub")
    scanner.fetch_yfinance_data = lambda limit=250: [
        {"ticker": "FAIL1"},
        {"ticker": "STALE1"},
        {"ticker": "FAIL2"},
    ]

    stale_ts = int((datetime.now(timezone.utc) - timedelta(minutes=30)).timestamp())

    def mock_finnhub_json(path, params):
        sym = params.get("symbol")
        if sym == "STALE1":
            if path == "quote":
                return {"c": 5.0, "dp": 10.0, "t": stale_ts}
            return {"marketCapitalization": 10, "shareOutstanding": 2}
        raise RuntimeError(f"Request failed for {sym}")

    with patch.object(scanner, "_finnhub_json", side_effect=mock_finnhub_json):
        rows = scanner.fetch_finnhub_data()

    assert rows == []
    assert scanner.last_status == "failed"
    # Both failures (2) and stale_quotes (1) should be accounted for in the message
    assert "2 candidate(s)" in scanner.last_error
    assert "1 candidate(s)" in scanner.last_error
    assert "stale" in scanner.last_error

    # When failures only (no stale quotes), preserves original message
    scanner2 = MiddayScreener(api_key="TEST_KEY", source="finnhub")
    scanner2.fetch_yfinance_data = lambda limit=250: [{"ticker": "FAIL1"}]
    with patch.object(scanner2, "_finnhub_json", side_effect=RuntimeError("Request failed")):
        rows2 = scanner2.fetch_finnhub_data()

    assert rows2 == []
    assert scanner2.last_status == "failed"
    assert scanner2.last_error == "Finnhub quote/profile requests failed for all discovered candidates."


def test_fetch_polygon_historical_avg_volume_and_rvol_gate():
    """Verify Polygon path fetches 10-day historical daily volume average before RVOL gate."""
    from midday_screener import MiddayScreener

    screener = MiddayScreener(api_key="TEST_KEY", source="polygon", min_volume=500_000, min_rvol=5.0)

    # Mock historical daily aggregates response (10 bars)
    mock_aggs = {
        "results": [{"v": 100_000}, {"v": 200_000}, {"v": 300_000}]
    }

    with patch("requests.get") as mock_get:
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_aggs
        mock_get.return_value = mock_resp

        avg_vol = screener.fetch_polygon_historical_avg_volume("TEST", days=10)
        assert avg_vol == 200_000.0
        mock_get.assert_called_once()
        url = mock_get.call_args[0][0]
        assert "/v2/aggs/ticker/TEST/range/1/day/" in url

        # Verify end_date excludes today's ET date and is set to yesterday ET
        from datetime import datetime, timedelta
        try:
            from zoneinfo import ZoneInfo
            expected_yesterday = (datetime.now(ZoneInfo("America/New_York")).date() - timedelta(days=1)).strftime("%Y-%m-%d")
            today_et = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
        except Exception:
            expected_yesterday = (datetime.now().date() - timedelta(days=1)).strftime("%Y-%m-%d")
            today_et = datetime.now().strftime("%Y-%m-%d")

        assert url.endswith(f"/{expected_yesterday}")
        assert not url.endswith(f"/{today_et}")

        params = mock_get.call_args[1].get("params", {})
        assert params.get("limit") == 10
        assert params.get("sort") == "desc"


def test_polygon_historical_avg_volume_skips_repeat_requests_on_none():
    """Verify Polygon flow skips repeat historical volume lookups after None and uses fallback."""
    from midday_screener import MiddayScreener

    screener = MiddayScreener(api_key="TEST_KEY", source="polygon", min_volume=500_000, min_rvol=5.0, float_mode="strict")

    snapshot_resp = Mock(status_code=200)
    snapshot_resp.json.return_value = {
        "tickers": [{
            "ticker": "FAIL_AGGS",
            "day": {"c": 5.0, "v": 1_000_000},
            "prevDay": {"c": 4.0},
        }]
    }
    aggs_resp = Mock(status_code=404)
    details_resp = Mock(status_code=200)
    details_resp.json.return_value = {
        "results": {"market_cap": 50_000_000, "free_float": 5_000_000}
    }

    def mock_get(url, *args, **kwargs):
        if "snapshot" in url:
            return snapshot_resp
        elif "aggs" in url:
            return aggs_resp
        elif "reference" in url:
            return details_resp
        return Mock(status_code=404)

    with patch("midday_screener.requests.get", side_effect=mock_get) as pget:
        df = screener.run(demo=False)
        aggs_calls = [c for c in pget.call_args_list if "aggs" in c[0][0]]
        # Exactly 1 call to aggs, no repeat request after None
        assert len(aggs_calls) == 1
        # Proceeded to fallback baseline (100000), calculated RVOL = 10.0x, passed screener
        assert len(df) == 1
        assert df.iloc[0]["Ticker"] == "FAIL_AGGS"
        assert df.iloc[0]["RVOL"] == 10.0





