"""
Базовый рендер свечных графиков (mplfinance) → PNG.
"""

from pathlib import Path
from typing import Optional

import matplotlib
import pandas as pd

matplotlib.use("Agg")  # headless backend — не нужен GUI


def render_candlestick(
    df: pd.DataFrame,
    output_path: Optional[str | Path] = None,
    config=None,
    show: bool = True,
    **plot_kwargs,
) -> Path:
    """
    Строит свечной график из OHLCV DataFrame и сохраняет в PNG.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV данные с DatetimeIndex и столбцами:
        ``open, high, low, close, volume`` (любой регистр — нормализуется).
    output_path : str | Path | None
        Путь сохранения. По умолчанию ``chart.png`` в текущей директории.
    config : ChartConfig | None
        Объект конфигурации визуализации (render.chart_config.ChartConfig).
        Если None — используются дефолтные параметры mplfinance.
    show : bool
        Если True — показывает график (только если GUI-бэкенд доступен).
    **plot_kwargs
        Дополнительные именованные аргументы для mplfinance.plot().

    Returns
    -------
    Path
        Абсолютный путь к сохранённому PNG-файлу.
    """
    import mplfinance as mpf

    from render.chart_config import DEFAULT_CONFIG

    config = config or DEFAULT_CONFIG

    # --- Normalize columns & index ---
    df = df.copy()
    df.columns = [c.lower().strip() for c in df.columns]

    if not isinstance(df.index, pd.DatetimeIndex):
        if "timestamp" in df.columns:
            df.index = pd.to_datetime(df["timestamp"])
        elif "date" in df.columns:
            df.index = pd.to_datetime(df["date"])
        else:
            raise ValueError(
                "DataFrame must have a DatetimeIndex or a 'timestamp'/'date' column."
            )

    # Ensure required OHLCV columns exist (lowercase)
    required = {"open", "high", "low", "close"}
    if not required.issubset(df.columns):
        raise ValueError(
            f"DataFrame must have columns: {required}. "
            f"Got: {set(df.columns)}"
        )

    # --- Build mplfinance style via make_mpf_style / make_marketcolors ---
    import mplfinance as mpf

    cc = config.colors
    vol = config.volume

    marketcolors = mpf.make_marketcolors(
        up=cc.bullish,
        down=cc.bearish,
        edge={"up": cc.bullish_edge, "down": cc.bearish_edge},
        wick={"up": cc.bullish_wick, "down": cc.bearish_wick},
        ohlc={"up": cc.bullish, "down": cc.bearish},
        volume={"up": vol.up_color, "down": vol.down_color},
        vcdopcod=True,
        alpha=vol.alpha,
    )

    appearance: dict = {
        "facecolor": config.style.facecolor,
        "gridcolor": config.style.gridcolor,
        "gridstyle": config.style.gridstyle,
        "gridaxis": config.style.gridaxis,
        "y_on_right": False,
    }

    mpl_style = mpf.make_mpf_style(marketcolors=marketcolors, **appearance)

    # --- Build plot kwargs ---
    mpldict = config.to_mpldict()
    plot_args = {
        "type": mpldict["type"],
        "mav": mpldict["mav"],
        "volume": mpldict["volume"],
        "figsize": mpldict["figsize"],
        "title": mpldict["title"],
        "tight_layout": mpldict["tight_layout"],
        "scale_padding": mpldict["scale_padding"],
        "style": mpl_style,
    }
    plot_args.update(plot_kwargs)

    # --- Plot & save ---
    output_path = Path(output_path or "chart.png")

    # Suppress MPL warnings about empty axes when df is too short
    if len(df) < 2:
        raise ValueError("At least 2 data points are required to render a chart.")

    fig, axes = mpf.plot(
        df,
        returnfig=True,
        **plot_args,
    )

    # Tighten layout to remove excess whitespace
    fig.tight_layout()

    # Save as PNG
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    matplotlib.pyplot.close(fig)

    if show:
        try:
            import matplotlib.pyplot as plt
            fig.show()
        except Exception:
            pass  # No GUI available — silently skip

    return output_path.resolve()
