import logging

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


class YFinanceClient:
    def __init__(self, ticker: str) -> None:
        self.ticker_symbol = ticker.upper()
        self._ticker: yf.Ticker | None = None

    @property
    def ticker(self) -> yf.Ticker:
        if self._ticker is None:
            self._ticker = yf.Ticker(self.ticker_symbol)
        return self._ticker

    def get_info(self) -> dict:
        try:
            return dict(self.ticker.info)
        except Exception:
            logger.warning("Failed to fetch info for %s", self.ticker_symbol)
            return {}

    def get_history(
        self,
        period: str = "1y",
        interval: str = "1d",
    ) -> pd.DataFrame:
        try:
            df = self.ticker.history(period=period, interval=interval)
            if df.empty:
                logger.warning(
                    "Empty history for %s",
                    self.ticker_symbol,
                )
            return df
        except Exception:
            logger.warning(
                "Failed to fetch history for %s",
                self.ticker_symbol,
            )
            return pd.DataFrame()

    def get_financials(self) -> pd.DataFrame:
        try:
            return self.ticker.financials
        except Exception:
            logger.warning(
                "Failed to fetch financials for %s",
                self.ticker_symbol,
            )
            return pd.DataFrame()

    def get_balance_sheet(self) -> pd.DataFrame:
        try:
            return self.ticker.balance_sheet
        except Exception:
            logger.warning(
                "Failed to fetch balance sheet for %s",
                self.ticker_symbol,
            )
            return pd.DataFrame()

    def get_cashflow(self) -> pd.DataFrame:
        try:
            return self.ticker.cashflow
        except Exception:
            logger.warning(
                "Failed to fetch cashflow for %s",
                self.ticker_symbol,
            )
            return pd.DataFrame()

    def get_recommendations(self) -> pd.DataFrame:
        try:
            recs = self.ticker.recommendations
            if recs is None:
                return pd.DataFrame()
            return recs
        except Exception:
            logger.warning(
                "Failed to fetch recommendations for %s",
                self.ticker_symbol,
            )
            return pd.DataFrame()

    def get_news(self) -> list[dict]:
        try:
            news = self.ticker.news
            return news if news else []
        except Exception:
            logger.warning("Failed to fetch news for %s", self.ticker_symbol)
            return []

    def get_calendar(self) -> dict:
        try:
            cal = self.ticker.calendar
            return dict(cal) if cal else {}
        except Exception:
            logger.warning("Failed to fetch calendar for %s", self.ticker_symbol)
            return {}

    def get_quarterly_financials(self) -> pd.DataFrame:
        try:
            return self.ticker.quarterly_financials
        except Exception:
            logger.warning(
                "Failed to fetch quarterly financials for %s",
                self.ticker_symbol,
            )
            return pd.DataFrame()
