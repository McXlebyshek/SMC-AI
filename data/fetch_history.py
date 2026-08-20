"""
Fetch historical OHLCV data with pagination for backtesting.

Bybit's API returns a maximum of 1000 candles per request,
so we paginate backwards from now until we have enough data
or reach the requested start date.
"""

from datetime import datetime, timedelta, timezone
import time
from typing import List, Optional

import pandas as pd
from loguru import logger

from data.bybit_client import BybitClient


# Maximum candles per request (Bybit API limit)
MAX_CANDLES_PER_REQUEST = 1000

# Cooldown between requests to respect rate limits (seconds)
REQUEST_COOLDOWN = 0.5


def _candle_duration_ms(timeframe: str) -> int:
    """Convert a timeframe string to milliseconds per candle."""
    multipliers = {
        "1m": 60_000,
        "5m": 300_000,
        "15m": 900_000,
        "30m": 1_800_000,
        "1h": 3_600_000,
        "2h": 7_200_000,
        "4h": 14_400_000,
        "12h": 43_200_000,
        "1d": 86_400_000,
        "1W": 604_800_000,
    }
    if timeframe not in multipliers:
        raise ValueError(f"Unsupported timeframe: {timeframe}. Supported: {list(multipliers.keys())}")
    return multipliers[timeframe]


def fetch_history(
    client: BybitClient,
    symbol: str,
    timeframe: str = "1h",
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    limit: Optional[int] = None,
) -> pd.DataFrame:
    """Download historical OHLCV data for a symbol with automatic pagination.

    Works backwards from `end` (or now) in chunks of `MAX_CANDLES_PER_REQUEST`,
    accumulating results until the requested range is fully covered.

    Parameters
    ----------
    client : BybitClient
        Initialized BybitClient instance.
    symbol : str
        Trading pair, e.g. "BTC/USDT".
    timeframe : str
        Candle interval (e.g. "1m", "15m", "1h", "4h", "1d", "1W").
    start : datetime | None
        Inclusive start of the desired range. If None, no lower bound.
    end : datetime | None
        Exclusive end of the desired range. If None, defaults to now.
    limit : int | None
        Hard cap on the total number of candles to fetch.
        If None, fetches until `start` or the beginning of exchange data.

    Returns
    -------
    pd.DataFrame
        OHLCV data sorted chronologically (oldest first), indexed by timestamp.
        Columns: Open, High, Low, Close, Volume.
    """
    if end is None:
        end = datetime.now(timezone.utc)

    end_ts = int(end.timestamp() * 1000)
    start_ts = int(start.timestamp() * 1000) if start else None

    all_records: List[list] = []
    current_since = end_ts
    total_fetched = 0

    logger.info(f"Fetching history for {symbol} [{timeframe}] from {start or 'beginning'} to {end}")

    while True:
        # Apply per-request limit
        remaining = limit - total_fetched if limit else MAX_CANDLES_PER_REQUEST
        request_limit = min(MAX_CANDLES_PER_REQUEST, remaining)

        raw = client.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=request_limit, since=current_since)

        if not raw:
            break

        all_records.extend(raw)
        total_fetched += len(raw)

        oldest_ts = raw[0][0]  # First candle in this batch is the oldest

        # Stop if we've reached the start boundary
        if start_ts is not None and oldest_ts <= start_ts:
            break

        # Stop if we've hit the global limit
        if limit is not None and total_fetched >= limit:
            break

        # Prepare for next page: fetch before the oldest candle of this batch
        current_since = oldest_ts - 1

        # Brief cooldown to respect rate limits
        time.sleep(REQUEST_COOLDOWN)

    if not all_records:
        logger.warning(f"No data returned for {symbol} [{timeframe}]")
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    # Deduplicate by timestamp (Bybit can return overlapping candles on boundary)
    seen_timestamps = set()
    deduped = []
    for record in all_records:
        ts = record[0]
        if ts not in seen_timestamps:
            seen_timestamps.add(ts)
            deduped.append(record)

    df = pd.DataFrame(deduped, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df.set_index("timestamp", inplace=True)
    df.rename(columns={c: c.capitalize() for c in ["open", "high", "low", "close", "volume"]}, inplace=True)

    # Filter by start boundary (inclusive)
    if start_ts is not None:
        df = df[df.index >= datetime.fromtimestamp(start_ts / 1000, tz=timezone.utc)]

    # Enforce global limit
    if limit is not None and len(df) > limit:
        df = df.iloc[:limit]

    df.sort_index(inplace=True)

    logger.info(f"Fetched {len(df)} candles for {symbol} [{timeframe}]")
    return df  # type: ignore[return-value]


def fetch_all_symbols(
    client: BybitClient,
    symbols: List[str],
    timeframes: List[str],
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    per_symbol_limit: Optional[int] = None,
) -> dict:
    """Download history for multiple symbols and timeframes.

    Parameters
    ----------
    client : BybitClient
        Initialized BybitClient instance.
    symbols : list[str]
        Trading pairs, e.g. ["BTC/USDT", "ETH/USDT"].
    timeframes : list[str]
        Time intervals, e.g. ["1h", "4h", "1d"].
    start : datetime | None
        Inclusive start of the range.
    end : datetime | None
        Exclusive end of the range.
    per_symbol_limit : int | None
        Max candles per symbol/timeframe combination.

    Returns
    -------
    dict
        Nested dict: {symbol: {timeframe: DataFrame}}.
    """
    results: dict = {}

    for symbol in symbols:
        results[symbol] = {}
        for timeframe in timeframes:
            try:
                df = fetch_history(
                    client,
                    symbol=symbol,
                    timeframe=timeframe,
                    start=start,
                    end=end,
                    limit=per_symbol_limit,
                )
                results[symbol][timeframe] = df
            except Exception as exc:
                logger.error(f"Failed to fetch {symbol} [{timeframe}]: {exc}")
                results[symbol][timeframe] = pd.DataFrame()

    return results
