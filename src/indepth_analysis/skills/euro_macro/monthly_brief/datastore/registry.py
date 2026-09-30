"""시계열 레지스트리 — 결정론 수집 대상의 선언적 정의.

각 항목은 ``SeriesSpec``: id·한국어 제목·단위·주기·지역·개념(concept)·수집기(source)·
쿼리·상태 규칙. ``store.build``가 이 목록을 순회해 ``series_store.json``을 만든다.

규약
- ``concept``는 같은 경제 개념을 가리키는 식별자다. ``role == "primary"`` 계열끼리는
  concept가 겹치면 안 된다(검증기 FAIL). 교차검증용 로컬 계열은 ``role = "xcheck"``.
- ``source`` ∈ eurostat | ecb | bbk | yf | fred | local_db | derived.
  (``llm_web``은 레지스트리가 아니라 ``ROOT/data/web_series_*.json``에서 흡수 —
  ``WEB_SERIES_MAP`` 참조.)
- ``status_rule`` ∈ final | eurostat_flags | hicp_flash | sdmx_flags | spot.
- 주기 ``freq`` ∈ D | M | Q | A. 기간 라벨: D=YYYY-MM-DD, M=YYYY-MM, Q=YYYY-Qn, A=YYYY.
"""

from __future__ import annotations

from dataclasses import dataclass, field

TIERS = ("api", "local_db", "market", "llm_web")
SOURCE_TIER = {
    "eurostat": "api",
    "ecb": "api",
    "bbk": "api",
    "fred": "api",
    "yf": "market",
    "local_db": "local_db",
    "llm_web": "llm_web",
}
SOURCE_LABEL = {
    "eurostat": "Eurostat",
    "ecb": "ECB Data Portal",
    "bbk": "Deutsche Bundesbank",
    "fred": "FRED (St. Louis Fed)",
    "yf": "Yahoo Finance(yfinance)",
    "local_db": "로컬 캘린더 DB(optionsdeck)",
    "llm_web": "웹 리서치(LLM 수집)",
}
EA_GEOS = ["EA", "EA21", "EA20"]  # 2026-01 불가리아 가입 → EA21. 데이터셋마다 코드 상이
GEO_KO = {
    "EA": "유로존",
    "DE": "독일",
    "FR": "프랑스",
    "IT": "이탈리아",
    "ES": "스페인",
    "US": "미국",
    "GLOBAL": "글로벌",
}


@dataclass(frozen=True)
class SeriesSpec:
    id: str
    title_ko: str
    unit: str
    freq: str
    geo: str
    concept: str
    source: str
    query: dict = field(default_factory=dict)
    status_rule: str = "final"
    decimals: int = 1
    start: str = "2019-01"
    role: str = "primary"
    xcheck_of: str = ""  # role=xcheck일 때 대조 대상 concept
    note: str = ""


def _es(
    sid: str,
    title: str,
    unit: str,
    freq: str,
    geo: str,
    concept: str,
    dataset: str,
    filters: dict,
    *,
    rule: str = "eurostat_flags",
    decimals: int = 1,
    start: str = "2019-01",
    note: str = "",
) -> SeriesSpec:
    geos = EA_GEOS if geo == "EA" else [geo]
    return SeriesSpec(
        id=sid,
        title_ko=title,
        unit=unit,
        freq=freq,
        geo=geo,
        concept=concept,
        source="eurostat",
        query={"dataset": dataset, "filters": filters, "geo_candidates": geos},
        status_rule=rule,
        decimals=decimals,
        start=start,
        note=note,
    )


def _ecb(
    sid: str,
    title: str,
    unit: str,
    freq: str,
    geo: str,
    concept: str,
    key: str,
    *,
    decimals: int = 2,
    start: str = "2019-01",
    rule: str = "sdmx_flags",
    note: str = "",
) -> SeriesSpec:
    return SeriesSpec(
        id=sid,
        title_ko=title,
        unit=unit,
        freq=freq,
        geo=geo,
        concept=concept,
        source="ecb",
        query={"key": key},
        status_rule=rule,
        decimals=decimals,
        start=start,
        note=note,
    )


def _yf(
    sid: str, title: str, unit: str, concept: str, ticker: str, *, decimals: int = 2
) -> SeriesSpec:
    return SeriesSpec(
        id=sid,
        title_ko=title,
        unit=unit,
        freq="D",
        geo="EA",
        concept=concept,
        source="yf",
        query={"ticker": ticker},
        status_rule="spot",
        decimals=decimals,
        start="2024-01-01",
    )


