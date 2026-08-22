"""
Отрисовка торговых сессий на свечных графиках (mplfinance).

Поддерживает Asian, London, New York сессии с полупрозрачным фоном
и текстовыми метками. Использует определения из config/symbols.yaml
и цвета из render/chart_config.SessionColors.
"""

from datetime import datetime, time
from typing import Optional

import matplotlib.pyplot as plt
import pandas as pd


def get_session_ranges(
    df: pd.DataFrame,
    session_defs: dict,
) -> list[dict]:
    """
    Определяет, какие сессии попадают в диапазон дат DataFrame.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV DataFrame с DatetimeIndex.
    session_defs : dict
        Словарь определений сессий из symbols.yaml, например::

            {
                "asian": {"start": "00:00", "end": "02:00"},
                "london": {"start": "07:00", "end": "10:00"},
                "ny": {"start": "13:00", "end": "16:00"},
            }

    Returns
    -------
    list[dict]
        Список словарей с ключами: name, start, end, color
        (start/end — datetime объекты границ сессии).
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        df = df.copy()
        df.index = pd.to_datetime(df.index)

    if df.index.tzinfo is None:
        df.index = df.index.tz_localize("UTC")

    date_range = df.index
    start_date = date_range.min().replace(hour=0, minute=0, second=0)
    end_date = date_range.max().replace(hour=23, minute=59, second=59)

    sessions = []

    for name, defs in session_defs.items():
        start_time = _parse_time(defs["start"])
        end_time = _parse_time(defs["end"])

        current_date = start_date
        while current_date <= end_date:
            session_start = datetime.combine(current_date.date(), start_time)
            session_end = datetime.combine(current_date.date(), end_time)
            if session_start.tzinfo is None:
                session_start = session_start.replace(tzinfo=pd.Timestamp("2000-01-01", tz="UTC").tzinfo)
                session_end = session_end.replace(tzinfo=pd.Timestamp("2000-01-01", tz="UTC").tzinfo)

            # Проверяем пересечение сессии с диапазоном данных
            if session_start <= end_date and session_end >= start_date:
                sessions.append({
                    "name": name,
                    "start": session_start,
                    "end": session_end,
                })

            current_date += pd.Timedelta(days=1)

    return sessions


def _is_intraday(df: pd.DataFrame) -> bool:
    """Определяет, является ли ТФ интрадей (< 1D) по частоте между свечами."""
    if len(df) < 2:
        return False
    if not isinstance(df.index, pd.DatetimeIndex):
        return False
    diffs = df.index.to_series().diff().dropna()
    if diffs.empty:
        return False
    median_diff = diffs.median()
    # Интрадей = меньше 24 часов
    return median_diff < pd.Timedelta(hours=24)


def render_sessions(
    ax,
    df: pd.DataFrame,
    session_defs: dict,
    session_colors: Optional[dict] = None,
    labels: bool = False,
    alpha: float = 0.15,
) -> None:
    """
    Отрисовывает вертикальные блоки сессий на графике mplfinance.

    Parameters
    ----------
    ax : matplotlib.axes.Axes
        Ось графика от mplfinance.plot(returnfig=True).
    df : pd.DataFrame
        OHLCV DataFrame с DatetimeIndex.
    session_defs : dict
        Словарь определений сессий из symbols.yaml.
    session_colors : dict | None
        Словарь цветов сессий: {"asian": "#ffffcc", "london": "#ccf5ff", ...}
        Если None — используются цвета по умолчанию.
    labels : bool
        Если True — добавляет текстовые метки сессий.
    alpha : float
        Прозрачность фоновых блоков (0.0 — полностью прозрачный, 1.0 — непрозрачный).
    """
    # Сессии имеют смысл только для ТФ < 1D (интрадей)
    if not _is_intraday(df):
        return

    if session_colors is None:
        session_colors = {
            "asian": "#ffffcc",
            "london": "#ccf5ff",
            "ny": "#ffccf5",
            "ny_extend": "#ffddff",
        }

    session_ranges = get_session_ranges(df, session_defs)

    for session in session_ranges:
        name = session["name"]
        color = session_colors.get(name, "#e0e0e0")

        # Вертикальный прямоугольник сессии
        ax.axvspan(
            session["start"],
            session["end"],
            facecolor=color,
            alpha=alpha,
            edgecolor=None,
            zorder=1,
        )

        if labels:
            # Текстовая метка в верхней части графика
            label_text = name.replace("_", " ").title()
            # Сохраняем текущие limits — ax.text() + get_xaxis_transform() вызывает autoscale,
            # который интерпретирует pandas Timestamp как большое число и растягивает ось
            xlim_before = ax.get_xlim()
            ylim_before = ax.get_ylim()
            autoscale_on_before = ax.get_autoscale_on()
            # Отключаем autoscale чтобы ax.text не менял limits
            ax.set_autoscale_on(False)
            # get_xaxis_transform(): x=data coords, y=axes fraction (0-1)
            try:
                trans = ax.get_xaxis_transform()
            except Exception:
                trans = ax.transData
            ax.text(
                session["start"],
                0.02,
                label_text,
                transform=trans,
                fontsize=7,
                fontweight="bold",
                color=color,
                alpha=0.8,
                rotation=0,
                verticalalignment="bottom",
                horizontalalignment="left",
                zorder=2,
            )
            # Восстанавливаем limits и autoscale
            ax.set_xlim(xlim_before)
            ax.set_ylim(ylim_before)
            ax.set_autoscale_on(autoscale_on_before)


def _parse_time(time_str: str) -> time:
    """Парсит строку времени 'HH:MM' в объект datetime.time."""
    parts = time_str.split(":")
    return time(hour=int(parts[0]), minute=int(parts[1]) if len(parts) > 1 else 0)
