from __future__ import annotations

import logging
from pathlib import Path

import matplotlib
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

from indepth_analysis.models.report_data import ReportData

matplotlib.use("Agg")

logger = logging.getLogger(__name__)

COLORS = {
    "close": "#1f77b4",
    "sma_20": "#ff7f0e",
    "sma_50": "#2ca02c",
    "sma_200": "#d62728",
    "volume": "#7f7f7f",
    "rsi": "#8c564b",
    "macd_line": "#1f77b4",
    "macd_signal": "#ff7f0e",
    "hist_pos": "#2ca02c",
    "hist_neg": "#d62728",
    "revenue": "#1f77b4",
    "net_income": "#2ca02c",
    "gross_margin": "#ff7f0e",
    "op_margin": "#d62728",
    "profit_margin": "#9467bd",
    "overbought": "#d62728",
    "oversold": "#2ca02c",
}


def _apply_style(ax: plt.Axes) -> None:
    ax.set_facecolor("white")
    ax.grid(True, alpha=0.3, linestyle="--")
    ax.tick_params(labelsize=9)
    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(fontsize=9, loc="upper left")


def _save_figure(fig: plt.Figure, path: Path) -> None:
    fig.savefig(
        path,
        dpi=150,
        bbox_inches="tight",
        facecolor="white",
        edgecolor="none",
    )
    plt.close(fig)


def generate_price_chart(
    report_data: ReportData, ticker: str, output_dir: Path
) -> Path | None:
    try:
        ind = report_data.indicators
        if ind.close is None or ind.dates is None:
            return None

        fig, (ax1, ax2) = plt.subplots(
            2, 1, figsize=(12, 7), height_ratios=[3, 1], sharex=True
        )
        fig.suptitle(
            f"{ticker} — Price & Moving Averages",
            fontsize=14,
            fontweight="bold",
        )

        ax1.plot(
            ind.dates,
            ind.close,
            color=COLORS["close"],
            linewidth=1.2,
            label="Close",
        )
        if ind.sma_20 is not None:
            ax1.plot(
                ind.dates,
                ind.sma_20,
                color=COLORS["sma_20"],
                linewidth=0.9,
                label="SMA(20)",
            )
        if ind.sma_50 is not None:
            ax1.plot(
                ind.dates,
                ind.sma_50,
                color=COLORS["sma_50"],
                linewidth=0.9,
                label="SMA(50)",
            )
        if ind.sma_200 is not None:
            ax1.plot(
                ind.dates,
                ind.sma_200,
                color=COLORS["sma_200"],
                linewidth=0.9,
                label="SMA(200)",
            )
        ax1.set_ylabel("Price ($)", fontsize=10)
        _apply_style(ax1)

        if ind.volume is not None:
            ax2.bar(ind.dates, ind.volume, color=COLORS["volume"], alpha=0.6, width=0.8)
            ax2.set_ylabel("Volume", fontsize=10)
            _apply_style(ax2)

        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
        fig.autofmt_xdate()

        path = output_dir / f"{ticker}_price.png"
        _save_figure(fig, path)
        return path
    except Exception:
        logger.warning("Failed to generate price chart", exc_info=True)
        return None


def generate_rsi_chart(
    report_data: ReportData, ticker: str, output_dir: Path
) -> Path | None:
    try:
        ind = report_data.indicators
        if ind.rsi_14 is None or ind.dates is None:
            return None

        fig, ax = plt.subplots(figsize=(12, 3.5))
        fig.suptitle(f"{ticker} — RSI(14)", fontsize=14, fontweight="bold")

        ax.plot(
            ind.dates,
            ind.rsi_14,
            color=COLORS["rsi"],
            linewidth=1.2,
            label="RSI(14)",
        )
        ax.axhline(
            70,
            color=COLORS["overbought"],
            linestyle="--",
            alpha=0.7,
            label="Overbought (70)",
        )
        ax.axhline(
            30,
            color=COLORS["oversold"],
            linestyle="--",
            alpha=0.7,
            label="Oversold (30)",
        )
        ax.fill_between(ind.dates, 70, 100, alpha=0.08, color=COLORS["overbought"])
        ax.fill_between(ind.dates, 0, 30, alpha=0.08, color=COLORS["oversold"])
        ax.set_ylim(0, 100)
        ax.set_ylabel("RSI", fontsize=10)
        _apply_style(ax)

        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
        fig.autofmt_xdate()

        path = output_dir / f"{ticker}_rsi.png"
        _save_figure(fig, path)
        return path
    except Exception:
        logger.warning("Failed to generate RSI chart", exc_info=True)
        return None