HICP = "prc_hicp_minr"
_H = {"unit": "RCH_A"}
COUNTRIES = ("DE", "FR", "IT", "ES")

SERIES: list[SeriesSpec] = []

# --- 물가 (Eurostat HICP, ECOICOP v2 `prc_hicp_minr`) ---------------------------
for _sid, _code, _t, _c in (
    ("ea_hicp_headline", "TOTAL", "유로존 HICP 헤드라인", "hicp_headline_yoy"),
    ("ea_hicp_core", "TOT_X_NRG_FOOD", "유로존 근원 HICP", "hicp_core_yoy"),
    ("ea_hicp_services", "SERV", "유로존 HICP 서비스", "hicp_services_yoy"),
    ("ea_hicp_energy", "NRG", "유로존 HICP 에너지", "hicp_energy_yoy"),
    ("ea_hicp_food", "FOOD", "유로존 HICP 식품·주류·담배", "hicp_food_yoy"),
    ("ea_hicp_neig", "IGD_NNRG", "유로존 HICP 비에너지 공산품", "hicp_neig_yoy"),
):
    SERIES.append(
        _es(
            _sid,
            _t,
            "% YoY",
            "M",
            "EA",
            _c,
            HICP,
            {**_H, "coicop18": _code},
            rule="hicp_flash",
        )
    )
SERIES.append(
    _es(
        "ea_hicp_headline_mom",
        "유로존 HICP 헤드라인 전월비",
        "% MoM",
        "M",
        "EA",
        "hicp_headline_mom",
        HICP,
        {"unit": "RCH_M", "coicop18": "TOTAL"},
        rule="hicp_flash",
    )
)
for _cc in COUNTRIES:
    SERIES.append(
        _es(
            f"{_cc.lower()}_hicp_headline",
            f"{GEO_KO[_cc]} HICP 헤드라인",
            "% YoY",
            "M",
            _cc,
            f"hicp_headline_yoy_{_cc.lower()}",
            HICP,
            {**_H, "coicop18": "TOTAL"},
        )
    )
for _sid, _code, _t in (
    ("ea_hicp_ctr_energy", "NRG", "에너지"),
    ("ea_hicp_ctr_food", "FOOD", "식품·주류·담배"),
    ("ea_hicp_ctr_neig", "IGD_NNRG", "비에너지 공산품"),
    ("ea_hicp_ctr_services", "SERV", "서비스"),
):
    SERIES.append(
        _es(
            _sid,
            f"유로존 HICP 기여도: {_t}",
            "%p",
            "M",
            "EA",
            f"hicp_contribution_{_code.lower()}",
            "prc_hicp_ctr",
            {"unit": "PC_PNT", "coicop18": _code},
            decimals=2,
            start="2023-01",
        )
    )

# --- 성장 (namq_10_gdp) ------------------------------------------------------
_GDP = {"s_adj": "SCA", "na_item": "B1GQ"}
for _cc in ("EA", *COUNTRIES):
    SERIES.append(
        _es(
            f"{_cc.lower()}_gdp_qoq",
            f"{GEO_KO[_cc]} 실질 GDP 전기비",
            "% QoQ",
            "Q",
            _cc,
            f"gdp_qoq_{_cc.lower()}",
            "namq_10_gdp",
            {**_GDP, "unit": "CLV_PCH_PRE"},
            start="2019-Q1",
        )
    )
    SERIES.append(
        _es(
            f"{_cc.lower()}_gdp_yoy",
            f"{GEO_KO[_cc]} 실질 GDP 전년동기비",
            "% YoY",
            "Q",
            _cc,
            f"gdp_yoy_{_cc.lower()}",
            "namq_10_gdp",
            {**_GDP, "unit": "CLV_PCH_SM"},
            start="2019-Q1",
        )
    )
