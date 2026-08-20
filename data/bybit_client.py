"""
Bybit client wrapper around ccxt for fetching OHLCV and market data.
"""

from typing import Optional

import ccxt
import pandas as pd
from loguru import logger


class BybitClient:
    """Client for Bybit exchange via ccxt."""

    def __init__(self, api_key: str = "", secret: str = "", has_rate_limit: bool = True) -> None:
        self.exchange = ccxt.bybit({
            "apiKey": api_key or "",
            "secret": secret or "",
            "enableRateLimit": has_rate_limit,
            "options": {
                "defaultType": "spot",
            },
        })
        logger.info("BybitClient initialized")

    def check_connection(self) -> bool:
        """Test the connection to Bybit and return True on success."""
        try:
            self.exchange.load_markets()
            logger.info("Bybit connection verified — markets loaded")
            return True
        except Exception as exc:
            logger.error(f"Bybit connection failed: {exc}")
            return False

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 1000,
        since: Optional[int] = None,
    ) -> pd.DataFrame:
        """Fetch OHLCV candlestick data for a given symbol.

        Parameters
        ----------
        symbol : str
            Trading pair, e.g. "BTC/USDT".
        timeframe : str
            Candle interval, e.g. "1m", "15m", "1h", "4h", "1d".
        limit : int
            Number of candles to fetch (max 1000 by default).
        since : int | None
            Start timestamp in ms. If None, fetches the most recent `limit` candles.

        Returns
        -------
        pd.DataFrame
            Columns: [timestamp, open, high, low, close, volume], indexed by timestamp.
        """
        raw = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit, since=since)
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
        df.rename(columns={c: c.capitalize() for c in ["open", "high", "low", "close", "volume"]}, inplace=True)
        logger.debug(f"Fetched {len(df)} candles for {symbol} [{timeframe}]")
        return df
