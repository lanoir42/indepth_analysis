from indepth_analysis.models.common import Signal


def fmt_pct(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "N/A"
    return f"{value:+.{decimals}f}%"


def fmt_number(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "N/A"
    return f"{value:,.{decimals}f}"


def fmt_large_number(value: float | None) -> str:
    if value is None:
        return "N/A"
    abs_val = abs(value)
    sign = "-" if value < 0 else ""
    if abs_val >= 1e12:
        return f"{sign}${abs_val / 1e12:.2f}T"
    if abs_val >= 1e9:
        return f"{sign}${abs_val / 1e9:.2f}B"
    if abs_val >= 1e6:
        return f"{sign}${abs_val / 1e6:.2f}M"
    return f"{sign}${abs_val:,.0f}"


def fmt_ratio(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "N/A"
    return f"{value:.{decimals}f}x"


def fmt_price(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"${value:,.2f}"


def signal_color(signal: Signal) -> str:
    colors = {
        Signal.STRONG_BUY: "bold green",
        Signal.BUY: "green",
        Signal.LEAN_BUY: "green3",
        Signal.NEUTRAL: "yellow",
        Signal.LEAN_SELL: "orange3",
        Signal.SELL: "red",
        Signal.STRONG_SELL: "bold red",
    }
    return colors.get(signal, "white")


def confidence_bar(confidence: float, width: int = 10) -> str:
    filled = round(confidence * width)
    return "█" * filled + "░" * (width - filled)