for _sid, _item, _t in (
    ("ea_gdp_ctr_consumption", "P31_S14_S15", "가계소비"),
    ("ea_gdp_ctr_government", "P3_S13", "정부소비"),
    ("ea_gdp_ctr_investment", "P51G", "총고정자본형성"),
    ("ea_gdp_ctr_inventories", "P52_P53", "재고변동"),
    ("ea_gdp_ctr_netexports", "P6X7", "순수출"),
):
    SERIES.append(
        _es(
            _sid,
            f"유로존 GDP 성장 기여도: {_t}",
            "%p",
            "Q",
            "EA",
            f"gdp_contribution_{_item.lower()}",
            "namq_10_gdp",
            {"s_adj": "SCA", "na_item": _item, "unit": "CON_PPCH_PRE"},
            decimals=2,
            start="2022-Q1",
        )
    )

# --- 노동·심리·실물 -------------------------------------------------------------
for _cc in ("EA", *COUNTRIES):
    SERIES.append(
        _es(
            f"{_cc.lower()}_unemployment",
            f"{GEO_KO[_cc]} 실업률",
            "%",
            "M",
            _cc,
            f"unemployment_{_cc.lower()}",
            "une_rt_m",
            {"s_adj": "SA", "age": "TOTAL", "sex": "T", "unit": "PC_ACT"},
        )
    )
SERIES += [
    _es(
        "ea_esi",
        "유로존 경기체감지수(ESI)",
        "index (LTA=100)",
        "M",
        "EA",
        "esi_ea",
        "ei_bssi_m_r2",
        {"s_adj": "SA", "indic": "BS-ESI-I"},
    ),
    _es(
        "ea_consumer_confidence",
        "유로존 소비자신뢰지수",
        "balance",
        "M",
        "EA",
        "consumer_confidence_ea",
        "ei_bssi_m_r2",
        {"s_adj": "SA", "indic": "BS-CSMCI-BAL"},
    ),
    _es(
        "ea_industry_confidence",
        "유로존 산업신뢰지수",
        "balance",
        "M",
        "EA",
        "industry_confidence_ea",
        "ei_bssi_m_r2",
        {"s_adj": "SA", "indic": "BS-ICI-BAL"},
    ),
    _es(
        "ea_ip_yoy",
        "유로존 산업생산 전년비(역일조정)",
        "% YoY",
        "M",
        "EA",
        "industrial_production_yoy_ea",
        "sts_inpr_m",
        {"indic_bt": "PRD", "nace_r2": "B-D", "s_adj": "CA", "unit": "PCH_SM"},
    ),
    _es(
        "de_ip_yoy",
        "독일 산업생산 전년비(역일조정)",
        "% YoY",
        "M",
        "DE",
        "industrial_production_yoy_de",
        "sts_inpr_m",
        {"indic_bt": "PRD", "nace_r2": "B-D", "s_adj": "CA", "unit": "PCH_SM"},
    ),
    _es(
        "ea_ip_mom",
        "유로존 산업생산 전월비(계절조정)",
        "% MoM",
        "M",
        "EA",
        "industrial_production_mom_ea",
        "sts_inpr_m",
        {"indic_bt": "PRD", "nace_r2": "B-D", "s_adj": "SCA", "unit": "PCH_PRE"},
    ),
    _es(
        "ea_retail_yoy",
        "유로존 소매판매량 전년비(역일조정)",
        "% YoY",
        "M",
        "EA",
        "retail_sales_yoy_ea",
        "sts_trtu_m",
        {"indic_bt": "VOL_SLS", "nace_r2": "G47", "s_adj": "CA", "unit": "PCH_SM"},
    ),
]

