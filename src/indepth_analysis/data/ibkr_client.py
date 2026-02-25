import asyncio
import logging

logger = logging.getLogger(__name__)


class IBKRClient:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7497,
        client_id: int = 1,
        timeout: float = 10.0,
    ) -> None:
        self.host = host
        self.port = port
        self.client_id = client_id
        self.timeout = timeout
        self._ib = None

    async def connect(self) -> bool:
        try:
            from ib_async import IB

            self._ib = IB()
            await asyncio.wait_for(
                self._ib.connectAsync(self.host, self.port, clientId=self.client_id),
                timeout=self.timeout,
            )
            logger.info("Connected to IBKR at %s:%s", self.host, self.port)
            return True
        except Exception as e:
            logger.debug("IBKR connection failed: %s", e)
            self._ib = None
            return False

    async def get_option_chain(self, ticker: str) -> dict | None:
        if not self._ib:
            return None
        try:
            from ib_async import Stock

            contract = Stock(ticker, "SMART", "USD")
            await self._ib.qualifyContractsAsync(contract)
            chains = await self._ib.reqSecDefOptParamsAsync(
                contract.symbol,
                "",
                contract.secType,
                contract.conId,
            )
            if not chains:
                return None

            chain = chains[0]
            strikes = sorted(chain.strikes)
            expirations = sorted(chain.expirations)

            tickers_data = []
            if expirations:
                from ib_async import Option

                near_exp = expirations[0]
                mid_idx = len(strikes) // 2
                sel_strikes = strikes[max(0, mid_idx - 10) : mid_idx + 10]

                contracts = []
                for s in sel_strikes:
                    for right in ("C", "P"):
                        opt = Option(
                            ticker,
                            near_exp,
                            s,
                            right,
                            chain.exchange,
                        )
                        contracts.append(opt)

                qualified = await self._ib.qualifyContractsAsync(*contracts)
                if qualified:
                    tickers_data = await self._ib.reqTickersAsync(
                        *[c for c in qualified if c.conId]
                    )

            return {
                "strikes": strikes,
                "expirations": expirations,
                "exchange": chain.exchange,
                "tickers": tickers_data,
            }
        except Exception as e:
            logger.warning("Option chain fetch failed: %s", e)
            return None

    async def disconnect(self) -> None:
        if self._ib:
            self._ib.disconnect()
            self._ib = None
