"""
Integration tests for DBManager — real SQLite persistence layer.

Tests cover:
- Table creation / dropping
- Upsert / bulk upsert of OHLCV candles
- Fetch with filters (limit, since, until, ascending)
- Metadata queries (latest_timestamp, symbols, timeframes, counts)
- Edge cases (empty DB, duplicates, multiple symbols)

Uses a temporary SQLite file per test class for isolation.
"""

import os
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
import pytest
from sqlalchemy.orm import Session, sessionmaker

from data.db_manager import DBManager, OhlcvRecord


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_manager():
    """Create an in-memory SQLite DBManager, create tables, drop after test."""
    manager = DBManager(database_url="sqlite:///")
    manager.create_tables()
    yield manager
    # Cleanup — SQLAlchemy in-memory SQLite drops on engine disposal
    manager._engine.dispose()


@pytest.fixture()
def temp_db_manager():
    """Create a DBManager backed by a real temp file (survives engine disposal)."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    manager = DBManager(database_url=f"sqlite:///{tmp.name}")
    manager.create_tables()
    yield manager
    manager._engine.dispose()
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


def _make_ohlcv_df(n: int, base_ts: Optional[datetime] = None, step_hours: int = 1) -> pd.DataFrame:
    """Create a synthetic OHLCV DataFrame with `n` candles.

    Columns: Open, High, Low, Close, Volume (matching DBManager.upsert_ohlcv expectations).
    Index: UTC datetime.
    """
    if base_ts is None:
        base_ts = datetime(2024, 1, 1, tzinfo=timezone.utc)

    records = []
    for i in range(n):
        ts = base_ts + timedelta(hours=step_hours * i)
        price = 42000.0 + i * 10.0
        records.append({
            "Open": price,
            "High": price + 100.0,
            "Low": price - 50.0,
            "Close": price + 50.0,
            "Volume": 100.0 + i * 0.5,
        })

    df = pd.DataFrame(records)
    df.index = pd.DatetimeIndex([ts for ts in pd.date_range(base_ts, periods=n, freq=f"{step_hours}h")], tz=timezone.utc)
    return df


# ---------------------------------------------------------------------------
# Table lifecycle
# ---------------------------------------------------------------------------


class TestTableLifecycle:
    def test_create_tables_succeeds(self, db_manager):
        """create_tables() succeeds without error."""
        db_manager.create_tables()  # no exception = pass

    def test_drop_tables_removes_tables(self, temp_db_manager):
        """drop_tables() actually removes the ohlcv table."""
        temp_db_manager.drop_tables()
        # Verify table is gone by trying a query
        with temp_db_manager._session() as session:
            from sqlalchemy import text as sa_text
            result = session.execute(sa_text("SELECT name FROM sqlite_master WHERE type='table' AND name='ohlcv'"))
            assert len(result.fetchall()) == 0

    def test_recreate_after_drop(self, temp_db_manager):
        """Can recreate tables after dropping them."""
        temp_db_manager.drop_tables()
        temp_db_manager.create_tables()
        df = _make_ohlcv_df(3)
        inserted = temp_db_manager.upsert_ohlcv(df, "BTC/USDT", "1h")
        assert inserted > 0


# ---------------------------------------------------------------------------
# Upsert single candles
# ---------------------------------------------------------------------------


class TestUpsertOHLCV:
    def test_upsert_inserts_candles(self, db_manager):
        """upsert_ohlcv() inserts all rows from DataFrame."""
        df = _make_ohlcv_df(10)
        inserted = db_manager.upsert_ohlcv(df, "BTC/USDT", "1h")
        assert inserted == 10

    def test_upsert_column_mapping(self, db_manager):
        """Column names Open/High/Low/Close/Volume map correctly to DB columns."""
        df = _make_ohlcv_df(1)
        inserted = db_manager.upsert_ohlcv(df, "ETH/USDT", "4h")
        assert inserted == 1

        result = db_manager.fetch_ohlcv("ETH/USDT", "4h")
        assert len(result) == 1
        assert result["open"].iloc[0] == 42000.0
        assert result["high"].iloc[0] == 42100.0
        assert result["low"].iloc[0] == 41950.0
        assert result["close"].iloc[0] == 42050.0
        assert result["volume"].iloc[0] == 100.0

    def test_upsert_multiple_symbols(self, db_manager):
        """Candles for different symbols coexist."""
        df_btc = _make_ohlcv_df(5, base_ts=datetime(2024, 1, 1, tzinfo=timezone.utc))
        df_eth = _make_ohlcv_df(5, base_ts=datetime(2024, 1, 1, tzinfo=timezone.utc))

        db_manager.upsert_ohlcv(df_btc, "BTC/USDT", "1h")
        db_manager.upsert_ohlcv(df_eth, "ETH/USDT", "1h")

        btc_df = db_manager.fetch_ohlcv("BTC/USDT", "1h")
        eth_df = db_manager.fetch_ohlcv("ETH/USDT", "1h")

        assert len(btc_df) == 5
        assert len(eth_df) == 5

    def test_upsert_multiple_timeframes(self, db_manager):
        """Same symbol, different timeframes stored independently."""
        df_1h = _make_ohlcv_df(3, step_hours=1)
        df_4h = _make_ohlcv_df(3, step_hours=4, base_ts=datetime(2024, 1, 1, tzinfo=timezone.utc))

        db_manager.upsert_ohlcv(df_1h, "SOL/USDT", "1h")
        db_manager.upsert_ohlcv(df_4h, "SOL/USDT", "4h")

        count_1h = db_manager.get_candle_count("SOL/USDT", "1h")
        count_4h = db_manager.get_candle_count("SOL/USDT", "4h")

        assert count_1h == 3
        assert count_4h == 3


# ---------------------------------------------------------------------------
# Bulk upsert
# ---------------------------------------------------------------------------


class TestBulkUpsertOHLCV:
    def test_bulk_upsert_inserts_all(self, db_manager):
        """bulk_upsert_ohlcv() inserts all rows in one call."""
        df = _make_ohlcv_df(500)
        inserted = db_manager.bulk_upsert_ohlcv(df, "BTC/USDT", "1h")
        assert inserted == 500

    def test_bulk_vs_upsert_equivalence(self, temp_db_manager):
        """bulk_upsert and upsert produce equivalent results for same data."""
        df = _make_ohlcv_df(100)

        inserted_bulk = temp_db_manager.bulk_upsert_ohlcv(df, "BULK/USDT", "1h")
        inserted_single = temp_db_manager.upsert_ohlcv(df, "SINGLE/USDT", "1h")

        assert inserted_bulk == inserted_single == 100

        df_bulk = temp_db_manager.fetch_ohlcv("BULK/USDT", "1h")
        df_single = temp_db_manager.fetch_ohlcv("SINGLE/USDT", "1h")

        pd.testing.assert_frame_equal(df_bulk, df_single, check_names=False)

    def test_bulk_upsert_large_dataset(self, db_manager):
        """Can handle large dataset (10000 candles)."""
        df = _make_ohlcv_df(10000, step_hours=1)
        inserted = db_manager.bulk_upsert_ohlcv(df, "LARGE/USDT", "1m")
        assert inserted == 10000

        result = db_manager.fetch_ohlcv("LARGE/USDT", "1m")
        assert len(result) == 10000


# ---------------------------------------------------------------------------
# Fetch OHLCV — basic
# ---------------------------------------------------------------------------


class TestFetchOHLCV:
    def test_fetch_returns_dataframe(self, db_manager):
        """fetch_ohlcv() returns a DataFrame."""
        df = _make_ohlcv_df(5)
        db_manager.upsert_ohlcv(df, "BTC/USDT", "1h")

        result = db_manager.fetch_ohlcv("BTC/USDT", "1h")
        assert isinstance(result, pd.DataFrame)

    def test_fetch_correct_columns(self, db_manager):
        """Result has correct column names: timestamp, open, high, low, close, volume."""
        df = _make_ohlcv_df(3)
        db_manager.upsert_ohlcv(df, "BTC/USDT", "1h")

        result = db_manager.fetch_ohlcv("BTC/USDT", "1h")
        assert list(result.columns) == ["open", "high", "low", "close", "volume"]
        assert result.index.name == "timestamp"

    def test_fetch_value_types(self, db_manager):
        """All price/volume columns are float."""
        df = _make_ohlcv_df(5)
        db_manager.upsert_ohlcv(df, "BTC/USDT", "1h")

        result = db_manager.fetch_ohlcv("BTC/USDT", "1h")
        for col in ["open", "high", "low", "close", "volume"]:
            assert pd.api.types.is_float_dtype(result[col])

    def test_fetch_empty_db(self, db_manager):
        """Returns empty DataFrame with correct columns when no data exists."""
        result = db_manager.fetch_ohlcv("NONEXISTENT/USDT", "1h")
        assert len(result) == 0
        assert list(result.columns) == ["timestamp", "open", "high", "low", "close", "volume"]

    def test_fetch_wrong_symbol(self, db_manager):
        """Returns empty DataFrame for symbol that doesn't exist."""
        df = _make_ohlcv_df(5, base_ts=datetime(2024, 1, 1, tzinfo=timezone.utc))
        db_manager.upsert_ohlcv(df, "BTC/USDT", "1h")

        result = db_manager.fetch_ohlcv("ETH/USDT", "1h")
        assert len(result) == 0

    def test_fetch_wrong_timeframe(self, db_manager):
        """Returns empty DataFrame for timeframe that doesn't exist."""
        df = _make_ohlcv_df(5, base_ts=datetime(2024, 1, 1, tzinfo=timezone.utc))
        db_manager.upsert_ohlcv(df, "BTC/USDT", "1h")

        result = db_manager.fetch_ohlcv("BTC/USDT", "4h")
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Fetch OHLCV — filters
# ---------------------------------------------------------------------------


