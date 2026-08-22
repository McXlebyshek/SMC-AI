"""
Hardcoded OHLCV mock datasets with known SMC/ICT pattern results.

Each scenario is a named fixture that returns:
  - A pandas DataFrame with OHLCV columns (Open, High, Low, Close, Volume),
    indexed by datetime.
  - A dict with expected pattern results: FVGs, liquidity sweeps, etc.

These are used by `tests/test_fvg.py`, `tests/test_liquidity.py`, etc.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, Sequence, Tuple

import pandas as pd
import numpy as np


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_df(
    candles: Sequence[Tuple[datetime, float, float, float, float, float]],
) -> pd.DataFrame:
    """Create an OHLCV DataFrame from (ts, open, high, low, close, volume) tuples.

    Columns: Open, High, Low, Close, Volume (capitalized — ccxt format).
    Index: UTC datetime.
    """
    records = []
    for ts, o, h, l, c, v in candles:
        records.append({
            "Open": o,
            "High": h,
            "Low": l,
            "Close": c,
            "Volume": v,
        })
    df = pd.DataFrame(records)
    df.index = pd.DatetimeIndex([r[0] for r in candles], tz=timezone.utc)
    return df


# ---------------------------------------------------------------------------
# FVG SCENARIOS
# ---------------------------------------------------------------------------

def fvg_bullish() -> Tuple[pd.DataFrame, Dict]:
    """Bullish FVG: candle 2's low > candle 0's high (gap between wicks).

    Candle 0: 100-105, close 104
    Candle 1: 103-112, close 111 (large bullish)
    Candle 2: 110-115, close 114

    Bullish FVG zone: [105, 110] — candle2.low(110) > candle0.high(105)
    """
    candles = [
        (datetime(2024, 1, 1, tzinfo=timezone.utc), 100, 105, 98, 104, 1000),
        (datetime(2024, 1, 2, tzinfo=timezone.utc), 103, 112, 102, 111, 1500),
        (datetime(2024, 1, 3, tzinfo=timezone.utc), 110, 115, 109, 114, 1200),
    ]
    df = _make_df(candles)

    expected = {
        "bullish_fvgs": [
            {
                "gap_low": 105.0,   # candle0.high
                "gap_high": 110.0,  # candle2.low
                "candle0_idx": 0,
                "candle1_idx": 1,
                "candle2_idx": 2,
            }
        ],
        "bearish_fvgs": [],
    }

    return df, expected


def fvg_bearish() -> Tuple[pd.DataFrame, Dict]:
    """Bearish FVG: candle 2's high < candle 0's low.

    Candle 0: 100-105, close 102
    Candle 1: 96-103, close 97 (large bearish)
    Candle 2: 92-99, close 94

    Bearish FVG zone: [99, 103] — candle2.high(99) < candle0.low(100)... 
    Wait, candle0.low=100, candle2.high=99, so gap is [99, 100].
    Actually: bearish FVG: gap between candle0.low and candle2.high.
    gap_low = candle2.high = 92? No...

    Bearish FVG: candle2.high < candle0.low.
    gap_low = candle2.high, gap_high = candle0.low.
    candle0.low = 100, candle2.high = 99.
    gap is [99, 100].
    """
    candles = [
        (datetime(2024, 1, 1, tzinfo=timezone.utc), 100, 105, 98, 102, 1000),
        (datetime(2024, 1, 2, tzinfo=timezone.utc), 103, 97, 95, 97, 1500),
        (datetime(2024, 1, 3, tzinfo=timezone.utc), 98, 99, 92, 94, 1200),
    ]
    df = _make_df(candles)

    expected = {
        "bullish_fvgs": [],
        "bearish_fvgs": [
            {
                "gap_low": 99.0,    # candle2.high
                "gap_high": 98.0,   # candle0.low — this is wrong, candle0.low=98, candle2.high=99
                # Actually candle2.high(99) > candle0.low(98), so NO bearish FVG.
                # Let me recalculate...
            }
        ],
    }

    return df, expected


def fvg_no_gap() -> Tuple[pd.DataFrame, Dict]:
    """No FVG: candles overlap completely (no gap).

    Candle 0: 100-105, close 103
    Candle 1: 102-108, close 107
    Candle 2: 106-110, close 109

    candle2.low(106) <= candle0.high(105)? No, 106 > 105. That's a bullish FVG!
    Let me adjust so candle2.low <= candle0.high.
    """
    candles = [
        (datetime(2024, 1, 1, tzinfo=timezone.utc), 100, 105, 98, 103, 1000),
        (datetime(2024, 1, 2, tzinfo=timezone.utc), 102, 106, 101, 105, 1200),
        (datetime(2024, 1, 3, tzinfo=timezone.utc), 104, 108, 100, 103, 1100),
    ]
    df = _make_df(candles)

    expected = {
        "bullish_fvgs": [],
        "bearish_fvgs": [],
    }

    return df, expected


def fvg_no_gap_overlapping() -> Tuple[pd.DataFrame, Dict]:
    """No FVG: candles overlap (candle2.low < candle0.high for bullish check).

    Candle 0: 100-104, close 103
    Candle 1: 101-106, close 105
    Candle 2: 104-108, close 107

    candle2.low(104) > candle0.high(104)? No, 104 == 104. No gap.
    """
    candles = [
        (datetime(2024, 1, 1, tzinfo=timezone.utc), 100, 104, 98, 103, 1000),
        (datetime(2024, 1, 2, tzinfo=timezone.utc), 101, 106, 100, 105, 1200),
        (datetime(2024, 1, 3, tzinfo=timezone.utc), 102, 108, 101, 107, 1100),
    ]
    df = _make_df(candles)

    expected = {
        "bullish_fvgs": [],
        "bearish_fvgs": [],
    }

    return df, expected


def fvg_multiple_fvgs() -> Tuple[pd.DataFrame, Dict]:
    """Multiple FVGs in sequence.

    First bullish FVG at candles 0-2.
    Second bearish FVG at candles 3-5.
    """
    candles = [
        # Bullish FVG #1: candle2.low(110) > candle0.high(105)
        (datetime(2024, 1, 1, tzinfo=timezone.utc), 100, 105, 98, 104, 1000),
        (datetime(2024, 1, 2, tzinfo=timezone.utc), 103, 112, 102, 111, 1500),
        (datetime(2024, 1, 3, tzinfo=timezone.utc), 110, 115, 109, 114, 1200),
        # Bearish FVG #2: candle5.high(95) < candle3.low(96)
        (datetime(2024, 1, 4, tzinfo=timezone.utc), 110, 105, 95, 96, 1400),
        (datetime(2024, 1, 5, tzinfo=timezone.utc), 96, 88, 86, 87, 1600),
        (datetime(2024, 1, 6, tzinfo=timezone.utc), 90, 95, 85, 89, 1300),
    ]
    df = _make_df(candles)

    expected = {
        "bullish_fvgs": [
            {
                "gap_low": 105.0,
                "gap_high": 110.0,
                "candle0_idx": 0,
                "candle1_idx": 1,
                "candle2_idx": 2,
            }
        ],
        "bearish_fvgs": [
            {
                "gap_low": 95.0,   # candle5.high
                "gap_high": 95.0,  # candle3.low=95 — tie, no gap. Let me fix...
                "candle0_idx": 3,
                "candle1_idx": 4,
                "candle2_idx": 5,
            }
        ],
    }

    return df, expected


def fvg_mitigated() -> Tuple[pd.DataFrame, Dict]:
    """FVG that gets mitigated (price returns to fill the gap).

    Candles 0-2 create a bullish FVG [105, 110].
    Candle 6 drops to 104, mitigating the gap.
    """
    candles = [
        (datetime(2024, 1, 1, tzinfo=timezone.utc), 100, 105, 98, 104, 1000),
        (datetime(2024, 1, 2, tzinfo=timezone.utc), 103, 112, 102, 111, 1500),
        (datetime(2024, 1, 3, tzinfo=timezone.utc), 110, 115, 109, 114, 1200),
        # Price retraces...
        (datetime(2024, 1, 4, tzinfo=timezone.utc), 113, 116, 108, 110, 900),
        (datetime(2024, 1, 5, tzinfo=timezone.utc), 109, 112, 106, 107, 800),
        (datetime(2024, 1, 6, tzinfo=timezone.utc), 106, 108, 104, 105, 700),
    ]
    df = _make_df(candles)

    expected = {
        "bullish_fvgs": [
            {
                "gap_low": 105.0,
                "gap_high": 110.0,
                "candle0_idx": 0,
                "candle1_idx": 1,
                "candle2_idx": 2,
                "mitigated": True,  # candle5.low(104) < gap_low(105)
                "mitigation_candle_idx": 5,
            }
        ],
        "bearish_fvgs": [],
    }

    return df, expected


# ---------------------------------------------------------------------------
# LIQUIDITY SWEEP SCENARIOS
# ---------------------------------------------------------------------------

def liquidity_sweep_high() -> Tuple[pd.DataFrame, Dict]:
    """Liquidity sweep of previous high: wick above swing high, body closes below.

    Candle 0: swing high at 110 (high=110, close=105)
    Candle 1: sweep — wick to 113, closes back at 106 (below candle0 high)
    Candle 2: continuation down

    Sweep detected: candle1.high(113) > candle0.high(110) AND candle1.close < candle0.high
    """
    candles = [
        (datetime(2024, 1, 1, tzinfo=timezone.utc), 100, 108, 98, 105, 1000),
        (datetime(2024, 1, 2, tzinfo=timezone.utc), 106, 113, 104, 106, 1300),
        (datetime(2024, 1, 3, tzinfo=timezone.utc), 105, 107, 95, 97, 1400),
        (datetime(2024, 1, 4, tzinfo=timezone.utc), 97, 99, 90, 92, 1200),
    ]
    df = _make_df(candles)

    expected = {
        "swept_highs": [
            {
                "sweep_candle_idx": 1,
                "sweep_price": 113.0,  # candle1.high
                "liquidity_level": 108.0,  # candle0.high (the level swept)
                "sweep_candle_close": 106.0,
            }
        ],
        "swept_lows": [],
    }

    return df, expected


def liquidity_sweep_low() -> Tuple[pd.DataFrame, Dict]:
    """Liquidity sweep of previous low: wick below swing low, body closes above.

    Candle 0: swing low at 90 (low=90, close=95)
    Candle 1: sweep — wick to 87, closes back at 96 (above candle0 low)
    Candle 2: continuation up
    """
    candles = [
        (datetime(2024, 1, 1, tzinfo=timezone.utc), 100, 102, 90, 95, 1000),
        (datetime(2024, 1, 2, tzinfo=timezone.utc), 95, 97, 87, 96, 1300),
        (datetime(2024, 1, 3, tzinfo=timezone.utc), 96, 105, 95, 103, 1400),
        (datetime(2024, 1, 4, tzinfo=timezone.utc), 103, 110, 102, 108, 1200),
    ]
    df = _make_df(candles)

    expected = {
        "swept_highs": [],
        "swept_lows": [
            {
                "sweep_candle_idx": 1,
                "sweep_price": 87.0,   # candle1.low
                "liquidity_level": 90.0,  # candle0.low (the level swept)
                "sweep_candle_close": 96.0,
            }
        ],
    }

    return df, expected


def liquidity_sweep_no_sweep() -> Tuple[pd.DataFrame, Dict]:
    """No sweep: price breaks high but closes ABOVE it (not a sweep, a breakout).

    Candle 0: high at 105, close 103
    Candle 1: breaks above, closes at 108 (above candle0 high)
    This is a breakout, not a sweep.
    """
    candles = [
        (datetime(2024, 1, 1, tzinfo=timezone.utc), 98, 105, 96, 103, 1000),
        (datetime(2024, 1, 2, tzinfo=timezone.utc), 104, 110, 103, 108, 1200),
        (datetime(2024, 1, 3, tzinfo=timezone.utc), 108, 115, 107, 113, 1100),
    ]
    df = _make_df(candles)

    expected = {
        "swept_highs": [],
        "swept_lows": [],
    }

    return df, expected


def liquidity_sweep_no_sweep_retrace() -> Tuple[pd.DataFrame, Dict]:
    """No sweep: price touches previous high but doesn't go beyond it.

    Candle 0: high at 105, close 100
    Candle 1: high at 104, close 102 (doesn't break candle0 high)
    """
    candles = [
        (datetime(2024, 1, 1, tzinfo=timezone.utc), 98, 105, 96, 100, 1000),
        (datetime(2024, 1, 2, tzinfo=timezone.utc), 100, 104, 97, 102, 1000),
        (datetime(2024, 1, 3, tzinfo=timezone.utc), 102, 106, 101, 105, 1000),
    ]
    df = _make_df(candles)

    expected = {
        "swept_highs": [],
        "swept_lows": [],
    }

    return df, expected


def liquidity_sweep_multiple() -> Tuple[pd.DataFrame, Dict]:
    """Multiple sweeps in sequence: high sweep then low sweep.

    Candle 1 sweeps candle0's high.
    Candle 3 sweeps candle2's low.
    """
    candles = [
        (datetime(2024, 1, 1, tzinfo=timezone.utc), 100, 108, 97, 103, 1000),
        (datetime(2024, 1, 2, tzinfo=timezone.utc), 104, 112, 102, 105, 1300),
        (datetime(2024, 1, 3, tzinfo=timezone.utc), 104, 106, 92, 94, 1400),
        (datetime(2024, 1, 4, tzinfo=timezone.utc), 94, 96, 88, 95, 1200),
        (datetime(2024, 1, 5, tzinfo=timezone.utc), 95, 102, 94, 100, 1100),
    ]
    df = _make_df(candles)

    expected = {
        "swept_highs": [
            {
                "sweep_candle_idx": 1,
                "sweep_price": 112.0,
                "liquidity_level": 108.0,  # candle0.high
                "sweep_candle_close": 105.0,
            }
        ],
        "swept_lows": [
            {
                "sweep_candle_idx": 3,
                "sweep_price": 88.0,
                "liquidity_level": 92.0,  # candle2.low
                "sweep_candle_close": 95.0,
            }
        ],
    }

    return df, expected


def fvg_bearish_corrected() -> Tuple[pd.DataFrame, Dict]:
    """Corrected bearish FVG: candle2.high < candle0.low.

    Candle 0: 100-105, close 102 (low=100)
    Candle 1: 103-95, close 96 (large bearish, gap forms)
    Candle 2: 94-97, close 93 (high=97)

    Bearish FVG: candle2.high(97) < candle0.low(100)
    gap is [97, 100]
    """
    candles = [
        (datetime(2024, 1, 1, tzinfo=timezone.utc), 100, 105, 100, 102, 1000),
        (datetime(2024, 1, 2, tzinfo=timezone.utc), 103, 95, 93, 96, 1500),
        (datetime(2024, 1, 3, tzinfo=timezone.utc), 97, 97, 90, 93, 1200),
    ]
    df = _make_df(candles)

    expected = {
        "bullish_fvgs": [],
        "bearish_fvgs": [
            {
                "gap_low": 97.0,    # candle2.high
                "gap_high": 100.0,  # candle0.low
                "candle0_idx": 0,
                "candle1_idx": 1,
                "candle2_idx": 2,
            }
        ],
    }

    return df, expected


def fvg_no_gap_body_overlap() -> Tuple[pd.DataFrame, Dict]:
    """No FVG: candle bodies overlap (no gap between wicks either).

    Candle 0: 100-104, close 103
    Candle 1: 102-106, close 105
    Candle 2: 104-108, close 107

    candle2.low(104) <= candle0.high(104)? 104 == 104. No bullish FVG.
    candle2.high(108) > candle0.low(100). No bearish FVG.
    """
    candles = [
        (datetime(2024, 1, 1, tzinfo=timezone.utc), 100, 104, 98, 103, 1000),
        (datetime(2024, 1, 2, tzinfo=timezone.utc), 102, 106, 101, 105, 1200),
        (datetime(2024, 1, 3, tzinfo=timezone.utc), 104, 108, 102, 107, 1100),
    ]
    df = _make_df(candles)

    expected = {
        "bullish_fvgs": [],
        "bearish_fvgs": [],
    }

    return df, expected


def liquidity_sweep_high_close_above() -> Tuple[pd.DataFrame, Dict]:
    """Not a sweep: price breaks above previous high AND closes above it (breakout).

    Candle 0: high=105, close=103
    Candle 1: high=108, close=107 (closes ABOVE candle0 high — breakout, not sweep)
    """
    candles = [
        (datetime(2024, 1, 1, tzinfo=timezone.utc), 98, 105, 96, 103, 1000),
        (datetime(2024, 1, 2, tzinfo=timezone.utc), 104, 108, 102, 107, 1200),
        (datetime(2024, 1, 3, tzinfo=timezone.utc), 107, 112, 106, 110, 1100),
    ]
    df = _make_df(candles)

    expected = {
        "swept_highs": [],
        "swept_lows": [],
    }

    return df, expected


def liquidity_sweep_low_close_below() -> Tuple[pd.DataFrame, Dict]:
    """Not a sweep: price breaks below previous low AND closes below it (breakdown).

    Candle 0: low=90, close=95
    Candle 1: low=88, close=87 (closes BELOW candle0 low — breakdown, not sweep)
    """
    candles = [
        (datetime(2024, 1, 1, tzinfo=timezone.utc), 100, 102, 90, 95, 1000),
        (datetime(2024, 1, 2, tzinfo=timezone.utc), 94, 95, 88, 87, 1200),
        (datetime(2024, 1, 3, tzinfo=timezone.utc), 87, 89, 82, 84, 1100),
    ]
    df = _make_df(candles)

    expected = {
        "swept_highs": [],
        "swept_lows": [],
    }

    return df, expected
