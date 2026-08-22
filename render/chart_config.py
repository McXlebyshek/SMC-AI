"""
Визуальные параметры для построения свечных графиков (mplfinance).
"""

from dataclasses import dataclass, field
from typing import Dict


@dataclass(frozen=True)
class CandleColors:
    """Цвета свечей, близкие к стилю TradingView."""
    bullish: str = "#26a69a"
    bearish: str = "#ef5350"
    bullish_edge: str = "#26a69a"
    bearish_edge: str = "#ef5350"
    bullish_wick: str = "#26a69a"
    bearish_wick: str = "#ef5350"


@dataclass(frozen=True)
class FigureStyle:
    """Общие параметры фигуры графика."""
    facecolor: str = "#ffffff"
    bgcolor: str = "#ffffff"
    gridcolor: str = "#e0e0e0"
    gridstyle: str = "-"
    gridaxis: str = "both"
    alpha: float = 1.0


@dataclass(frozen=True)
class Margins:
    """Отступы для mplfinance (top, bottom, left, right) as fractions."""
    top: float = 0.08
    bottom: float = 0.15
    left: float = 0.08
    right: float = 0.03


@dataclass(frozen=True)
class VolumeStyle:
    """Параметры отображения объёма."""
    enabled: bool = True
    scale_height: float = 0.15
    alpha: float = 0.75
    up_color: str = "#26a69a"
    down_color: str = "#ef5350"


@dataclass(frozen=True)
class SessionColors:
    """Цвета фоновых блоков торговых сессий."""
    asian: str = "#ffffcc"
    london: str = "#ccf5ff"
    new_york: str = "#ffccf5"
    asian_label: str = "#b3b300"
    london_label: str = "#007ba7"
    new_york_label: str = "#a7007b"


@dataclass(frozen=True)
class ChartConfig:
    """Полная конфигурация визуальных параметров графика."""
    colors: CandleColors = field(default_factory=CandleColors)
    style: FigureStyle = field(default_factory=FigureStyle)
    margins: Margins = field(default_factory=Margins)
    volume: VolumeStyle = field(default_factory=VolumeStyle)
    sessions: SessionColors = field(default_factory=SessionColors)

    def to_mpldict(self) -> Dict:
        """Формирует словарь для передачи в mplfinance.plot()."""
        return {
            "type": "candle",
            "mav": (5, 20),
            "volume": self.volume.enabled,
            "figsize": (14, 8),
            "title": "",
            "tight_layout": True,
            "scale_padding": {
                "top": self.margins.top,
                "bottom": self.margins.bottom,
                "left": self.margins.left,
                "right": self.margins.right,
            },
            "style": {
                "facecolor": self.style.facecolor,
                "bgcolor": self.style.bgcolor,
                "gridcolor": self.style.gridcolor,
                "gridstyle": self.style.gridstyle,
                "gridaxis": self.style.gridaxis,
                "up": self.colors.bullish,
                "down": self.colors.bearish,
                "upedgecolor": self.colors.bullish_edge,
                "downedgecolor": self.colors.bearish_edge,
                "upwedgecolor": self.colors.bullish_wick,
                "downwedgecolor": self.colors.bearish_wick,
                "volume_up": self.volume.up_color,
                "volume_down": self.volume.down_color,
                "volume_alpha": self.volume.alpha,
            },
            "marketcolors": {
                "candle": [self.colors.bullish, self.colors.bearish],
                "edge": [self.colors.bullish_edge, self.colors.bearish_edge],
                "wick": [self.colors.bullish_wick, self.colors.bearish_wick],
                "ohlc": [self.colors.bullish, self.colors.bearish],
                "volume": [self.volume.up_color, self.volume.down_color],
            },
        }


DEFAULT_CONFIG = ChartConfig()