class TestFetchOHLCVFilters:
    def test_fetch_ascending_order(self, db_manager):
        """Default ascending=True returns candles oldest-first."""
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        df = _make_ohlcv_df(10, base_ts=base, step_hours=1)
        db_manager.upsert_ohlcv(df, "BTC/USDT", "1h")

        result = db_manager.fetch_ohlcv("BTC/USDT", "1h", ascending=True)
        timestamps = result.index.tolist()
        assert timestamps == sorted(timestamps)

    def test_fetch_descending_order(self, db_manager):
        """ascending=False returns candles newest-first."""
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        df = _make_ohlcv_df(10, base_ts=base, step_hours=1)
        db_manager.upsert_ohlcv(df, "BTC/USDT", "1h")

        result = db_manager.fetch_ohlcv("BTC/USDT", "1h", ascending=False)
        timestamps = result.index.tolist()
        assert timestamps == sorted(timestamps, reverse=True)

    def test_fetch_limit(self, db_manager):
        """limit caps the number of returned candles."""
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        df = _make_ohlcv_df(20, base_ts=base, step_hours=1)
        db_manager.upsert_ohlcv(df, "BTC/USDT", "1h")

        result = db_manager.fetch_ohlcv("BTC/USDT", "1h", limit=5)
        assert len(result) == 5

    def test_fetch_limit_with_descending(self, db_manager):
        """limit works with descending order — gets most recent N candles."""
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        df = _make_ohlcv_df(20, base_ts=base, step_hours=1)
        db_manager.upsert_ohlcv(df, "BTC/USDT", "1h")

        result = db_manager.fetch_ohlcv("BTC/USDT", "1h", limit=5, ascending=False)
        assert len(result) == 5
        # Last 5 candles (most recent) when re-sorted ascending
        timestamps = result.index.tolist()
        expected = sorted(timestamps)
        assert timestamps == list(reversed(expected))

    def test_fetch_since(self, db_manager):
        """since filter returns candles on or after the given timestamp."""
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        df = _make_ohlcv_df(24, base_ts=base, step_hours=1)  # 24 candles
        db_manager.upsert_ohlcv(df, "BTC/USDT", "1h")

        since = base + timedelta(hours=12)
        result = db_manager.fetch_ohlcv("BTC/USDT", "1h", since=since)

        assert len(result) >= 12  # candles from hour 12 to hour 23
        for ts in result.index:
            assert ts >= since

    def test_fetch_until(self, db_manager):
        """until filter returns candles before the given timestamp."""
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        df = _make_ohlcv_df(24, base_ts=base, step_hours=1)
        db_manager.upsert_ohlcv(df, "BTC/USDT", "1h")

        until = base + timedelta(hours=12)
        result = db_manager.fetch_ohlcv("BTC/USDT", "1h", until=until)

        assert len(result) <= 12  # candles from hour 0 to hour 11
        for ts in result.index:
            assert ts <= until

    def test_fetch_since_and_until(self, db_manager):
        """Combined since + until returns candles within the range."""
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        df = _make_ohlcv_df(48, base_ts=base, step_hours=1)
        db_manager.upsert_ohlcv(df, "BTC/USDT", "1h")

        since = base + timedelta(hours=10)
        until = base + timedelta(hours=20)
        result = db_manager.fetch_ohlcv("BTC/USDT", "1h", since=since, until=until)

        for ts in result.index:
            assert ts >= since
            assert ts <= until
        assert len(result) > 0

    def test_fetch_limit_since_until_combined(self, db_manager):
        """All filters combined: limit + since + until + descending."""
        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        df = _make_ohlcv_df(100, base_ts=base, step_hours=1)
        db_manager.upsert_ohlcv(df, "BTC/USDT", "1h")

        since = base + timedelta(hours=40)
        until = base + timedelta(hours=80)
        result = db_manager.fetch_ohlcv(
            "BTC/USDT", "1h",
            limit=5,
            since=since,
            until=until,
            ascending=False,
        )
        assert len(result) == 5
        for ts in result.index:
            assert since <= ts <= until


