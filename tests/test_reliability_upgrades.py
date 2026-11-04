from unittest.mock import Mock
from datetime import datetime, timezone

from finnhub_screener import FinnhubScreener
from midday_screener import MiddayScreener


def test_missing_polygon_history_excludes_candidate_without_fallback():
    screener = MiddayScreener(api_key="TEST", source="polygon", min_rvol=1)
    screener.fetch_polygon_data = lambda: [{
        "ticker": "ABCD", "price": 5.0, "change_pct": 15.0,
        "volume": 900_000, "avg_volume": None, "avg_volume_attempted": True,
        "market_cap": 20_000_000, "float": 2_000_000,
    }]
    screener.fetch_polygon_historical_avg_volume = lambda ticker, days=10: None

    result = screener.run()

    assert result.empty
    assert screener.last_status == "incomplete"
    assert "excluded" in screener.last_error


def test_finnhub_strict_mode_excludes_unknown_float():
    screener = FinnhubScreener(api_key="TEST", float_mode="strict")
    screener.client = Mock()
    screener.client.quote.return_value = {"c": 5.0, "dp": 12.0, "t": int(datetime.now(timezone.utc).timestamp())}
    screener.client.company_profile2.return_value = {
        "marketCapitalization": 20.0,
        "shareOutstanding": 5.0,
    }

    assert screener.fetch_ticker_data("ABCD") is None
    screener.client.stock_candles.assert_not_called()


def test_finnhub_never_substitutes_shares_outstanding_for_float():
    screener = FinnhubScreener(api_key="TEST", float_mode="discovery", min_volume=0)
    screener.client = Mock()
    now = int(datetime.now(timezone.utc).timestamp())
    screener.client.quote.return_value = {"c": 5.0, "dp": 12.0, "t": now}
    screener.client.company_profile2.return_value = {
        "marketCapitalization": 20.0,
        "shareOutstanding": 5.0,
    }
    screener.client.stock_candles.return_value = {"s": "ok", "v": [1_000_000, 700_000], "t": [now - 86400, now]}

    row = screener.fetch_ticker_data("ABCD")

    assert row["Float (M)"] is None
    assert row["Float Status"] == "unverified"
    assert row["Volume"] == 700_000
    assert row["RVOL"] == 0.7


def test_midday_provider_failure_is_not_reported_as_empty_success():
    screener = MiddayScreener(source="polygon")

    result = screener.run()

    assert result.empty
    assert screener.last_status == "failed"
    assert screener.last_error
