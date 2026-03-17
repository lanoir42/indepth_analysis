"""Eurostat JSON Statistics API client for European macroeconomic data.

Free, no authentication required.
Docs: https://ec.europa.eu/eurostat/web/user-guides/data-browser/api-data-access
"""

import logging
from datetime import date
from functools import reduce

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

JSON_API = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
DEFAULT_TIMEOUT = 30.0

# Dataset codes
HICP_INDEX = "prc_hicp_midx"
HICP_ANNUAL_RATE = "prc_hicp_manr"
INDUSTRIAL_PROD = "sts_inpr_m"
TRADE_EA = "ext_lt_maineu"

# Country codes
GEO_EA20 = "EA20"
GEO_EU27 = "EU27_2020"
GEO_DE = "DE"
GEO_FR = "FR"
GEO_IT = "IT"
GEO_ES = "ES"

GEO_LABELS = {
    "EA20": "Euro Area",
    "EU27_2020": "EU-27",
    "DE": "Germany",
    "FR": "France",
    "IT": "Italy",
    "ES": "Spain",
}

# COICOP codes
COICOP_ALL = "CP00"
COICOP_FOOD = "CP01"
COICOP_ENERGY = "NRG"
COICOP_CORE = "TOT_X_NRG_FOOD"

COICOP_LABELS = {
    "CP00": "All items",
    "CP01": "Food",
    "NRG": "Energy",
    "TOT_X_NRG_FOOD": "Core (ex food & energy)",
}


