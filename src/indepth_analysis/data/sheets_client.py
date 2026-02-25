import logging
import re

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from indepth_analysis.models.portfolio import PortfolioHolding

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


class SheetsClient:
    def __init__(self, credentials_path: str, sheet_id: str) -> None:
        self.sheet_id = sheet_id
        creds = Credentials.from_service_account_file(credentials_path, scopes=SCOPES)
        self._service = build("sheets", "v4", credentials=creds)

    def read_holdings(self, range_name: str = "A:F") -> list[PortfolioHolding]:
        result = (
            self._service.spreadsheets()
            .values()
            .get(spreadsheetId=self.sheet_id, range=range_name)
            .execute()
        )
        rows = result.get("values", [])
        if not rows:
            return []

        header = [c.strip().lower() for c in rows[0]]
        holdings: list[PortfolioHolding] = []

        for i, row in enumerate(rows[1:], start=2):
            try:
                h = self._parse_row(header, row)
                if h:
                    holdings.append(h)
            except Exception:
                logger.debug("Skipping messy row %d", i)

        return holdings

    def _parse_row(self, header: list[str], row: list[str]) -> PortfolioHolding | None:
        if len(row) < 2:
            return None

        data: dict[str, str] = {}
        for i, val in enumerate(row):
            if i < len(header):
                data[header[i]] = val.strip()

        ticker = self._find_field(data, ["ticker", "symbol", "stock", "name"])
        if not ticker:
            return None
        ticker = re.sub(r"[^A-Za-z.]", "", ticker).upper()
        if not ticker:
            return None

        shares = self._parse_number(
            self._find_field(
                data,
                ["shares", "quantity", "qty", "units"],
            )
        )
        if shares is None or shares <= 0:
            return None

        value = self._parse_number(
            self._find_field(
                data,
                [
                    "market value",
                    "value",
                    "market_value",
                    "total",
                ],
            )
        )
        cost = self._parse_number(
            self._find_field(
                data,
                [
                    "cost basis",
                    "cost",
                    "cost_basis",
                    "avg cost",
                ],
            )
        )

        return PortfolioHolding(
            ticker=ticker,
            shares=shares,
            market_value=value,
            cost_basis=cost,
        )

    def _find_field(self, data: dict[str, str], candidates: list[str]) -> str | None:
        for key in candidates:
            if key in data and data[key]:
                return data[key]
        return None

    def _parse_number(self, val: str | None) -> float | None:
        if not val:
            return None
        cleaned = re.sub(r"[,$\s]", "", val)
        try:
            return float(cleaned)
        except ValueError:
            return None
