"""
Tests for BybitClient — connection, OHLCV fetching, and error handling.
"""

from unittest.mock import MagicMock, patch

import pytest

from data.bybit_client import BybitClient


@pytest.fixture
def mock_exchange():
    """Return a fully configured mock ccxt exchange."""
    exchange = MagicMock()
    exchange.load_markets.return_value = {
        "BTC/USDT": {"symbol": "BTC/USDT", "base": "BTC", "quote": "USDT"},
        "ETH/USDT": {"symbol": "ETH/USDT", "base": "ETH", "quote": "USDT"},
    }
    exchange.fetch_ohlcv.return_value = [
        [1704067200000, 42000.0, 43000.0, 41500.0, 42800.0, 150.5],
        [1704070800000, 42800.0, 43500.0, 42500.0, 43200.0, 200.3],
        [1704074400000, 43200.0, 44000.0, 43000.0, 43800.0, 180.1],
    ]
    return exchange


@pytest.fixture
def bybit_client(mock_exchange):
    """Create a BybitClient with a mocked exchange."""
    with patch("data.bybit_client.ccxt.bybit", return_value=mock_exchange):
        client = BybitClient(api_key="fake_key", secret="fake_secret")
    return client


class TestBybitInit:
    """Tests for BybitClient initialization."""

    def test_init_with_credentials(self, mock_exchange):
        """Client initializes with provided API credentials."""
        with patch("data.bybit_client.ccxt.bybit", return_value=mock_exchange) as mock_bybit:
            BybitClient(api_key="key123", secret="secret456")
            mock_bybit.assert_called_once_with({
                "apiKey": "key123",
                "secret": "secret456",
                "enableRateLimit": True,
                "options": {"defaultType": "spot"},
            })

    def test_init_without_credentials(self, mock_exchange):
        """Client initializes with empty strings when no credentials provided."""
        with patch("data.bybit_client.ccxt.bybit", return_value=mock_exchange) as mock_bybit:
            BybitClient()
            mock_bybit.assert_called_once()
            call_args = mock_bybit.call_args[0][0]
            assert call_args["apiKey"] == ""
            assert call_args["secret"] == ""

    def test_init_default_rate_limit(self, mock_exchange):
        """Rate limiting is enabled by default."""
        with patch("data.bybit_client.ccxt.bybit", return_value=mock_exchange) as mock_bybit:
            BybitClient()
            call_args = mock_bybit.call_args[0][0]
            assert call_args["enableRateLimit"] is True


class TestCheckConnection:
    """Tests for the check_connection method."""

    def test_check_connection_success(self, bybit_client, mock_exchange):
        """Returns True when markets load successfully."""
        result = bybit_client.check_connection()
        assert result is True
        mock_exchange.load_markets.assert_called_once()

    def test_check_connection_failure(self, mock_exchange):
        """Returns False and logs error when connection fails."""
        mock_exchange.load_markets.side_effect = Exception("Network error")
        with patch("data.bybit_client.ccxt.bybit", return_value=mock_exchange):
            client = BybitClient()
            result = client.check_connection()
        assert result is False


class TestFetchOHLCV:
    """Tests for OHLCV data fetching."""

    def test_fetch_ohlcv_returns_dataframe(self, bybit_client):
        """Returns a pandas DataFrame with OHLCV data."""
        df = bybit_client.fetch_ohlcv("BTC/USDT", timeframe="1h")
        assert df is not None
        assert len(df) == 3

    def test_fetch_ohlcv_column_names(self, bybit_client):
        """Column names are capitalized: Open, High, Low, Close, Volume."""
        df = bybit_client.fetch_ohlcv("BTC/USDT", timeframe="1h")
        expected_columns = ["Open", "High", "Low", "Close", "Volume"]
        assert list(df.columns) == expected_columns

    def test_fetch_ohlcv_index_is_datetime(self, bybit_client):
        """Index is a UTC datetime index."""
        df = bybit_client.fetch_ohlcv("BTC/USDT", timeframe="1h")
        assert df.index.name == "timestamp"
        assert df.index.tz is not None

    def test_fetch_ohlcv_passes_parameters(self, bybit_client, mock_exchange):
        """Correct symbol and timeframe are passed to ccxt."""
        bybit_client.fetch_ohlcv("ETH/USDT", timeframe="4h", limit=500)
        mock_exchange.fetch_ohlcv.assert_called_once_with(
            "ETH/USDT", timeframe="4h", limit=500, since=None
        )

    def test_fetch_ohlcv_with_since(self, bybit_client, mock_exchange):
        """Since parameter is forwarded correctly."""
        since_ts = 1704067200000
        bybit_client.fetch_ohlcv("BTC/USDT", since=since_ts)
        mock_exchange.fetch_ohlcv.assert_called_once_with(
            "BTC/USDT", timeframe="1h", limit=1000, since=since_ts
        )

    def test_fetch_ohlcv_value_types(self, bybit_client):
        """OHLCV values are numeric floats."""
        df = bybit_client.fetch_ohlcv("BTC/USDT", timeframe="1h")
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            assert df[col].dtype in ("float64", "float32")

    def test_fetch_ohlcv_invalid_symbol(self, mock_exchange):
        """Raises ccxt error for invalid symbol."""
        mock_exchange.fetch_ohlcv.side_effect = Exception("Invalid symbol")
        with patch("data.bybit_client.ccxt.bybit", return_value=mock_exchange):
            client = BybitClient()
            with pytest.raises(Exception):
                client.fetch_ohlcv("INVALID/USDT")


class TestIntegration:
    """Light integration test — hits the real Bybit public API (no keys needed)."""

    def test_live_connection(self):
        """Real connection check against Bybit (read-only, no keys)."""
        client = BybitClient()
        assert client.check_connection() is True

    def test_live_fetch_ohlcv(self):
        """Fetch real BTC/USDT 1h candles from Bybit."""
        client = BybitClient()
        df = client.fetch_ohlcv("BTC/USDT", timeframe="1h", limit=5)
        assert len(df) == 5
        assert "Close" in df.columns
        assert df["Close"].iloc[0] > 0
