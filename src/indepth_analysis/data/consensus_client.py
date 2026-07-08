"""Consensus / forecast client via DBnomics (keyless).

Forward-looking macro projections for the H2 outlook report: real GDP growth and
consumer-price inflation forecasts for the euro area, the major member states and
the UK, sourced from IMF World Economic Outlook and OECD Economic Outlook
datasets mirrored on DBnomics (https://api.db.nomics.world, no auth).

Honesty principle (same as energy_client): only projections that resolve from a
real structured feed are returned. Forecast vintages and series codes drift, so
each target is best-effort and degrades to an empty-but-annotated record; the
web-research team backfills finer consensus detail (ECB SPF, EC forecast) with
citations rather than this client faking anything.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

DBNOMICS_API = "https://api.db.nomics.world/v22/series"
DEFAULT_TIMEOUT = 30.0

# IMF WEO vintages to try, newest first. WEO ships twice a year (Apr / Oct).
IMF_WEO_VINTAGES = ["2026-04", "2025-10", "2025-04"]

# geo -> IMF ISO3 code (WEO REF_AREA).
IMF_GEOS: dict[str, str] = {
    "EA": "U2",  # euro area aggregate in WEO REF_AREA
    "DE": "DEU",
    "FR": "FRA",
    "IT": "ITA",
    "ES": "ESP",
    "UK": "GBR",
    "PL": "POL",
    "RU": "RUS",
}

# IMF WEO subjects of interest.
IMF_SUBJECTS: dict[str, str] = {
    "gdp_growth_pct": "NGDP_RPCH",  # real GDP, annual % change
    "inflation_pct": "PCPIPCH",  # inflation, avg consumer prices, annual % change
}

# OECD Economic Outlook fallback (DBnomics OECD/EO). Location codes differ from
# IMF; the euro area is EA17 in the frozen EO vintage on DBnomics.
OECD_EO_GEOS: dict[str, str] = {
    "EA": "EA17",
    "DE": "DEU",
    "FR": "FRA",
    "IT": "ITA",
    "ES": "ESP",
    "UK": "GBR",
}
OECD_EO_SUBJECTS: dict[str, str] = {
    "gdp_growth_pct": "GDPV_ANNPCT",  # real GDP growth
    "inflation_pct": "CPI_YTYPCT",  # CPI, y/y %
}

GEO_LABELS: dict[str, str] = {
    "EA": "Euro area",
    "DE": "Germany",
    "FR": "France",
    "IT": "Italy",
    "ES": "Spain",
    "UK": "United Kingdom",
    "PL": "Poland",
    "RU": "Russia",
}


class ConsensusClient:
    """Keyless forward-projection client (IMF WEO + OECD EO via DBnomics)."""

    def __init__(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        self._timeout = timeout
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self._timeout, follow_redirects=True)
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _fetch_series(self, series_path: str) -> list[dict]:
        """Fetch one DBnomics series -> list of {period, value}. [] on failure."""
        url = f"{DBNOMICS_API}/{series_path}"
        try:
            resp = self.client.get(url, params={"observations": "1"})
            resp.raise_for_status()
        except Exception as e:  # noqa: BLE001 - never abort the batch
            logger.debug("DBnomics miss %s: %s", series_path, e)
            return []
        docs = resp.json().get("series", {}).get("docs", [])
        if not docs:
            return []
        doc = docs[0]
        out: list[dict] = []
        for p, v in zip(doc.get("period", []), doc.get("value", [])):
            if v is None or (isinstance(v, str) and v.upper() in ("NA", "NAN", "")):
                continue
            try:
                out.append({"period": str(p), "value": round(float(v), 4)})
            except (TypeError, ValueError):
                continue
        return out

    def _fetch_imf(self, geo: str, subject: str) -> dict:
        """Try IMF WEO vintages newest-first for one geo/subject."""
        iso = IMF_GEOS.get(geo)
        if not iso:
            return {}
        for vintage in IMF_WEO_VINTAGES:
            path = f"IMF/WEO:{vintage}/{iso}.{subject}.pcent_change"
            values = self._fetch_series(path)
            if values:
                return {
                    "source": "imf_weo",
                    "series_id": path,
                    "vintage": vintage,
                    "values": values,
                }
        return {}

    def _fetch_oecd(self, geo: str, subject: str) -> dict:
        """OECD Economic Outlook fallback for one geo/subject."""
        loc = OECD_EO_GEOS.get(geo)
        if not loc:
            return {}
        path = f"OECD/EO/{loc}.{subject}.A"
        values = self._fetch_series(path)
        if values:
            return {"source": "oecd_eo", "series_id": path, "values": values}
        return {}

    def get_projection(self, geo: str, metric: str) -> dict:
        """One projection record for a geo/metric, IMF first then OECD.

        metric in {"gdp_growth_pct", "inflation_pct"}. Always returns a
        well-formed record; ``values`` is [] when nothing resolved.
        """
        record: dict = {
            "geo": geo,
            "label": GEO_LABELS.get(geo, geo),
            "metric": metric,
            "unit": "% (annual)",
            "values": [],
        }
        imf = self._fetch_imf(geo, IMF_SUBJECTS.get(metric, ""))
        if imf.get("values"):
            record.update(imf)
            return record
        oecd = self._fetch_oecd(geo, OECD_EO_SUBJECTS.get(metric, ""))
        if oecd.get("values"):
            record.update(oecd)
            return record
        record["source"] = "unresolved"
        return record

    def fetch_all(
        self,
        geos: list[str] | None = None,
        metrics: list[str] | None = None,
    ) -> dict[str, list[dict]]:
        """Fetch GDP-growth and inflation projections for the report geos.

        Returns {metric: [records]}. Unresolved series are kept (values=[]) so
        the gap is visible and the web team knows what to backfill.
        """
        geos = geos or ["EA", "DE", "FR", "IT", "ES", "UK", "PL", "RU"]
        metrics = metrics or ["gdp_growth_pct", "inflation_pct"]
        out: dict[str, list[dict]] = {}
        for metric in metrics:
            recs: list[dict] = []
            for geo in geos:
                try:
                    recs.append(self.get_projection(geo, metric))
                except Exception as e:  # noqa: BLE001
                    logger.warning("projection %s/%s failed: %s", geo, metric, e)
                    recs.append(
                        {
                            "geo": geo,
                            "label": GEO_LABELS.get(geo, geo),
                            "metric": metric,
                            "source": "error",
                            "error": str(e),
                            "values": [],
                        }
                    )
            out[metric] = recs
        return out