def generate_macd_chart(
    report_data: ReportData, ticker: str, output_dir: Path
) -> Path | None:
    try:
        ind = report_data.indicators
        if ind.macd_line is None or ind.dates is None:
            return None

        fig, ax = plt.subplots(figsize=(12, 4))
        fig.suptitle(f"{ticker} — MACD", fontsize=14, fontweight="bold")

        ax.plot(
            ind.dates,
            ind.macd_line,
            color=COLORS["macd_line"],
            linewidth=1.2,
            label="MACD",
        )
        if ind.macd_signal is not None:
            ax.plot(
                ind.dates,
                ind.macd_signal,
                color=COLORS["macd_signal"],
                linewidth=1.0,
                label="Signal",
            )
        if ind.macd_histogram is not None:
            pos = ind.macd_histogram.copy()
            neg = ind.macd_histogram.copy()
            pos[pos < 0] = 0
            neg[neg > 0] = 0
            ax.bar(ind.dates, pos, color=COLORS["hist_pos"], alpha=0.5, width=0.8)
            ax.bar(ind.dates, neg, color=COLORS["hist_neg"], alpha=0.5, width=0.8)

        ax.axhline(0, color="black", linewidth=0.5, alpha=0.5)
        ax.set_ylabel("MACD", fontsize=10)
        _apply_style(ax)

        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
        fig.autofmt_xdate()

        path = output_dir / f"{ticker}_macd.png"
        _save_figure(fig, path)
        return path
    except Exception:
        logger.warning("Failed to generate MACD chart", exc_info=True)
        return None


def generate_fundamentals_chart(
    report_data: ReportData, ticker: str, output_dir: Path
) -> Path | None:
    try:
        fh = report_data.fundamentals_history
        if not fh.dates or not fh.revenue:
            return None

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7))
        fig.suptitle(
            f"{ticker} — Quarterly Fundamentals", fontsize=14, fontweight="bold"
        )

        x = range(len(fh.dates))
        width = 0.35

        # Revenue & net income bar chart
        ax1.bar(
            [i - width / 2 for i in x],
            [v / 1e9 for v in fh.revenue],
            width,
            label="Revenue",
            color=COLORS["revenue"],
            alpha=0.8,
        )
        if fh.net_income:
            ax1.bar(
                [i + width / 2 for i in x],
                [v / 1e9 for v in fh.net_income],
                width,
                label="Net Income",
                color=COLORS["net_income"],
                alpha=0.8,
            )
        ax1.set_ylabel("USD (Billions)", fontsize=10)
        ax1.set_xticks(list(x))
        ax1.set_xticklabels(fh.dates, rotation=45, ha="right", fontsize=8)
        _apply_style(ax1)

        # Margin trends
        if fh.gross_margin:
            ax2.plot(
                fh.dates,
                fh.gross_margin,
                color=COLORS["gross_margin"],
                marker="o",
                markersize=4,
                label="Gross Margin %",
            )
        if fh.operating_margin:
            ax2.plot(
                fh.dates,
                fh.operating_margin,
                color=COLORS["op_margin"],
                marker="s",
                markersize=4,
                label="Operating Margin %",
            )
        if fh.profit_margin:
            ax2.plot(
                fh.dates,
                fh.profit_margin,
                color=COLORS["profit_margin"],
                marker="^",
                markersize=4,
                label="Profit Margin %",
            )
        ax2.set_ylabel("Margin (%)", fontsize=10)
        ax2.set_xticks(range(len(fh.dates)))
        ax2.set_xticklabels(fh.dates, rotation=45, ha="right", fontsize=8)
        _apply_style(ax2)

        fig.tight_layout()

        path = output_dir / f"{ticker}_fundamentals.png"
        _save_figure(fig, path)
        return path
    except Exception:
        logger.warning("Failed to generate fundamentals chart", exc_info=True)
        return None


def generate_all_charts(
    report_data: ReportData, ticker: str, output_dir: Path
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    charts: dict[str, Path] = {}

    generators = {
        "price": generate_price_chart,
        "rsi": generate_rsi_chart,
        "macd": generate_macd_chart,
        "fundamentals": generate_fundamentals_chart,
    }

    for name, gen_func in generators.items():
        path = gen_func(report_data, ticker, output_dir)
        if path:
            charts[name] = path

    return charts
