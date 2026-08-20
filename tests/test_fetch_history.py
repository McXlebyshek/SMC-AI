"""
Tests for fetch_history — pagination, dedup, filtering, edge cases.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
import pandas as pd

from data.fetch_history import fetch_history, fetch_all_symbols, _candle_duration_ms


# --- Fixtures ---


def make_candles(count: int, step_ms: int = 3_600_000, base_ts: int = 1704067200000) -> list:
    """Generate `count` synthetic OHLCV candles (base_ts = oldest)."""
    records = []
    for i in range(count):
        ts = base_ts + i * step_ms
        price = 42000.0 + i * 10.0
        records.append([ts, price, price + 100, price - 50, price + 50, 100.0 + i])
    return records


def _mock_client(records_per_call: list) -> tuple:
    """Build a mock client that returns `records_per_call` sequentially.

    Each call to fetch_ohlcv returns the next element from the list.
    Once exhausted, returns [].
    """
    call_idx = [0]

    def side_effect(*args, **kwargs):
        if call_idx[0] < len(records_per_call):
            call_idx[0] += 1
            return records_per_call[call_idx[0] - 1]
        return []

    exchange = MagicMock()
    exchange.fetch_ohlcv.side_effect = side_effect
    client = MagicMock()
    client.exchange = exchange
    return client, exchange


# --- _candle_duration_ms ---


class TestCandleDurationMs:
    def test_1m(self):
        assert _candle_duration_ms("1m") == 60_000

    def test_1h(self):
        assert _candle_duration_ms("1h") == 3_600_000

    def test_1d(self):
        assert _candle_duration_ms("1d") == 86_400_000

    def test_1W(self):
        assert _candle_duration_ms("1W") == 604_800_000

    def test_unsupported(self):
        with pytest.raises(ValueError, match="Unsupported timeframe"):
            _candle_duration_ms("3x")


# --- fetch_history ---


class TestFetchHistory:
    def test_single_page_no_pagination(self):
        """Single request returns data, second call returns empty to confirm end."""
        client, exchange = _mock_client([make_candles(50)])
        end = datetime(2024, 1, 5, tzinfo=timezone.utc)
        with patch("data.fetch_history.time.sleep", return_value=None):
            df = fetch_history(client, "BTC/USDT", timeframe="1h", end=end)
        assert len(df) == 50
        # First call returns data, second returns [] to stop loop
        assert exchange.fetch_ohlcv.call_count == 2

    def test_pagination_multiple_pages(self):
        """When data exceeds limit, fetches multiple pages backwards."""
        # Pages ordered by API call: newest first, then older
        page1 = make_candles(1000, step_ms=3_600_000, base_ts=1704153600000)   # newest
        page2 = make_candles(500, step_ms=3_600_000, base_ts=1703900000000)    # older

        client, exchange = _mock_client([page1, page2])

        end = datetime.fromtimestamp(1704153600000 / 1000, tz=timezone.utc)
        # Start is between page1 oldest and page2 oldest, so loop stops on page2
        start = datetime(2023, 12, 30, 12, 0, 0, tzinfo=timezone.utc)

        with patch("data.fetch_history.time.sleep", return_value=None):
            df = fetch_history(client, "BTC/USDT", timeframe="1h", start=start, end=end)

        # 2 data pages (page2 oldest=1703900000000 < start, loop stops)
        assert exchange.fetch_ohlcv.call_count == 2
        assert len(df) == 1489

    def test_deduplication(self):
        """Overlapping boundary candles are deduplicated."""
        shared_ts = 1704067200000
        page1 = [[1704153600000, 42100, 42200, 42050, 42150, 100],
                 [shared_ts, 42000, 42100, 41950, 42050, 90]]
        page2 = [[shared_ts, 42000, 42100, 41950, 42050, 90],
                 [1703980800000, 41900, 42000, 41850, 41950, 80]]

        client, exchange = _mock_client([page1, page2])

        with patch("data.fetch_history.time.sleep", return_value=None):
            df = fetch_history(client, "BTC/USDT", timeframe="1h")

        # shared_ts appears only once → 3 unique candles
        assert len(df) == 3

    def test_filter_by_start(self):
        """Candles before `start` are excluded."""
        records = make_candles(10, base_ts=1704067200000)
        client, exchange = _mock_client([records])

        # Mock data: 10 candles from 00:00 to 09:00 (base_ts=1704067200000)
        # Start at 03:00 → keep candles 03,04,05,06,07,08,09 = 7 candles
        end = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        start = datetime(2024, 1, 1, 3, 0, 0, tzinfo=timezone.utc)

        with patch("data.fetch_history.time.sleep", return_value=None):
            df = fetch_history(client, "BTC/USDT", timeframe="1h", start=start, end=end)

        assert len(df) == 7

    def test_limit_candles(self):
        """`limit` caps the total returned candles."""
        records = make_candles(100)
        client, exchange = _mock_client([records])
        end = datetime(2024, 2, 1, tzinfo=timezone.utc)

        with patch("data.fetch_history.time.sleep", return_value=None):
            df = fetch_history(client, "BTC/USDT", timeframe="1h", limit=25)

        assert len(df) == 25
        exchange.fetch_ohlcv.assert_called_once()

    def test_empty_response(self):
        """Returns empty DataFrame when exchange returns nothing."""
        exchange = MagicMock()
        exchange.fetch_ohlcv.return_value = []
        client = MagicMock()
        client.exchange = exchange
        df = fetch_history(client, "BTC/USDT", timeframe="1h")
        assert len(df) == 0
        assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]

    def test_columns_and_index(self):
        """Result has correct column names and UTC datetime index."""
        records = make_candles(5)
        client, exchange = _mock_client([records])
        with patch("data.fetch_history.time.sleep", return_value=None):
            df = fetch_history(client, "BTC/USDT", timeframe="1h")

        assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
        assert df.index.name == "timestamp"
        assert df.index.tz is not None  # type: ignore[attr-defined]

    def test_sorted_ascending(self):
        """Data is sorted chronologically (oldest first)."""
        records = make_candles(10)
        client, exchange = _mock_client([records])
        with patch("data.fetch_history.time.sleep", return_value=None):
            df = fetch_history(client, "BTC/USDT", timeframe="1h")

        timestamps = df.index.tolist()
        assert timestamps == sorted(timestamps)

    def test_stop_at_start_boundary(self):
        """Pagination stops once oldest candle <= start."""
        page1 = make_candles(1000, step_ms=3_600_000, base_ts=1704153600000)
        page2 = make_candles(1000, step_ms=3_600_000, base_ts=1703900000000)

        client, exchange = _mock_client([page1, page2])

        end = datetime.fromtimestamp(1704153600000 / 1000, tz=timezone.utc)
        start = datetime.fromtimestamp(1703950000000 / 1000, tz=timezone.utc)

        with patch("data.fetch_history.time.sleep", return_value=None):
            df = fetch_history(client, "BTC/USDT", timeframe="1h", start=start, end=end)

        # page2 oldest ts (1703900000000) <= start (1703950000000), so loop stops
        assert exchange.fetch_ohlcv.call_count == 2
        # Only candles >= start are kept
        assert len(df) > 0


# --- fetch_all_symbols ---


class TestFetchAllSymbols:
    def test_fetch_multiple_combinations(self):
        """Returns dict with all symbol x timeframe combinations."""
        page1 = make_candles(3)
        client, exchange = _mock_client([page1])

        end = datetime(2024, 2, 1, tzinfo=timezone.utc)
        with patch("data.fetch_history.time.sleep", return_value=None):
            results = fetch_all_symbols(
                client,
                symbols=["BTC/USDT", "ETH/USDT"],
                timeframes=["1h", "4h"],
                end=end,
            )

        assert "BTC/USDT" in results
        assert "ETH/USDT" in results
        assert "1h" in results["BTC/USDT"]
        assert "4h" in results["BTC/USDT"]
        assert len(results["BTC/USDT"]["1h"]) == 3

    def test_failed_symbol_returns_empty_df(self):
        """If one symbol fails, it gets an empty DataFrame, others still work."""
        eth_page = make_candles(5)

        call_tracker = {"btc": 0, "eth": 0}

        def side_effect(symbol, timeframe, limit, since):
            if "BTC" in symbol:
                call_tracker["btc"] += 1
                raise Exception("API error")
            # ETH: first call returns data, second returns empty to stop pagination
            call_tracker["eth"] += 1
            if call_tracker["eth"] == 1:
                return eth_page
            return []

        exchange = MagicMock()
        exchange.fetch_ohlcv.side_effect = side_effect
        client = MagicMock()
        client.exchange = exchange

        with patch("data.fetch_history.time.sleep", return_value=None):
            results = fetch_all_symbols(
                client,
                symbols=["BTC/USDT", "ETH/USDT"],
                timeframes=["1h"],
            )

        assert len(results["BTC/USDT"]["1h"]) == 0
        assert len(results["ETH/USDT"]["1h"]) == 5