# --- 통화정책·금리 (ECB·Bundesbank) -------------------------------------------
SERIES += [
    _ecb(
        "ecb_dfr",
        "ECB 예금금리(DFR)",
        "%",
        "D",
        "EA",
        "ecb_dfr",
        "FM/D.U2.EUR.4F.KR.DFR.LEV",
        start="2022-01-01",
        note="일별 적용 수준(발효일 기준)",
    ),
    _ecb(
        "ecb_mro",
        "ECB 주요 리파이낸싱 금리(MRO)",
        "%",
        "D",
        "EA",
        "ecb_mro",
        "FM/D.U2.EUR.4F.KR.MRR_FR.LEV",
        start="2022-01-01",
    ),
    _ecb(
        "ecb_mlf",
        "ECB 한계대출금리(MLF)",
        "%",
        "D",
        "EA",
        "ecb_mlf",
        "FM/D.U2.EUR.4F.KR.MLFR.LEV",
        start="2022-01-01",
    ),
    _ecb(
        "ecb_dfr_changes",
        "ECB 예금금리 변경(발효일)",
        "%",
        "D",
        "EA",
        "ecb_dfr_change_dates",
        "FM/B.U2.EUR.4F.KR.DFR.LEV",
        start="2019-01-01",
        note="변경 발효일만 관측",
    ),
    _ecb(
        "ecb_mro_changes",
        "ECB MRO 변경(발효일)",
        "%",
        "D",
        "EA",
        "ecb_mro_change_dates",
        "FM/B.U2.EUR.4F.KR.MRR_FR.LEV",
        start="2019-01-01",
    ),
    _ecb(
        "ecb_mlf_changes",
        "ECB MLF 변경(발효일)",
        "%",
        "D",
        "EA",
        "ecb_mlf_change_dates",
        "FM/B.U2.EUR.4F.KR.MLFR.LEV",
        start="2019-01-01",
    ),
    _ecb(
        "estr",
        "€STR(유로 단기금리)",
        "%",
        "D",
        "EA",
        "estr",
        "EST/B.EU000A2X2A25.WT",
        decimals=3,
        start="2024-01-01",
    ),
    _ecb(
        "ea_aaa_10y",
        "유로존 AAA 국채 10년 스팟(YC)",
        "%",
        "D",
        "EA",
        "ea_aaa_curve_10y",
        "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y",
        start="2024-01-01",
    ),
]
for _sid, _tenor, _t in (
    ("de_bund_2y", "R02XX", "2년"),
    ("de_bund_10y", "R10XX", "10년"),
):
    SERIES.append(
        SeriesSpec(
            id=_sid,
            title_ko=f"독일 국채(Bund) {_t} 수익률",
            unit="%",
            freq="D",
            geo="DE",
            concept=f"bund_{_tenor[1:3].lstrip('0')}y_daily",
            source="bbk",
            query={
                "flow": "BBSIS",
                "key": f"D.I.ZST.ZI.EUR.S1311.B.A604.{_tenor}.R.A.A._Z._Z.A",
            },
            status_rule="final",
            decimals=2,
            start="2024-01-01",
            note="Bundesbank 스벤손 기간구조(상장 연방채) 일별",
        )
    )
for _cc in COUNTRIES:
    SERIES.append(
        _ecb(
            f"{_cc.lower()}_10y_m",
            f"{GEO_KO[_cc]} 10년 국채수익률(월평균)",
            "%",
            "M",
            _cc,
            f"gov10y_monthly_{_cc.lower()}",
            f"IRS/M.{_cc}.L.L40.CI.0000.EUR.N.Z",
            start="2019-01",
        )
    )
for _cc in ("FR", "IT", "ES"):
    SERIES.append(
        SeriesSpec(
            id=f"{_cc.lower()}_spread_m",
            title_ko=f"{GEO_KO[_cc]}-독일 10년 스프레드(월평균)",
            unit="bp",
            freq="M",
            geo=_cc,
            concept=f"spread10y_monthly_{_cc.lower()}",
            source="derived",
            query={
                "op": "spread_bp",
                "a": f"{_cc.lower()}_10y_m",
                "b": "de_10y_m",
            },
            decimals=0,
            note="(해당국 − 독일) × 100, ECB IRS 월평균",
        )
    )

# --- 환율 (ECB 기준환율) ---------------------------------------------------------
for _q, _t, _d in (("USD", "EUR/USD", 4), ("KRW", "EUR/KRW", 2), ("GBP", "EUR/GBP", 4)):
    SERIES.append(
        _ecb(
            f"eur{_q.lower()}",
            f"{_t} (ECB 기준환율)",
            f"{_q} per EUR",
            "D",
            "EA",
            f"fx_eur{_q.lower()}",
            f"EXR/D.{_q}.EUR.SP00.A",
            decimals=_d,
            start="2023-01-01",
            rule="spot",
        )
    )
SERIES.append(
    _ecb(
        "eurjpy",
        "EUR/JPY (ECB 기준환율)",
        "JPY per EUR",
        "D",
        "EA",
        "fx_eurjpy",
        "EXR/D.JPY.EUR.SP00.A",
        decimals=2,
        start="2023-01-01",
        rule="spot",
    )
)