class EurostatClient:
    """Client for Eurostat JSON Statistics API."""

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

    def _fetch_json(
        self,
        dataset: str,
        params: list[tuple[str, str]],
    ) -> dict:
        """Fetch data from Eurostat JSON statistics API.

        Uses repeated query params (e.g. geo=DE&geo=FR) as required
        by the Eurostat API.
        """
        url = f"{JSON_API}/{dataset}"
        logger.info("Eurostat request: %s", dataset)
        resp = self.client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _json_to_dataframe(data: dict) -> pd.DataFrame:
        """Convert Eurostat JSON-stat response to a tidy DataFrame.

        The JSON response uses positional indices for values.
        Position = sum of (dim_index * product_of_subsequent_sizes).
        """
        dimensions = data.get("id", [])
        sizes = data.get("size", [])
        values = data.get("value", {})

        if not dimensions or not values:
            return pd.DataFrame()

        # Build dimension index maps
        dim_indices: list[list[str]] = []
        dim_labels_map: list[dict[str, str]] = []
        for dim_name in dimensions:
            dim_info = data["dimension"][dim_name]["category"]
            # index is {code: position}
            idx = dim_info.get("index", {})
            labels = dim_info.get("label", {})
            # Sort by position
            sorted_codes = sorted(idx.items(), key=lambda x: x[1])
            dim_indices.append([code for code, _ in sorted_codes])
            dim_labels_map.append(labels)

        # Generate all rows from positional values
        rows = []
        for pos_str, val in values.items():
            pos = int(pos_str)
            # Decode position to dimension indices
            indices = []
            remainder = pos
            for i in range(len(sizes)):
                product = reduce(lambda a, b: a * b, sizes[i + 1 :], 1)
                idx = remainder // product
                remainder = remainder % product
                indices.append(idx)

            row: dict[str, str | float] = {}
            for i, dim_name in enumerate(dimensions):
                code = dim_indices[i][indices[i]]
                row[dim_name] = code
                label = dim_labels_map[i].get(code, code)
                row[f"{dim_name}_label"] = label

            row["value"] = val
            rows.append(row)

        return pd.DataFrame(rows)

    def get_hicp(
        self,
        geos: list[str] | None = None,
        coicops: list[str] | None = None,
        start_period: str | None = None,
        end_period: str | None = None,
        rate: bool = True,
    ) -> pd.DataFrame:
        """Get HICP data (annual rate of change or index)."""
        if geos is None:
            geos = [GEO_EA20, GEO_DE, GEO_FR]
        if coicops is None:
            coicops = [COICOP_ALL]

        dataset = HICP_ANNUAL_RATE if rate else HICP_INDEX
        params: list[tuple[str, str]] = []
        for g in geos:
            params.append(("geo", g))
        for c in coicops:
            params.append(("coicop", c))
        if start_period:
            params.append(("sinceTimePeriod", start_period))
        if end_period:
            params.append(("untilTimePeriod", end_period))

        data = self._fetch_json(dataset, params)
        df = self._json_to_dataframe(data)

        if not df.empty and "geo" in df.columns:
            df["geo_label"] = df["geo"].map(lambda x: GEO_LABELS.get(x, x))
        if not df.empty and "coicop" in df.columns:
            df["coicop_label"] = df["coicop"].map(lambda x: COICOP_LABELS.get(x, x))

        return df

    def get_industrial_production(
        self,
        geos: list[str] | None = None,
        start_period: str | None = None,
        end_period: str | None = None,
    ) -> pd.DataFrame:
        """Get industrial production index, calendar adjusted."""
        if geos is None:
            geos = [GEO_EA20, GEO_DE, GEO_FR]

        params: list[tuple[str, str]] = [
            ("s_adj", "CA"),
            ("unit", "I21"),
            ("nace_r2", "B-D"),
        ]
        for g in geos:
            params.append(("geo", g))
        if start_period:
            params.append(("sinceTimePeriod", start_period))
        if end_period:
            params.append(("untilTimePeriod", end_period))

        data = self._fetch_json(INDUSTRIAL_PROD, params)
        df = self._json_to_dataframe(data)

        if not df.empty and "geo" in df.columns:
            df["geo_label"] = df["geo"].map(lambda x: GEO_LABELS.get(x, x))

        return df

    def get_trade(
        self,
        start_period: str | None = None,
        end_period: str | None = None,
    ) -> pd.DataFrame:
        """Get EA20 external trade data (imports/exports)."""
        params: list[tuple[str, str]] = [
            ("geo", GEO_EA20),
            ("sitc06", "TOTAL"),
            ("partner", "EXT_EA20"),
        ]
        if start_period:
            params.append(("sinceTimePeriod", start_period))
        if end_period:
            params.append(("untilTimePeriod", end_period))

        try:
            data = self._fetch_json(TRADE_EA, params)
            return self._json_to_dataframe(data)
        except httpx.HTTPStatusError:
            logger.warning("Trade data not available for this period")
            return pd.DataFrame()

    def fetch_all_macro(
        self,
        start_period: str = "2025-01",
        end_period: str | None = None,
    ) -> dict[str, pd.DataFrame]:
        """Fetch all key macro indicators."""
        if end_period is None:
            end_period = date.today().strftime("%Y-%m")

        geos = [GEO_EA20, GEO_DE, GEO_FR, GEO_IT, GEO_ES]
        coicops = [COICOP_ALL, COICOP_FOOD, COICOP_ENERGY, COICOP_CORE]
        result: dict[str, pd.DataFrame] = {}

        try:
            result["hicp"] = self.get_hicp(
                geos=geos,
                coicops=coicops,
                start_period=start_period,
                end_period=end_period,
            )
            logger.info("HICP: %d rows", len(result["hicp"]))
        except Exception as e:
            logger.error("Failed to fetch HICP: %s", e)
            result["hicp"] = pd.DataFrame()

        try:
            result["industrial_production"] = self.get_industrial_production(
                geos=geos,
                start_period=start_period,
                end_period=end_period,
            )
            logger.info(
                "Industrial production: %d rows",
                len(result["industrial_production"]),
            )
        except Exception as e:
            logger.error("Failed to fetch industrial production: %s", e)
            result["industrial_production"] = pd.DataFrame()

        try:
            result["trade"] = self.get_trade(start_period, end_period)
            logger.info("Trade: %d rows", len(result["trade"]))
        except Exception as e:
            logger.error("Failed to fetch trade: %s", e)
            result["trade"] = pd.DataFrame()

        return result
