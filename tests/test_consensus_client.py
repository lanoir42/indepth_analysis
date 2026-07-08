"""Smoke tests for ConsensusClient (network-free via monkeypatched fetch)."""

from indepth_analysis.data.consensus_client import ConsensusClient


def _fake_series(values):
    return [{"period": p, "value": v} for p, v in values]


def test_get_projection_prefers_imf(monkeypatch):
    c = ConsensusClient()
    monkeypatch.setattr(
        c,
        "_fetch_imf",
        lambda geo, subj: {
            "source": "imf_weo",
            "series_id": "IMF/WEO:2025-04/DEU.NGDP_RPCH.pcent_change",
            "vintage": "2025-04",
            "values": _fake_series([("2026", 1.0), ("2027", 1.4)]),
        },
    )
    monkeypatch.setattr(c, "_fetch_oecd", lambda geo, subj: {})
    rec = c.get_projection("DE", "gdp_growth_pct")
    assert rec["geo"] == "DE"
    assert rec["source"] == "imf_weo"
    assert rec["vintage"] == "2025-04"
    assert rec["values"][-1]["period"] == "2027"


def test_get_projection_falls_back_to_oecd(monkeypatch):
    c = ConsensusClient()
    monkeypatch.setattr(c, "_fetch_imf", lambda geo, subj: {})
    monkeypatch.setattr(
        c,
        "_fetch_oecd",
        lambda geo, subj: {
            "source": "oecd_eo",
            "series_id": "OECD/EO/EA17.GDPV_ANNPCT.A",
            "values": _fake_series([("2025", 1.4)]),
        },
    )
    rec = c.get_projection("EA", "gdp_growth_pct")
    assert rec["source"] == "oecd_eo"
    assert rec["values"] == [{"period": "2025", "value": 1.4}]


def test_get_projection_unresolved_is_well_formed(monkeypatch):
    c = ConsensusClient()
    monkeypatch.setattr(c, "_fetch_imf", lambda geo, subj: {})
    monkeypatch.setattr(c, "_fetch_oecd", lambda geo, subj: {})
    rec = c.get_projection("RU", "inflation_pct")
    assert rec["source"] == "unresolved"
    assert rec["values"] == []
    assert rec["geo"] == "RU"


def test_fetch_all_never_aborts(monkeypatch):
    c = ConsensusClient()

    def boom(geo, metric):
        raise RuntimeError("network down")

    monkeypatch.setattr(c, "get_projection", boom)
    out = c.fetch_all(geos=["EA", "DE"], metrics=["gdp_growth_pct"])
    assert set(out) == {"gdp_growth_pct"}
    assert len(out["gdp_growth_pct"]) == 2
    assert all(r["source"] == "error" for r in out["gdp_growth_pct"])


def test_fetch_series_parses_dbnomics(monkeypatch):
    c = ConsensusClient()

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "series": {
                    "docs": [
                        {
                            "period": ["2025", "2026", "2027"],
                            "value": [1.2, "NA", 1.5],
                        }
                    ]
                }
            }

    monkeypatch.setattr(c, "_client", type("X", (), {"get": lambda *a, **k: _Resp()})())
    vals = c._fetch_series("IMF/WEO:2025-04/DEU.NGDP_RPCH.pcent_change")
    # NA dropped, floats rounded
    assert vals == [
        {"period": "2025", "value": 1.2},
        {"period": "2027", "value": 1.5},
    ]