# --- 주식·원자재 (yfinance, FRED) ----------------------------------------------
SERIES += [
    _yf("stoxx600", "STOXX Europe 600", "index", "equity_stoxx600", "^STOXX"),
    _yf("sx5e", "Euro STOXX 50", "index", "equity_sx5e", "^STOXX50E"),
    _yf("dax", "DAX", "index", "equity_dax", "^GDAXI"),
    _yf("cac40", "CAC 40", "index", "equity_cac40", "^FCHI"),
    _yf("ftsemib", "FTSE MIB", "index", "equity_ftsemib", "FTSEMIB.MI"),
    _yf("ibex35", "IBEX 35", "index", "equity_ibex35", "^IBEX"),
    _yf(
        "banks_proxy",
        "유럽 은행 섹터(ETF 프록시 EXV1)",
        "EUR",
        "equity_sector_banks",
        "EXV1.DE",
    ),
    _yf(
        "autos_proxy",
        "유럽 자동차 섹터(ETF 프록시 EXV5)",
        "EUR",
        "equity_sector_autos",
        "EXV5.DE",
    ),
    _yf("brent_fut", "Brent 근월물 선물", "USD/bbl", "brent_front_future", "BZ=F"),
    _yf("ttf", "TTF 천연가스 근월물", "EUR/MWh", "ttf_front_future", "TTF=F"),
    SeriesSpec(
        id="brent_dated",
        title_ko="Brent 현물(Dated, FRED)",
        unit="USD/bbl",
        freq="D",
        geo="GLOBAL",
        concept="brent_dated_spot",
        source="fred",
        query={"id": "DCOILBRENTEU"},
        status_rule="spot",
        decimals=2,
        start="2023-01-01",
        note="EIA 현물가격(FRED). 선물(BZ=F)과 별개 개념",
    ),
]

# --- 신용 (ECB BSI·MIR) --------------------------------------------------------
SERIES += [
    _ecb(
        "ea_loans_nfc",
        "유로존 기업대출 증가율(조정)",
        "% YoY",
        "M",
        "EA",
        "loan_growth_nfc",
        "BSI/M.U2.Y.U.A20T.A.I.U2.2240.Z01.A",
        decimals=1,
    ),
    _ecb(
        "ea_loans_hh",
        "유로존 가계대출 증가율(조정)",
        "% YoY",
        "M",
        "EA",
        "loan_growth_hh",
        "BSI/M.U2.Y.U.A20T.A.I.U2.2250.Z01.A",
        decimals=1,
    ),
    _ecb(
        "ea_rate_nfc",
        "유로존 기업 차입비용(신규)",
        "%",
        "M",
        "EA",
        "lending_rate_nfc",
        "MIR/M.U2.B.A2I.AM.R.A.2240.EUR.N",
    ),
    _ecb(
        "ea_rate_mortgage",
        "유로존 가계 주택담보 차입비용(신규)",
        "%",
        "M",
        "EA",
        "lending_rate_mortgage",
        "MIR/M.U2.B.A2C.AM.R.A.2250.EUR.N",
    ),
]

# --- 재정 (Eurostat) -----------------------------------------------------------
for _cc in ("EA", *COUNTRIES):
    SERIES.append(
        _es(
            f"{_cc.lower()}_deficit",
            f"{GEO_KO[_cc]} 재정수지(GDP 대비)",
            "% of GDP",
            "A",
            _cc,
            f"gov_balance_{_cc.lower()}",
            "gov_10dd_edpt1",
            {"unit": "PC_GDP", "sector": "S13", "na_item": "B9"},
            start="2015",
        )
    )
    SERIES.append(
        _es(
            f"{_cc.lower()}_debt_q",
            f"{GEO_KO[_cc]} 정부부채(GDP 대비, 분기)",
            "% of GDP",
            "Q",
            _cc,
            f"gov_debt_{_cc.lower()}",
            "gov_10q_ggdebt",
            {"unit": "PC_GDP", "sector": "S13", "na_item": "GD"},
            start="2019-Q1",
        )
    )

