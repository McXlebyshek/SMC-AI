"""
Fetch recent OHLCV candles for live / real-time analysis.

Unlike fetch_history (which paginates over historical data),
this module provides a simple, single-call function to grab the
last N candles — ideal for live analysis pipelines.
"""

from typing import Optional

import pandas as pd
from loguru import logger

from data.bybit_client import BybitClient


# Maximum candles per request (Bybit API limit)
MAX_CANDLES_PER_REQUEST = 1000


def fetch_realtime(
    client: BybitClient,
    symbol: str,
    timeframe: str = "1h",
    limit: int = 100,
) -> pd.DataFrame:
    """Fetch the last N most recent candles for live analysis.

    Parameters
    ----------
    client : BybitClient
        Initialized BybitClient instance.
    symbol : str
        Trading pair, e.g. "BTC/USDT".
    timeframe : str
        Candle interval (e.g. "1m", "15m", "1h", "4h", "1d", "1W").
    limit : int
        Number of recent candles to return (max 1000 by default).
        Defaults to 100.

    Returns
    -------
    pd.DataFrame
        OHLCV data sorted chronologically (oldest first), indexed by timestamp.
        Columns: Open, High, Low, Close, Volume.
    """
    if limit <= 0:
        raise ValueError(f"limit must be positive, got {limit}")
    if limit > MAX_CANDLES_PER_REQUEST:
        logger.warning(
            f"Requested limit {limit} exceeds Bybit max ({MAX_CANDLES_PER_REQUEST}). "
            f"Capping to {MAX_CANDLES_PER_REQUEST}."
        )
        limit = MAX_CANDLES_PER_REQUEST

    raw = client.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

    if not raw:
        logger.warning(f"No realtime data returned for {symbol} [{timeframe}]")
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df.set_index("timestamp", inplace=True)
    df.rename(columns={c: c.capitalize() for c in ["open", "high", "low", "close", "volume"]}, inplace=True)
    df.sort_index(inplace=True)

    logger.info(f"Fetched {len(df)} realtime candles for {symbol} [{timeframe}]")
    return df  # type: ignore[return-value]
