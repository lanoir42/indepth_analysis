import pandas as pd

from indepth_analysis.analysis.fundamentals_history import extract_fundamentals_history


class TestFundamentalsHistory:
    def test_basic_extraction(self):
        dates = pd.to_datetime(["2024-09-30", "2024-06-30", "2024-03-31", "2023-12-31"])
        data = {
            dates[0]: [60e9, 40e9, 18e9, 20e9],
            dates[1]: [58e9, 39e9, 17e9, 19e9],
            dates[2]: [55e9, 37e9, 16e9, 18e9],
            dates[3]: [52e9, 35e9, 15e9, 17e9],
        }
        df = pd.DataFrame(
            data,
            index=["Total Revenue", "Gross Profit", "Net Income", "Operating Income"],
        )
        fh = extract_fundamentals_history(df)
        # Reversed to chronological order
        assert len(fh.dates) == 4
        assert len(fh.revenue) == 4
        assert len(fh.net_income) == 4
        # Oldest first
        assert fh.revenue[0] == 52e9
        assert fh.revenue[-1] == 60e9

    def test_margins_computed(self):
        dates = pd.to_datetime(["2024-06-30", "2024-03-31"])
        data = {
            dates[0]: [100e9, 60e9, 20e9, 30e9],
            dates[1]: [80e9, 50e9, 15e9, 25e9],
        }
        df = pd.DataFrame(
            data,
            index=["Total Revenue", "Gross Profit", "Net Income", "Operating Income"],
        )
        fh = extract_fundamentals_history(df)
        assert len(fh.gross_margin) == 2
        assert len(fh.operating_margin) == 2
        assert len(fh.profit_margin) == 2
        # Oldest first: 80B rev, 50B GP → 62.5%
        assert abs(fh.gross_margin[0] - 62.5) < 0.1
        # Newest: 100B rev, 60B GP → 60%
        assert abs(fh.gross_margin[1] - 60.0) < 0.1

    def test_empty_dataframe(self):
        fh = extract_fundamentals_history(pd.DataFrame())
        assert fh.dates == []
        assert fh.revenue == []
        assert fh.net_income == []

    def test_none_input(self):
        fh = extract_fundamentals_history(None)
        assert fh.dates == []
