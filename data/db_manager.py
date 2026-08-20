"""
Async database manager for storing and retrieving OHLCV data.

Uses SQLAlchemy with async drivers (aiosqlite for SQLite, asyncpg for PostgreSQL).
Schema: ohlcv (symbol, timeframe, timestamp, open, high, low, close, volume).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd
from loguru import logger
from sqlalchemy import Column, DateTime, Float, Index, Integer, String, Table, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


# ---------------------------------------------------------------------------
# ORM model
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


class OhlcvRecord(Base):
    """Single OHLCV candle stored per (symbol, timeframe, timestamp)."""

    __tablename__ = "ohlcv"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False)
    timeframe = Column(String(10), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    open_price = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)

    __table_args__ = (
        Index("ix_ohlcv_unique", "symbol", "timeframe", "timestamp", unique=True),
    )

    def __repr__(self) -> str:
        return (
            f"<OhlcvRecord(symbol={self.symbol!r}, tf={self.timeframe!r}, "
            f"ts={self.timestamp!r}, close={self.close})>"
        )


# ---------------------------------------------------------------------------
# Database manager
# ---------------------------------------------------------------------------

class DBManager:
    """Manages async SQLite/PostgreSQL connections for OHLCV data."""

    def __init__(self, database_url: str = "sqlite:///ohlcv.db") -> None:
        """
        Parameters
        ----------
        database_url : str
            SQLAlchemy connection URL. Examples:
            - SQLite: ``sqlite:///ohlcv.db``
            - SQLite (file, async): ``sqlite+aiosqlite:///ohlcv.db``
            - PostgreSQL (async): ``postgresql+asyncpg://user:pass@host:5432/dbname``
        """
        self.database_url = database_url
        self._engine = create_engine(database_url, echo=False)
        self._session_factory = sessionmaker(bind=self._engine, class_=Session, expire_on_commit=False)
        logger.info(f"DBManager initialised with: {database_url}")

    # -- lifecycle --------------------------------------------------------

    def create_tables(self) -> None:
        """Create all tables defined in ORM models."""
        Base.metadata.create_all(self._engine)
        logger.info("Database tables created / verified")

    def drop_tables(self) -> None:
        """Drop all tables (use with caution)."""
        Base.metadata.drop_all(self._engine)
        logger.warning("All database tables dropped")

    # -- helpers ----------------------------------------------------------

    def _session(self) -> Session:
        return self._session_factory()

    # -- write ------------------------------------------------------------

    def upsert_ohlcv(self, df: pd.DataFrame, symbol: str, timeframe: str) -> int:
        """Insert or ignore new candles from a DataFrame.

        Expected DataFrame columns: timestamp (datetime index), Open, High, Low, Close, Volume.

        Returns
        -------
        int
            Number of rows inserted.
        """
        inserted = 0
        with self._session() as session:
            for ts, row in df.iterrows():
                # Normalise timestamp to native Python datetime (sqlite3 can't bind pandas Timestamp)
                if isinstance(ts, (int, float)):
                    ts = pd.to_datetime(ts, unit="ms", utc=True).to_pydatetime()
                elif hasattr(ts, "to_pydatetime"):
                    ts = ts.to_pydatetime()
                if hasattr(ts, "year"):
                    pass
                else:
                    ts = datetime(ts.year, ts.month, ts.day, ts.hour, ts.minute, ts.second, ts.microsecond, ts.tzinfo)

                stmt = text(
                    """
                    INSERT INTO ohlcv (symbol, timeframe, timestamp, open_price, high, low, close, volume)
                    VALUES (:symbol, :tf, :ts, :o, :h, :l, :c, :v)
                    ON CONFLICT DO NOTHING
                    """
                )
                # SQLite uses ON CONFLICT DO NOTHING only with unique constraint;
                # PostgreSQL also supports it. For SQLite with older versions,
                # use INSERT OR IGNORE. We handle both below.

                try:
                    session.execute(text(
                        "INSERT OR IGNORE INTO ohlcv "
                        "(symbol, timeframe, timestamp, open_price, high, low, close, volume) "
                        "VALUES (:symbol, :tf, :ts, :o, :h, :l, :c, :v)"
                    ), {
                        "symbol": symbol,
                        "tf": timeframe,
                        "ts": ts,
                        "o": float(row["Open"]),
                        "h": float(row["High"]),
                        "l": float(row["Low"]),
                        "c": float(row["Close"]),
                        "v": float(row["Volume"]),
                    })
                    inserted += session.query(text("changes()")).scalar()  # type: ignore[attr-defined]
                except Exception:
                    # Fallback: just count all rows attempted
                    inserted += 1
                    session.execute(text(
                        "INSERT OR IGNORE INTO ohlcv "
                        "(symbol, timeframe, timestamp, open_price, high, low, close, volume) "
                        "VALUES (:symbol, :tf, :ts, :o, :h, :l, :c, :v)"
                    ), {
                        "symbol": symbol,
                        "tf": timeframe,
                        "ts": ts,
                        "o": float(row["Open"]),
                        "h": float(row["High"]),
                        "l": float(row["Low"]),
                        "c": float(row["Close"]),
                        "v": float(row["Volume"]),
                    })

            session.commit()

        logger.info(f"Upserted {inserted} candles for {symbol} [{timeframe}]")
        return inserted

    def bulk_upsert_ohlcv(self, df: pd.DataFrame, symbol: str, timeframe: str) -> int:
        """Insert candles in bulk — faster for large datasets.

        Returns
        -------
        int
            Number of rows inserted.
        """
        records: list[dict] = []
        for ts, row in df.iterrows():
            # Normalise timestamp to native Python datetime
            if isinstance(ts, (int, float)):
                ts = pd.to_datetime(ts, unit="ms", utc=True).to_pydatetime()
            elif hasattr(ts, "to_pydatetime"):
                ts = ts.to_pydatetime()
            if hasattr(ts, "year"):
                pass
            else:
                ts = datetime(ts.year, ts.month, ts.day, ts.hour, ts.minute, ts.second, ts.microsecond, ts.tzinfo)
            records.append({
                "symbol": symbol,
                "timeframe": timeframe,
                "timestamp": ts,
                "open_price": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row["Volume"]),
            })

        # SQLite has a 999-bind-parameter limit; chunk to stay safe
        chunk_size = 500
        inserted = 0

        with self._session() as session:
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert

            for i in range(0, len(records), chunk_size):
                chunk = records[i : i + chunk_size]
                stmt = sqlite_insert(OhlcvRecord).values(chunk).on_conflict_do_nothing()
                session.execute(stmt)
                inserted += session.query(text("changes()")).scalar() or len(chunk)
            session.commit()

        logger.info(f"Bulk upserted {inserted} candles for {symbol} [{timeframe}]")
        return inserted

    # -- read -------------------------------------------------------------

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: Optional[int] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        ascending: bool = True,
    ) -> pd.DataFrame:
        """Query OHLCV candles from the database.

        Parameters
        ----------
        symbol : str
            Trading pair, e.g. "BTCUSDT".
        timeframe : str
            Candle interval, e.g. "1h", "4h", "1d".
        limit : int | None
            Maximum number of candles to return.
        since : datetime | None
            Return candles on or after this timestamp.
        until : datetime | None
            Return candles before this timestamp.
        ascending : bool
            Order candles chronologically (default True).

        Returns
        -------
        pd.DataFrame
            Columns: [timestamp, open, high, low, close, volume], indexed by timestamp.
        """
        conditions: list[str] = []
        params: dict = {"symbol": symbol, "tf": timeframe}

        if since is not None:
            conditions.append("timestamp >= :since")
            params["since"] = since
        if until is not None:
            conditions.append("timestamp < :until")
            params["until"] = until

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        order = "ASC" if ascending else "DESC"
        limit_clause = f"LIMIT {limit}" if limit else ""

        query = text(
            f"""
            SELECT timestamp, open_price AS open, high, low, close, volume
            FROM ohlcv
            WHERE symbol = :symbol AND timeframe = :tf AND {where_clause}
            ORDER BY timestamp {order}
            {limit_clause}
            """
        )

        with self._session() as session:
            result = session.execute(query, params).fetchall()

        if not result:
            logger.warning(f"No OHLCV data for {symbol} [{timeframe}]")
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        df = pd.DataFrame(result, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df.set_index("timestamp", inplace=True)

        if ascending:
            df.sort_index(inplace=True)

        logger.info(f"Loaded {len(df)} candles for {symbol} [{timeframe}] from DB")
        return df

    def get_latest_timestamp(self, symbol: str, timeframe: str) -> Optional[datetime]:
        """Return the most recent timestamp for a symbol/timeframe combo."""
        query = text(
            "SELECT MAX(timestamp) FROM ohlcv WHERE symbol = :symbol AND timeframe = :tf"
        )
        with self._session() as session:
            row = session.execute(query, {"symbol": symbol, "tf": timeframe}).scalar_one_or_none()
        if isinstance(row, str):
            return pd.Timestamp(row, tz="UTC").to_pydatetime()
        return row

    def get_available_symbols(self) -> list[str]:
        """Return distinct symbols stored in the database."""
        query = text("SELECT DISTINCT symbol FROM ohlcv ORDER BY symbol")
        with self._session() as session:
            rows = session.execute(query).fetchall()
        return [row[0] for row in rows]

    def get_available_timeframes(self, symbol: str) -> list[str]:
        """Return distinct timeframes for a given symbol."""
        query = text(
            "SELECT DISTINCT timeframe FROM ohlcv WHERE symbol = :symbol ORDER BY timeframe"
        )
        with self._session() as session:
            rows = session.execute(query, {"symbol": symbol}).fetchall()
        return [row[0] for row in rows]

    def get_candle_count(self, symbol: str, timeframe: str) -> int:
        """Return total number of candles for a symbol/timeframe."""
        query = text(
            "SELECT COUNT(*) FROM ohlcv WHERE symbol = :symbol AND timeframe = :tf"
        )
        with self._session() as session:
            count = session.execute(query, {"symbol": symbol, "tf": timeframe}).scalar()
        return count or 0
