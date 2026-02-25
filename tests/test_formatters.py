from indepth_analysis.models.common import Signal
from indepth_analysis.output.formatters import (
    confidence_bar,
    fmt_large_number,
    fmt_number,
    fmt_pct,
    fmt_price,
    fmt_ratio,
    signal_color,
)


class TestFmtPct:
    def test_positive(self):
        assert fmt_pct(12.345) == "+12.35%"

    def test_negative(self):
        assert fmt_pct(-5.1) == "-5.10%"

    def test_none(self):
        assert fmt_pct(None) == "N/A"


class TestFmtNumber:
    def test_basic(self):
        assert fmt_number(1234.567) == "1,234.57"

    def test_none(self):
        assert fmt_number(None) == "N/A"

    def test_zero_decimals(self):
        assert fmt_number(42, 0) == "42"


class TestFmtLargeNumber:
    def test_trillion(self):
        assert fmt_large_number(3.2e12) == "$3.20T"

    def test_billion(self):
        assert fmt_large_number(45.6e9) == "$45.60B"

    def test_million(self):
        assert fmt_large_number(123e6) == "$123.00M"

    def test_small(self):
        assert fmt_large_number(5000) == "$5,000"

    def test_none(self):
        assert fmt_large_number(None) == "N/A"


class TestFmtRatio:
    def test_basic(self):
        assert fmt_ratio(1.5) == "1.50x"

    def test_none(self):
        assert fmt_ratio(None) == "N/A"


class TestFmtPrice:
    def test_basic(self):
        assert fmt_price(420.69) == "$420.69"

    def test_none(self):
        assert fmt_price(None) == "N/A"


class TestSignalColor:
    def test_strong_buy(self):
        assert signal_color(Signal.STRONG_BUY) == "bold green"

    def test_neutral(self):
        assert signal_color(Signal.NEUTRAL) == "yellow"


class TestConfidenceBar:
    def test_full(self):
        assert confidence_bar(1.0) == "██████████"

    def test_empty(self):
        assert confidence_bar(0.0) == "░░░░░░░░░░"

    def test_half(self):
        bar = confidence_bar(0.5)
        assert "█" in bar
        assert "░" in bar
