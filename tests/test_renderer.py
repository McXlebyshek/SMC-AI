"""
Visual regression tests for chart renderer -- generates real BTC 1D charts.

Fetches live BTC/USDT 1D data from Bybit, renders candlestick charts with
mplfinance, and saves PNG files to tests/output/ for manual inspection.

Run:
    python -m pytest tests/test_renderer.py -v
    python tests/test_renderer.py           (direct execution)
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from render.renderer import render_candlestick

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fetch_btc_1d():
    """Fetch the latest 500 BTC/USDT 1D candles from Bybit (live API)."""
    from data.bybit_client import BybitClient

    client = BybitClient()
    df = client.fetch_ohlcv("BTC/USDT", timeframe="1d", limit=500)
    return df


def _fetch_btc_1h():
    """Fetch the latest 500 BTC/USDT 1H candles from Bybit (live API)."""
    from data.bybit_client import BybitClient

    client = BybitClient()
    df = client.fetch_ohlcv("BTC/USDT", timeframe="1h", limit=500)
    return df


def _generate_mock_ohlcv(n=120, freq="1D"):
    """Create synthetic OHLCV with a clear trend pattern."""
    import numpy as np

    np.random.seed(42)
    base_ts = pd.Timestamp("2025-01-01", tz="UTC")
    dates = pd.date_range(base_ts, periods=n, freq=freq)

    prices = []
    p = 40000.0
    for i in range(n):
        trend = 200 * np.sin(i / 15)
        noise = np.random.randn() * 300
        p += 100 + trend + noise
        p = max(p, 30000)
        o = p + np.random.randn() * 100
        c = p + np.random.randn() * 200
        h = max(o, c) + abs(np.random.randn() * 500)
        l = min(o, c) - abs(np.random.randn() * 500)
        prices.append({"Open": o, "High": h, "Low": l, "Close": c, "Volume": 500 + np.random.randn() * 100})

    df = pd.DataFrame(prices)
    df.index = dates
    return df


def _get_session_defs():
    """Load session definitions from symbols.yaml."""
    import yaml

    config_path = PROJECT_ROOT / "config" / "symbols.yaml"
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    return cfg.get("analysis", {}).get("sessions", {})


def _render_session_chart(df, filename, session_defs):
    """Render a chart with session backgrounds."""
    import matplotlib.pyplot as plt
    import mplfinance as mpf
    from render.chart_config import DEFAULT_CONFIG
    from render.sessions import render_sessions

    cc = DEFAULT_CONFIG.colors
    vol = DEFAULT_CONFIG.volume

    marketcolors = mpf.make_marketcolors(
        up=cc.bullish, down=cc.bearish,
        edge={"up": cc.bullish_edge, "down": cc.bearish_edge},
        wick={"up": cc.bullish_wick, "down": cc.bearish_wick},
        ohlc={"up": cc.bullish, "down": cc.bearish},
        volume={"up": vol.up_color, "down": vol.down_color},
        vcdopcod=True, alpha=vol.alpha,
    )
    mpl_style = mpf.make_mpf_style(
        marketcolors=marketcolors,
        facecolor=DEFAULT_CONFIG.style.facecolor,
        gridcolor=DEFAULT_CONFIG.style.gridcolor,
        gridstyle=DEFAULT_CONFIG.style.gridstyle,
        gridaxis=DEFAULT_CONFIG.style.gridaxis,
    )

    fig, axes = mpf.plot(
        df, type="candle", mav=(5, 20), volume=True,
        figsize=(14, 8), style=mpl_style,
        returnfig=True, tight_layout=True,
        scale_padding={
            "top": DEFAULT_CONFIG.margins.top,
            "bottom": DEFAULT_CONFIG.margins.bottom,
            "left": DEFAULT_CONFIG.margins.left,
            "right": DEFAULT_CONFIG.margins.right,
        },
    )

    ax_price = axes[0] if isinstance(axes, (list, tuple)) else axes[0]
    render_sessions(ax_price, df, session_defs, alpha=0.12)

    out = OUTPUT_DIR / filename
    fig.savefig(str(out), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def _render_dark_chart(df, filename):
    """Render a chart with dark background."""
    import matplotlib.pyplot as plt
    import mplfinance as mpf
    from render.chart_config import DEFAULT_CONFIG

    cc = DEFAULT_CONFIG.colors
    vol = DEFAULT_CONFIG.volume

    marketcolors = mpf.make_marketcolors(
        up=cc.bullish, down=cc.bearish,
        edge={"up": cc.bullish_edge, "down": cc.bearish_edge},
        wick={"up": cc.bullish_wick, "down": cc.bearish_wick},
        ohlc={"up": cc.bullish, "down": cc.bearish},
        volume={"up": vol.up_color, "down": vol.down_color},
        vcdopcod=True, alpha=vol.alpha,
    )
    mpl_style = mpf.make_mpf_style(
        marketcolors=marketcolors,
        facecolor="#1a1a2e",
        gridcolor="#333333",
        gridstyle="-",
        gridaxis="both",
    )

    fig, axes = mpf.plot(
        df, type="candle", mav=(5, 20), volume=True,
        figsize=(14, 8), style=mpl_style,
        returnfig=True, tight_layout=True,
    )

    out = OUTPUT_DIR / filename
    fig.savefig(str(out), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


# ---------------------------------------------------------------------------
# Tests -- live data charts
# ---------------------------------------------------------------------------


class TestLiveBTCCharts:
    """Render charts from real BTC/USDT 1D data."""

    @classmethod
    def setup_class(cls):
        """Fetch data once for all tests in this class."""
        cls.btc_df = _fetch_btc_1d()
        cls.session_defs = _get_session_defs()

    def test_01_basic_candlestick(self):
        """Basic candlestick chart from live BTC 1D data."""
        df = self.btc_df.tail(90).copy()
        out = OUTPUT_DIR / "btc_1d_basic.png"
        path = render_candlestick(df, output_path=out, config=None)
        assert path.exists()
        assert path.stat().st_size > 10_000

    def test_02_with_volume(self):
        """Candlestick chart with volume bars enabled."""
        df = self.btc_df.tail(90).copy()
        out = OUTPUT_DIR / "btc_1d_with_volume.png"
        path = render_candlestick(df, output_path=out)
        assert path.exists()
        assert path.stat().st_size > 10_000

    def test_03_with_sessions(self):
        """Candlestick chart with trading session backgrounds (1H TF)."""
        import matplotlib.pyplot as plt
        import mplfinance as mpf
        from render.chart_config import DEFAULT_CONFIG
        from render.sessions import render_sessions

        df_1h = _fetch_btc_1h()
        out = OUTPUT_DIR / "btc_1h_with_sessions.png"

        cc = DEFAULT_CONFIG.colors
        vol = DEFAULT_CONFIG.volume

        marketcolors = mpf.make_marketcolors(
            up=cc.bullish, down=cc.bearish,
            edge={"up": cc.bullish_edge, "down": cc.bearish_edge},
            wick={"up": cc.bullish_wick, "down": cc.bearish_wick},
            ohlc={"up": cc.bullish, "down": cc.bearish},
            volume={"up": vol.up_color, "down": vol.down_color},
            vcdopcod=True, alpha=vol.alpha,
        )
        mpl_style = mpf.make_mpf_style(
            marketcolors=marketcolors,
            facecolor=DEFAULT_CONFIG.style.facecolor,
            gridcolor=DEFAULT_CONFIG.style.gridcolor,
            gridstyle=DEFAULT_CONFIG.style.gridstyle,
            gridaxis=DEFAULT_CONFIG.style.gridaxis,
        )

        fig, axes = mpf.plot(
            df_1h.tail(120), type="candle", mav=(5, 20), volume=True,
            figsize=(14, 8), style=mpl_style, returnfig=True,
            tight_layout=True,
            scale_padding={
                "top": DEFAULT_CONFIG.margins.top,
                "bottom": DEFAULT_CONFIG.margins.bottom,
                "left": DEFAULT_CONFIG.margins.left,
                "right": DEFAULT_CONFIG.margins.right,
            },
        )

        ax_price = axes[0] if isinstance(axes, (list, tuple)) else axes[0]
        render_sessions(ax_price, df_1h.tail(120), self.session_defs, alpha=0.12)

        fig.savefig(str(out), dpi=150, bbox_inches="tight")
        plt.close(fig)

        assert out.exists()
        assert out.stat().st_size > 10_000

    def test_04_45_day_view(self):
        """Compact 45-day view for quick daily snapshot."""
        df = self.btc_df.tail(45).copy()
        out = OUTPUT_DIR / "btc_1d_45day.png"
        path = render_candlestick(df, output_path=out, figsize=(12, 5), mav=(5,))
        assert path.exists()
        assert path.stat().st_size > 5_000


# ---------------------------------------------------------------------------
# Tests -- synthetic data charts (deterministic patterns)
# ---------------------------------------------------------------------------


class TestSyntheticCharts:
    """Render charts from deterministic synthetic OHLCV data."""

    def setup_method(self):
        """Generate synthetic data with a fixed seed for reproducibility."""
        self.mock_df = _generate_mock_ohlcv(120, freq="1h")
        self.session_defs = _get_session_defs()

    def test_01_trend_chart(self):
        """Uptrend/downtrend synthetic chart with MA overlay."""
        out = OUTPUT_DIR / "synthetic_trend.png"
        path = render_candlestick(self.mock_df, output_path=out)
        assert path.exists()
        assert path.stat().st_size > 10_000

    def test_02_range_chart(self):
        """Consolidation/range synthetic chart (no MA)."""
        range_df = self.mock_df.iloc[40:80].copy()
        out = OUTPUT_DIR / "synthetic_range.png"
        path = render_candlestick(range_df, output_path=out, mav=(5,))
        assert path.exists()

    def test_03_with_all_sessions(self):
        """Synthetic chart with all session backgrounds rendered."""
        out = OUTPUT_DIR / "synthetic_with_sessions.png"
        path = _render_session_chart(self.mock_df, "synthetic_with_sessions.png", self.session_defs)
        assert path.exists()
        assert path.stat().st_size > 10_000

    def test_04_dark_style(self):
        """Candlestick chart with dark background style."""
        out = OUTPUT_DIR / "synthetic_dark.png"
        path = _render_dark_chart(self.mock_df, "synthetic_dark.png")
        assert path.exists()
        assert path.stat().st_size > 10_000


# ---------------------------------------------------------------------------
# Tests -- edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Chart renderer edge cases."""

    def test_01_short_series(self):
        """Chart with minimal data (20 candles)."""
        short_df = _generate_mock_ohlcv(20)
        out = OUTPUT_DIR / "synthetic_short.png"
        path = render_candlestick(short_df, output_path=out, mav=(5,))
        assert path.exists()

    def test_02_large_series(self):
        """Chart with 250 candles (full year of 1D data)."""
        large_df = _generate_mock_ohlcv(250)
        out = OUTPUT_DIR / "synthetic_large.png"
        path = render_candlestick(large_df, output_path=out, mav=(5, 20, 50), volume=True)
        assert path.exists()
        assert path.stat().st_size > 20_000

    def test_03_bearish_only(self):
        """Chart with only bearish candles."""
        import numpy as np

        np.random.seed(99)
        n = 60
        base_ts = pd.Timestamp("2025-06-01", tz="UTC")
        dates = pd.date_range(base_ts, periods=n, freq="1D")

        records = []
        p = 50000.0
        for i in range(n):
            drop = np.random.uniform(200, 800)
            o, c = p, p - drop
            h = o + np.random.uniform(50, 200)
            l = c - np.random.uniform(50, 200)
            records.append({"Open": o, "High": h, "Low": l, "Close": c, "Volume": 800})
            p = c

        df = pd.DataFrame(records)
        df.index = dates

        out = OUTPUT_DIR / "synthetic_bearish.png"
        path = render_candlestick(df, output_path=out, mav=(5,))
        assert path.exists()