# ---------------------------------------------------------------------------
# Metadata queries
# ---------------------------------------------------------------------------


class TestMetadataQueries:
    def test_get_latest_timestamp(self, db_manager):
        """Returns the most recent timestamp for a symbol/timeframe."""
        base = datetime(2024, 1, 5, tzinfo=timezone.utc)
        df = _make_ohlcv_df(10, base_ts=base, step_hours=1)
        db_manager.upsert_ohlcv(df, "BTC/USDT", "1h")

        latest = db_manager.get_latest_timestamp("BTC/USDT", "1h")
        expected = base + timedelta(hours=9)
        assert latest is not None
        assert latest.date() == expected.date()

    def test_get_latest_timestamp_empty(self, db_manager):
        """Returns None for non-existent symbol/timeframe."""
        result = db_manager.get_latest_timestamp("NONEXISTENT/USDT", "1h")
        assert result is None

    def test_get_latest_timestamp_different_timeframes(self, db_manager):
        """Latest timestamp is per symbol/timeframe combination."""
        base_1h = datetime(2024, 1, 1, tzinfo=timezone.utc)
        base_4h = datetime(2024, 6, 1, tzinfo=timezone.utc)

        df_1h = _make_ohlcv_df(10, base_ts=base_1h, step_hours=1)
        df_4h = _make_ohlcv_df(5, base_ts=base_4h, step_hours=4)

        db_manager.upsert_ohlcv(df_1h, "SOL/USDT", "1h")
        db_manager.upsert_ohlcv(df_4h, "SOL/USDT", "4h")

        latest_1h = db_manager.get_latest_timestamp("SOL/USDT", "1h")
        latest_4h = db_manager.get_latest_timestamp("SOL/USDT", "4h")

        assert latest_1h < latest_4h

    def test_get_available_symbols(self, db_manager):
        """Returns sorted list of distinct symbols."""
        df = _make_ohlcv_df(5, base_ts=datetime(2024, 1, 1, tzinfo=timezone.utc))
        db_manager.upsert_ohlcv(df, "ETH/USDT", "1h")
        db_manager.upsert_ohlcv(df, "BTC/USDT", "1h")
        db_manager.upsert_ohlcv(df, "SOL/USDT", "1h")

        symbols = db_manager.get_available_symbols()
        assert symbols == ["BTC/USDT", "ETH/USDT", "SOL/USDT"]

    def test_get_available_symbols_empty(self, db_manager):
        """Returns empty list when DB has no data."""
        symbols = db_manager.get_available_symbols()
        assert symbols == []

    def test_get_available_timeframes(self, db_manager):
        """Returns sorted list of distinct timeframes for a symbol."""
        df = _make_ohlcv_df(5, base_ts=datetime(2024, 1, 1, tzinfo=timezone.utc))
        db_manager.upsert_ohlcv(df, "BTC/USDT", "1h")
        db_manager.upsert_ohlcv(df, "BTC/USDT", "4h")
        db_manager.upsert_ohlcv(df, "BTC/USDT", "1d")

        timeframes = db_manager.get_available_timeframes("BTC/USDT")
        assert timeframes == ["1d", "1h", "4h"]

    def test_get_available_timeframes_nonexistent(self, db_manager):
        """Returns empty list for non-existent symbol."""
        timeframes = db_manager.get_available_timeframes("NONEXISTENT/USDT")
        assert timeframes == []

    def test_get_candle_count(self, db_manager):
        """Returns correct count of candles."""
        df = _make_ohlcv_df(25, base_ts=datetime(2024, 1, 1, tzinfo=timezone.utc))
        db_manager.upsert_ohlcv(df, "BTC/USDT", "1h")

        count = db_manager.get_candle_count("BTC/USDT", "1h")
        assert count == 25

    def test_get_candle_count_empty(self, db_manager):
        """Returns 0 for non-existent symbol/timeframe."""
        count = db_manager.get_candle_count("NONEXISTENT/USDT", "1h")
        assert count == 0

    def test_get_candle_count_multiple_timeframes(self, db_manager):
        """Counts are per symbol/timeframe combination."""
        df_1h = _make_ohlcv_df(10, base_ts=datetime(2024, 1, 1, tzinfo=timezone.utc))
        df_4h = _make_ohlcv_df(5, base_ts=datetime(2024, 1, 1, tzinfo=timezone.utc))

        db_manager.upsert_ohlcv(df_1h, "ETH/USDT", "1h")
        db_manager.upsert_ohlcv(df_4h, "ETH/USDT", "4h")

        assert db_manager.get_candle_count("ETH/USDT", "1h") == 10
        assert db_manager.get_candle_count("ETH/USDT", "4h") == 5


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_duplicate_inserts_not_duplicated(self, temp_db_manager):
        """Inserting the same data twice doesn't create duplicates."""
        df = _make_ohlcv_df(10, base_ts=datetime(2024, 1, 1, tzinfo=timezone.utc))
        temp_db_manager.upsert_ohlcv(df, "BTC/USDT", "1h")
        temp_db_manager.upsert_ohlcv(df, "BTC/USDT", "1h")

        count = temp_db_manager.get_candle_count("BTC/USDT", "1h")
        assert count == 10

    def test_bulk_duplicate_inserts_not_duplicated(self, temp_db_manager):
        """Bulk inserting the same data twice doesn't create duplicates."""
        df = _make_ohlcv_df(20, base_ts=datetime(2024, 1, 1, tzinfo=timezone.utc))
        temp_db_manager.bulk_upsert_ohlcv(df, "BTC/USDT", "1h")
        temp_db_manager.bulk_upsert_ohlcv(df, "BTC/USDT", "1h")

        count = temp_db_manager.get_candle_count("BTC/USDT", "1h")
        assert count == 20

    def test_partial_duplicate_bulk_upsert(self, temp_db_manager):
        """Bulk upsert with partially overlapping data keeps existing + adds new."""
        df1 = _make_ohlcv_df(10, base_ts=datetime(2024, 1, 1, tzinfo=timezone.utc), step_hours=1)
        df2 = _make_ohlcv_df(5, base_ts=datetime(2024, 1, 8, tzinfo=timezone.utc), step_hours=1)

        temp_db_manager.bulk_upsert_ohlcv(df1, "BTC/USDT", "1h")
        # df2 is non-overlapping, so all 5 should be inserted
        inserted = temp_db_manager.bulk_upsert_ohlcv(df2, "BTC/USDT", "1h")

        assert inserted == 5
        total = temp_db_manager.get_candle_count("BTC/USDT", "1h")
        assert total == 15

    def test_partial_duplicate_bulk_upsert_overlapping(self, temp_db_manager):
        """Bulk upsert with overlapping data only inserts new rows."""
        df1 = _make_ohlcv_df(10, base_ts=datetime(2024, 1, 1, tzinfo=timezone.utc), step_hours=1)
        # Overlapping: first 5 candles of df2 are same as last 5 of df1
        df2 = _make_ohlcv_df(10, base_ts=datetime(2024, 1, 1, 5, tzinfo=timezone.utc), step_hours=1)

        temp_db_manager.bulk_upsert_ohlcv(df1, "BTC/USDT", "1h")
        # Overlap at indices 5,6,7,8,9 from df1 → only 5 new from df2
        inserted = temp_db_manager.bulk_upsert_ohlcv(df2, "BTC/USDT", "1h")

        assert inserted == 5
        total = temp_db_manager.get_candle_count("BTC/USDT", "1h")
        assert total == 15

    def test_upsert_with_timestamp_as_int(self, db_manager):
        """DataFrame with integer timestamp index is handled correctly."""
        df = pd.DataFrame({
            "Open": [42000.0, 42100.0],
            "High": [42100.0, 42200.0],
            "Low": [41950.0, 42050.0],
            "Close": [42050.0, 42150.0],
            "Volume": [100.0, 110.0],
        })
        # Set index to integer milliseconds
        df.index = [1704067200000, 1704070800000]

        inserted = db_manager.upsert_ohlcv(df, "BTC/USDT", "1h")
        assert inserted == 2

    def test_upsert_single_candle(self, db_manager):
        """Single-row DataFrame inserts correctly."""
        df = _make_ohlcv_df(1, base_ts=datetime(2024, 1, 1, tzinfo=timezone.utc))
        inserted = db_manager.upsert_ohlcv(df, "BTC/USDT", "1h")
        assert inserted == 1

        result = db_manager.fetch_ohlcv("BTC/USDT", "1h")
        assert len(result) == 1
        assert result["close"].iloc[0] == 42050.0

    def test_persistence_across_sessions(self, temp_db_manager):
        """Data persists after closing and reopening the connection."""
        df = _make_ohlcv_df(10, base_ts=datetime(2024, 1, 1, tzinfo=timezone.utc))
        temp_db_manager.upsert_ohlcv(df, "BTC/USDT", "1h")
        assert temp_db_manager.get_candle_count("BTC/USDT", "1h") == 10

        # Reopen connection
        temp_db_manager._engine.dispose()
        temp_db_manager._engine = temp_db_manager._engine
        temp_db_manager._session_factory = sessionmaker(bind=temp_db_manager._engine, class_=Session, expire_on_commit=False)

        assert temp_db_manager.get_candle_count("BTC/USDT", "1h") == 10
        result = temp_db_manager.fetch_ohlcv("BTC/USDT", "1h")
        assert len(result) == 10

    def test_price_ordering_high_gte_low(self, db_manager):
        """High >= Low and Close within High/Low range is preserved."""
        df = _make_ohlcv_df(5, base_ts=datetime(2024, 1, 1, tzinfo=timezone.utc))
        db_manager.upsert_ohlcv(df, "BTC/USDT", "1h")

        result = db_manager.fetch_ohlcv("BTC/USDT", "1h")
        assert (result["high"] >= result["low"]).all()
        assert (result["close"] >= result["low"]).all()
        assert (result["close"] <= result["high"]).all()

    def test_timestamps_are_utc(self, db_manager):
        """All timestamps in fetched data are UTC."""
        df = _make_ohlcv_df(5, base_ts=datetime(2024, 1, 1, tzinfo=timezone.utc))
        db_manager.upsert_ohlcv(df, "BTC/USDT", "1h")

        result = db_manager.fetch_ohlcv("BTC/USDT", "1h")
        assert result.index.tz is not None  # type: ignore[attr-defined]
        assert str(result.index.tz) == "UTC"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# ORM model
# ---------------------------------------------------------------------------


class TestOhlcvRecord:
    def test_repr(self):
        """__repr__ returns readable string."""
        from datetime import datetime, timezone
        record = OhlcvRecord(
            symbol="BTC/USDT",
            timeframe="1h",
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open_price=42000.0,
            high=42100.0,
            low=41950.0,
            close=42050.0,
            volume=100.0,
        )
        assert "BTC/USDT" in repr(record)
        assert "1h" in repr(record)
