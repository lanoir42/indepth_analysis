import logging

import pandas as pd

from indepth_analysis.config import AnalysisConfig
from indepth_analysis.data.yfinance_client import YFinanceClient

logger = logging.getLogger(__name__)


class MarketDataProvider:
    def __init__(self, ticker: str, config: AnalysisConfig) -> None:
        self.ticker = ticker.upper()
        self.config = config
        self._yf = YFinanceClient(ticker)
        self._ibkr = None
        self._ibkr_available = False

    async def initialize(self) -> None:
        try:
            from indepth_analysis.data.ibkr_client import IBKRClient

            client = IBKRClient(
                host=self.config.ibkr_host,
                port=self.config.ibkr_port,
                client_id=self.config.ibkr_client_id,
                timeout=self.config.ibkr_timeout,
            )
            connected = await client.connect()
            if connected:
                self._ibkr = client
                self._ibkr_available = True
                logger.info("IBKR connected")
            else:
                logger.info("IBKR unavailable, using yfinance only")
        except Exception:
            logger.info("IBKR unavailable, using yfinance only")

    @property
    def ibkr_available(self) -> bool:
        return self._ibkr_available

    def get_info(self) -> dict:
        return self._yf.get_info()

    def get_history(
        self,
        period: str | None = None,
        interval: str | None = None,
    ) -> pd.DataFrame:
        p = period or self.config.history_period
        i = interval or self.config.history_interval
        return self._yf.get_history(period=p, interval=i)

    def get_financials(self) -> pd.DataFrame:
        return self._yf.get_financials()

    def get_balance_sheet(self) -> pd.DataFrame:
        return self._yf.get_balance_sheet()

    def get_cashflow(self) -> pd.DataFrame:
        return self._yf.get_cashflow()

    def get_recommendations(self) -> pd.DataFrame:
        return self._yf.get_recommendations()

    def get_sector_history(self, etf: str, period: str = "1y") -> pd.DataFrame:
        client = YFinanceClient(etf)
        return client.get_history(period=period)

    def get_news(self) -> list[dict]:
        return self._yf.get_news()

    def get_calendar(self) -> dict:
        return self._yf.get_calendar()

    def get_quarterly_financials(self) -> pd.DataFrame:
        return self._yf.get_quarterly_financials()

    async def get_option_chain(self) -> dict | None:
        if self._ibkr and self._ibkr_available:
            try:
                return await self._ibkr.get_option_chain(self.ticker)
            except Exception:
                logger.warning("IBKR option chain failed")
        return None

    async def disconnect(self) -> None:
        if self._ibkr:
            await self._ibkr.disconnect()
