"""ECB data client via DBnomics (free aggregator).

ECB's own API has WAF/cookie protection that blocks programmatic access.
DBnomics mirrors ECB datasets at https://api.db.nomics.world with no auth.
"""

import logging

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

DBNOMICS_API = "https://api.db.nomics.world/v22/series"
DEFAULT_TIMEOUT = 30.0

# ECB series via DBnomics
SERIES = {
    # Interest rates
    "MRR": "ECB/FM/B.U2.EUR.4F.KR.MRR_FR.LEV",
    "DFR": "ECB/FM/D.U2.EUR.4F.KR.DFR.LEV",
    "MLF": "ECB/FM/D.U2.EUR.4F.KR.MLFR.LEV",
    # Exchange rates
    "EUR/USD": "ECB/EXR/D.USD.EUR.SP00.A",
    "EUR/GBP": "ECB/EXR/D.GBP.EUR.SP00.A",
    "EUR/JPY": "ECB/EXR/D.JPY.EUR.SP00.A",
    "EUR/CHF": "ECB/EXR/D.CHF.EUR.SP00.A",
    # HICP (via ECB mirror)
    "HICP_EA": "ECB/ICP/M.U2.N.000000.4.ANR",
    "HICP_DE": "ECB/ICP/M.DE.N.000000.4.ANR",
    "HICP_FR": "ECB/ICP/M.FR.N.000000.4.ANR",
    "HICP_EA_CORE": "ECB/ICP/M.U2.N.XEF000.4.ANR",
}

RATE_LABELS = {
    "MRR": "Main Refinancing Rate",
    "DFR": "Deposit Facility Rate",
    "MLF": "Marginal Lending Facility",
}


class ECBClient:
    """ECB data client via DBnomics API."""

    def __init__(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        self._timeout = timeout
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=self._timeout,
                follow_redirects=True,
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _fetch_series(self, series_id: str) -> pd.DataFrame:
        """Fetch a single series from DBnomics."""
        url = f"{DBNOMICS_API}/{series_id}"
        logger.info("DBnomics request: %s", series_id)
        resp = self.client.get(url, params={"observations": "1"})
        resp.raise_for_status()

        data = resp.json()
        docs = data.get("series", {}).get("docs", [])
        if not docs:
            return pd.DataFrame()

        doc = docs[0]
        periods = doc.get("period", [])
        values = doc.get("value", [])

        df = pd.DataFrame({"period": periods, "value": values})
        df["series_code"] = doc.get("series_code", series_id)
        return df

    def get_interest_rates(self) -> pd.DataFrame:
        """Get ECB key interest rates."""
        results = []
        for key in ["MRR", "DFR", "MLF"]:
            try:
                df = self._fetch_series(SERIES[key])
                if not df.empty:
                    df["indicator"] = RATE_LABELS[key]
                    # Keep only actual rate changes (remove daily repeats)
                    df = df.drop_duplicates(subset=["value"], keep="last")
                    results.append(df)
            except Exception as e:
                logger.warning("Failed to fetch %s: %s", key, e)

        return pd.concat(results, ignore_index=True) if results else pd.DataFrame()

    def get_exchange_rates(
        self,
        pairs: list[str] | None = None,
        last_n: int = 60,
    ) -> pd.DataFrame:
        """Get EUR exchange rates."""
        if pairs is None:
            pairs = ["EUR/USD", "EUR/GBP", "EUR/JPY"]

        results = []
        for pair in pairs:
            if pair not in SERIES:
                continue
            try:
                df = self._fetch_series(SERIES[pair])
                if not df.empty:
                    df["pair"] = pair
                    df = df.tail(last_n)
                    results.append(df)
            except Exception as e:
                logger.warning("Failed to fetch %s: %s", pair, e)

        return pd.concat(results, ignore_index=True) if results else pd.DataFrame()

    def get_hicp(self) -> pd.DataFrame:
        """Get HICP from ECB mirror via DBnomics."""
        results = []
        hicp_keys = {
            "HICP_EA": "Euro Area",
            "HICP_DE": "Germany",
            "HICP_FR": "France",
            "HICP_EA_CORE": "Euro Area (Core)",
        }

        for key, label in hicp_keys.items():
            try:
                df = self._fetch_series(SERIES[key])
                if not df.empty:
                    df["geo"] = label
                    results.append(df)
            except Exception as e:
                logger.warning("Failed to fetch %s: %s", key, e)

        return pd.concat(results, ignore_index=True) if results else pd.DataFrame()

    def fetch_all(self) -> dict[str, pd.DataFrame]:
        """Fetch all ECB indicators."""
        result: dict[str, pd.DataFrame] = {}

        result["interest_rates"] = self.get_interest_rates()
        logger.info("ECB rates: %d rows", len(result["interest_rates"]))

        result["exchange_rates"] = self.get_exchange_rates()
        logger.info("ECB FX: %d rows", len(result["exchange_rates"]))

        result["hicp"] = self.get_hicp()
        logger.info("ECB HICP: %d rows", len(result["hicp"]))

        return result
