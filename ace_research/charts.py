"""
charts.py

Matplotlib financial trend chart generator for the ACE Research reporting system.

Reads ONLY from the pre-computed summary dict produced by build_financial_summary().
No database access. No metric recomputation.

Public API:
    generate_charts(summary, years) -> list[str]
        Returns a list of four temporary PNG file paths.
        The CALLER is responsible for deleting the files after use.

Charts generated (in order):
    1. Revenue Trend
    2. Net Margin Trend (%)
    3. Return on Equity Trend (%)
    4. Debt Ratio Trend (%)
"""

from __future__ import annotations

import os
import tempfile
from typing import Optional

try:
    import matplotlib
    matplotlib.use("Agg")           # non-interactive, file-only backend
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
    _MATPLOTLIB_AVAILABLE = True
except ImportError:
    _MATPLOTLIB_AVAILABLE = False


# =============================================================================
# Visual constants
# =============================================================================

_LINE_COLOR   = "#1a3a6e"    # dark blue — matches PDF brand colour
_MARKER_COLOR = "#e05c2a"    # contrasting orange for data points
_ANNOT_COLOR  = "#1a3a6e"
_GRID_COLOR   = "#e0e6f0"
_BG_COLOR     = "#f8f9fb"
_FIGSIZE      = (3.4, 2.4)   # inches per individual chart
_DPI          = 130


# =============================================================================
# Private helpers
# =============================================================================

def _fmt_annotation(value: float, as_pct: bool) -> str:
    """Compact label for chart data-point annotations."""
    if as_pct:
        s = f"{value:.1f}".rstrip("0").rstrip(".")
        return f"{s}%"
    abs_v = abs(value)
    if abs_v >= 1_000_000_000:
        s = f"{value / 1_000_000_000:.1f}".rstrip("0").rstrip(".")
        return f"{s}B"
    if abs_v >= 1_000_000:
        s = f"{value / 1_000_000:.1f}".rstrip("0").rstrip(".")
        return f"{s}M"
    if abs_v >= 1_000:
        return f"{value:,.0f}"
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _plot_trend(
    years: list[int],
    values: dict[int, Optional[float]],
    title: str,
    y_label: str,
    as_pct: bool = False,
) -> str:
    """
    Generate one line chart and save to a temporary PNG file.

    Parameters
    ----------
    years   : ordered fiscal years (x-axis universe)
    values  : pre-computed metric values keyed by year; None → point skipped
    title   : chart title
    y_label : y-axis label
    as_pct  : if True, multiply raw decimal values by 100 before plotting

    Returns
    -------
    str — absolute path of the written PNG temp file
    """
    xs: list[int]   = []
    ys: list[float] = []
    for yr in years:
        v = values.get(yr)
        if v is not None:
            xs.append(yr)
            ys.append(v * 100.0 if as_pct else v)

    fig, ax = plt.subplots(figsize=_FIGSIZE, dpi=_DPI)
    fig.patch.set_facecolor(_BG_COLOR)
    ax.set_facecolor(_BG_COLOR)

    if xs:
        ax.plot(xs, ys, color=_LINE_COLOR, linewidth=2.0, zorder=3)
        ax.scatter(xs, ys, color=_MARKER_COLOR, s=44, zorder=4, linewidths=0)

        for x, y in zip(xs, ys):
            ax.annotate(
                _fmt_annotation(y, as_pct),
                (x, y),
                textcoords="offset points",
                xytext=(0, 8),
                ha="center",
                fontsize=6.5,
                color=_ANNOT_COLOR,
            )

    ax.set_title(title, fontsize=9, fontweight="bold", color=_LINE_COLOR, pad=6)
    ax.set_ylabel(y_label, fontsize=7.5, color="#555555")
    ax.set_xlabel("Year", fontsize=7.5, color="#555555")

    if xs:
        ax.set_xticks(xs)
    ax.xaxis.set_major_formatter(
        mticker.FuncFormatter(lambda x, _: str(int(x)))
    )
    ax.tick_params(axis="both", labelsize=7, colors="#555555")
    ax.grid(True, color=_GRID_COLOR, linestyle="-", linewidth=0.8, zorder=0)
    for spine in ax.spines.values():
        spine.set_edgecolor(_GRID_COLOR)

    plt.tight_layout(pad=0.8)

    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    fig.savefig(path, dpi=_DPI, bbox_inches="tight", facecolor=_BG_COLOR)
    plt.close(fig)

    return path


# =============================================================================
# Public API
# =============================================================================

def generate_charts(summary: dict, years: list[int]) -> list[str]:
    """
    Generate four financial trend charts from the pre-computed summary dict.

    Charts (in order):
        1. Revenue Trend
        2. Net Margin Trend (%)
        3. Return on Equity Trend (%)
        4. Debt Ratio Trend (%)

    Parameters
    ----------
    summary : dict
        Output of build_financial_summary().
    years : list[int]
        Sorted list of fiscal years.

    Returns
    -------
    list[str]
        Absolute paths of the four temporary PNG files.
        The caller is responsible for deleting them after use.

    Raises
    ------
    ImportError
        If matplotlib is not installed.
    """
    if not _MATPLOTLIB_AVAILABLE:
        raise ImportError(
            "matplotlib is required for chart generation. "
            "Install with: pip install matplotlib"
        )

    income  = summary.get("income_statement", {})
    quality = summary.get("quality_metrics", {})

    chart_specs: list[tuple] = [
        (
            income.get("revenue", {}).get("values", {}),
            "Revenue Trend",
            "Revenue",
            False,
        ),
        (
            quality.get("net_margin", {}).get("values", {}),
            "Net Margin Trend",
            "Net Margin (%)",
            True,
        ),
        (
            quality.get("return_on_equity", {}).get("values", {}),
            "Return on Equity Trend",
            "ROE (%)",
            True,
        ),
        (
            quality.get("debt_ratio", {}).get("values", {}),
            "Debt Ratio Trend",
            "Debt Ratio (%)",
            True,
        ),
    ]

    return [
        _plot_trend(years, values, title, y_label, as_pct=as_pct)
        for values, title, y_label, as_pct in chart_specs
    ]