# ---------------------------------------------------------------------------
# Direct execution -- generate all charts when run as script
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("SMC/ICT Chart Renderer -- Visual Test Generator")
    print("=" * 60)

    print("\n[1/8] Fetching live BTC/USDT 1D data from Bybit...")
    try:
        live_df = _fetch_btc_1d()
        print(f"      OK -- {len(live_df)} candles fetched")
    except Exception as e:
        print(f"      ERROR -- {e}")
        live_df = None

    session_defs = _get_session_defs()
    mock_df = _generate_mock_ohlcv(120)

    charts = []

    # --- Live data charts ---
    if live_df is not None:
        charts.append(("Live BTC 1D -- Basic (90 days)",
                       lambda: render_candlestick(live_df.tail(90), OUTPUT_DIR / "btc_1d_basic.png")))
        charts.append(("Live BTC 1D -- With Volume (90 days)",
                       lambda: render_candlestick(live_df.tail(90), OUTPUT_DIR / "btc_1d_with_volume.png")))
        charts.append(("Live BTC 1D -- 45 Day Compact",
                       lambda: render_candlestick(live_df.tail(45), OUTPUT_DIR / "btc_1d_45day.png",
                                                  figsize=(12, 5), mav=(5,))))

    # --- Synthetic charts ---
    charts.append(("Synthetic -- Trend (120 days)",
                   lambda: render_candlestick(mock_df, OUTPUT_DIR / "synthetic_trend.png")))
    charts.append(("Synthetic -- Range (40 days)",
                   lambda: render_candlestick(mock_df.iloc[40:80], OUTPUT_DIR / "synthetic_range.png",
                                              mav=(5,))))
    charts.append(("Synthetic -- Short (20 days)",
                   lambda: render_candlestick(_generate_mock_ohlcv(20), OUTPUT_DIR / "synthetic_short.png",
                                              mav=(5,))))

    import numpy as np
    np.random.seed(99)
    n = 60
    base_ts = pd.Timestamp("2025-06-01", tz="UTC")
    dates = pd.date_range(base_ts, periods=n, freq="1D")
    records = []
    p = 50000.0
    for i in range(n):
        drop = np.random.uniform(200, 800)
        o, c = p, p - drop
        h = o + np.random.uniform(50, 200)
        l = c - np.random.uniform(50, 200)
        records.append({"Open": o, "High": h, "Low": l, "Close": c, "Volume": 800})
        p = c
    bearish_df = pd.DataFrame(records)
    bearish_df.index = dates
    charts.append(("Synthetic -- Bearish (60 days)",
                   lambda: render_candlestick(bearish_df, OUTPUT_DIR / "synthetic_bearish.png",
                                              mav=(5,))))

    # --- Session/dark charts ---
    print("\n[1/8] Fetching live BTC/USDT 1H data for session charts...")
    live_1h_df = None
    try:
        live_1h_df = _fetch_btc_1h()
        print(f"      OK -- {len(live_1h_df)} candles fetched")
    except Exception as e:
        print(f"      ERROR -- {e}")
    if live_1h_df is not None:
        charts.append(("Live BTC 1H -- With Sessions",
                       lambda: _render_session_chart(live_1h_df.tail(120), "btc_1h_with_sessions.png", session_defs)))
    charts.append(("Synthetic 1H -- With Sessions",
                   lambda: _render_session_chart(_generate_mock_ohlcv(120, freq="1h"), "synthetic_1h_with_sessions.png", session_defs)))
    charts.append(("Synthetic -- Dark Style",
                   lambda: _render_dark_chart(mock_df, "synthetic_dark.png")))

    # --- Execute ---
    print(f"\n[2/8] Generating {len(charts)} charts -> {OUTPUT_DIR.absolute()}\n")
    for i, (name, fn) in enumerate(charts, 1):
        try:
            out_path = fn()
            size_kb = out_path.stat().st_size / 1024
            print(f"  {i:2d}. {name}")
            print(f"       -> {out_path.name} ({size_kb:.0f} KB)")
        except Exception as e:
            print(f"  {i:2d}. {name} -- ERROR: {e}")

    print(f"\nDone. {len(charts)} charts saved to {OUTPUT_DIR.absolute()}")
    print("=" * 60)