# --- 로컬 교차검증 계열 (optionsdeck 캘린더 실적) ----------------------------------
SERIES += [
    SeriesSpec(
        id="xc_ea_pmi_mfg",
        title_ko="유로존 제조업 PMI(로컬 캘린더 실적)",
        unit="index",
        freq="M",
        geo="EA",
        concept="xcheck_pmi_mfg_ea",
        source="local_db",
        query={"calendar_series": "EU.PMI_MFG", "kind": "pmi"},
        role="xcheck",
        xcheck_of="pmi_manufacturing_ea",
        start="2024-01",
    ),
    SeriesSpec(
        id="xc_ea_pmi_svc",
        title_ko="유로존 서비스업 PMI(로컬 캘린더 실적)",
        unit="index",
        freq="M",
        geo="EA",
        concept="xcheck_pmi_services_ea",
        source="local_db",
        query={"calendar_series": "EU.PMI_SVC", "kind": "pmi"},
        role="xcheck",
        xcheck_of="pmi_services_ea",
        start="2024-01",
    ),
    SeriesSpec(
        id="xc_ea_hicp",
        title_ko="유로존 HICP(로컬 캘린더 실적)",
        unit="% YoY",
        freq="M",
        geo="EA",
        concept="xcheck_hicp_headline_ea",
        source="local_db",
        query={"calendar_series": "EU.HICP_YOY", "kind": "hicp"},
        role="xcheck",
        xcheck_of="hicp_headline_yoy",
        start="2024-01",
    ),
]

BY_ID: dict[str, SeriesSpec] = {s.id: s for s in SERIES}

# web_series_<KEY>.json 흡수 매핑 (WP3 SERIES 프롬프트 id → concept/제목)
WEB_SERIES_MAP: dict[str, tuple[str, str, str]] = {
    "ea_pmi_composite": ("pmi_composite_ea", "유로존 종합 PMI", "index"),
    "ea_pmi_manufacturing": ("pmi_manufacturing_ea", "유로존 제조업 PMI", "index"),
    "ea_pmi_services": ("pmi_services_ea", "유로존 서비스업 PMI", "index"),
    "de_pmi_composite": ("pmi_composite_de", "독일 종합 PMI", "index"),
    "fr_pmi_composite": ("pmi_composite_fr", "프랑스 종합 PMI", "index"),
    "it_pmi_composite": ("pmi_composite_it", "이탈리아 종합 PMI", "index"),
    "es_pmi_composite": ("pmi_composite_es", "스페인 종합 PMI", "index"),
    "estr_ois_implied_dfr": ("ois_implied_dfr", "OIS 내재 DFR 경로", "%"),
    # W2 프롬프트 id (2026-09-30 시험 실행에서 id 불일치 발견 → 매핑 추가)
    "ois_dfr_asof": ("ois_implied_dfr", "OIS 내재 DFR(기준일)", "%"),
    "ois_dfr_prev": ("ois_implied_dfr_prev", "OIS 내재 DFR(1개월 전)", "%"),
    "ois_cum_bp_asof": ("ois_cum_bp", "OIS 내재 누적 변화(bp)", "bp"),
    "sma_dfr_median": ("sma_dfr_median", "ECB 통화분석가 설문(SMA) DFR 중앙값", "%"),
    "ois_hike_prob": ("ois_hike_prob", "회의별 인상 확률(시장 내재)", "%"),
    "bbg_survey_dfr": ("bbg_survey_dfr", "Bloomberg 이코노미스트 설문 DFR 중앙값", "%"),
}
# llm_web 계열 교차검증 허용오차 (concept → 절대값)
XCHECK_TOL = {"pmi_manufacturing_ea": 0.3, "pmi_services_ea": 0.3}

# ECB 정책금리 변경 결정일 정적 표 (결정일 → 발효일).
# 2022-07 이후 발효일 = 결정일 + 6일(수요일). 표에 없는 변경은 규칙으로 역산하고
# 표기 ``derived``로 남긴다.
ECB_DECISIONS: list[tuple[str, str]] = [
    ("2022-07-21", "2022-07-27"),
    ("2022-09-08", "2022-09-14"),
    ("2022-10-27", "2022-11-02"),
    ("2022-12-15", "2022-12-21"),
    ("2023-02-02", "2023-02-08"),
    ("2023-03-16", "2023-03-22"),
    ("2023-05-04", "2023-05-10"),
    ("2023-06-15", "2023-06-21"),
    ("2023-07-27", "2023-08-02"),
    ("2023-09-14", "2023-09-20"),
    ("2024-06-06", "2024-06-12"),
    ("2024-09-12", "2024-09-18"),
    ("2024-10-17", "2024-10-23"),
    ("2024-12-12", "2024-12-18"),
    ("2025-01-30", "2025-02-05"),
    ("2025-03-06", "2025-03-12"),
    ("2025-04-17", "2025-04-23"),
    ("2025-06-05", "2025-06-11"),
]
