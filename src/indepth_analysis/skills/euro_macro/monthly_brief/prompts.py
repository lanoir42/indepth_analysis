# ruff: noqa: E501
"""월간 유럽 매크로 리포트 v3 — Sonnet 웹리서치·웹 시계열·보충 리서치 프롬프트.

v2 상수(월 하드코딩)는 ``prompts_v2.py``에 그대로 보존한다.

v3 원칙
- **월 독립**: 날짜·연도·회의일·이벤트는 전부 ``Edition``(``ROOT/edition.json``)에서
  주입한다. 템플릿 본문에 특정 연도·월을 쓰지 않는다(테스트가 강제).
- 알려진 사실은 ``ROOT/data/facts.md``(결정론 수집)에서, BI 맥락은
  ``ROOT/sections/<GROUP>.md`` 스캐폴드에서 축별로 잘라 주입한다.
- 모든 프롬프트는 ``claude -p`` 사용자 프롬프트(``<system>`` 태그 금지).

공개 API
- ``RESEARCH_AXES`` (R01~R12), ``WEB_SERIES`` (W1·W2)
- ``edition_vars(ed)`` → 템플릿 변수 dict
- ``build_axis_prompt(key, ed, known, bi_context)``
- ``build_web_series_prompt(key, ed, known)``
- ``build_gap_prompt(round_id, n, items, ed, known)``
- ``AXIS_GROUPS`` (축 → BI 섹션 그룹), ``BI_GROUPS``
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

BI_GROUPS = (
    "ECB",
    "EA_MACRO",
    "DE",
    "FR",
    "IT",
    "ES",
    "UK",
    "EU_POLICY",
    "ENERGY_EXTERNAL",
    "GLOBAL",
)

KNOWN_PLACEHOLDER = (
    "- (data/facts.md 미생성 — 결정론 수집 이전 실행. 이 축의 모든 수치를 1차 출처로 "
    "직접 확인할 것)"
)
BI_PLACEHOLDER = (
    "- (BI 섹션 스캐폴드 없음 — sections/<GROUP>.md 미생성. BI 주장 검증 절은 "
    "'해당 없음'으로 두고 조사 질문에 집중할 것)"
)


# ---------------------------------------------------------------------------
# 회차 변수
# ---------------------------------------------------------------------------


def _d(s: str) -> date:
    return date.fromisoformat(s)


def _month_label(month: str) -> str:
    y, m = month.split("-")
    return f"{y}년 {int(m)}월"


def _prev_month(month: str) -> str:
    y, m = (int(x) for x in month.split("-"))
    y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return f"{y:04d}-{m:02d}"


def edition_vars(ed: Any) -> dict[str, str]:
    """Edition → 템플릿 변수. 모든 날짜·연도 문자열의 유일한 공급원."""
    as_of = _d(ed.as_of)
    year = int(ed.month[:4])
    window = ed.window or {"from": f"{ed.month}-01", "to": ed.as_of}
    ecb = ed.ecb or {}
    return {
        "month_label": _month_label(ed.month),
        "prior_month_label": _month_label(_prev_month(ed.month)),
        "as_of": ed.as_of,
        "report_date": ed.report_date,
        "window_from": window.get("from", f"{ed.month}-01"),
        "window_to": window.get("to", ed.as_of),
        "window": f"{window.get('from', '')} ~ {window.get('to', ed.as_of)}",
        "year": str(year),
        "prev_year": str(year - 1),
        "next_year": str(year + 1),
        "next2_year": str(year + 2),
        "series_start": f"{year - 3}-01",
        "last_meeting": ecb.get("last_meeting")
        or "(edition 미기재 — 직전 ECB 회의일을 확인)",
        "next_meeting": ecb.get("next_meeting")
        or "(edition 미기재 — 다음 ECB 회의일을 확인)",
        "lookback_from": (as_of - timedelta(days=28)).isoformat(),
        "horizon_from": (as_of + timedelta(days=1)).isoformat(),
        "horizon_to": (as_of + timedelta(days=30)).isoformat(),
        "ois_prev_date": (as_of - timedelta(days=30)).isoformat(),
        "phase_ko": getattr(ed, "phase_ko", ed.phase),
    }


def events_block(ed: Any, geos: tuple[str, ...] = ()) -> str:
    """edition.events → 마크다운 목록. geos가 있으면 해당 지역·전역 이벤트만."""
    rows = []
    for ev in ed.events or []:
        geo = str(ev.get("geo", "")).upper()
        if geos and geo and geo not in geos and geo not in ("EU", "GLOBAL", "EA"):
            continue
        rows.append(
            f"- {ev.get('date', '?')} [{geo or '-'}·{ev.get('kind', '-')}] "
            f"{ev.get('title', '')}"
        )
    if not rows:
        return (
            "- (edition.json에 등록된 이벤트 없음 — 조사 대상 기간의 일정을 직접 확인)"
        )
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# 공통 헤더 (v2 공통 규약 계승 + v3 보강)
# ---------------------------------------------------------------------------

RESEARCH_HEADER = """\
유럽 거시경제 월간 리포트용 웹리서처(Sonnet) 과제. 기준 시점 **{as_of} (KST)**. \
조사 대상 기간 **{window}** (대상 월 {month_label}; 기간 안에 발표된 확정치·사건 포함). \
리포트 보고일 {report_date}({phase_ko}). ECB 직전 회의 {last_meeting}, 다음 회의 {next_meeting}.

## 공통 규약 (위반 시 산출물 폐기)
- 모든 사실에 **발표일·수치·기관(1차 출처 우선)·URL**을 붙일 것. 1차 출처: ECB·Eurostat·\
각국 통계청(Destatis·INSEE·ISTAT·INE·CBS)·각국 중앙은행·S&P Global/HCOB·Ifo·ZEW·EU 집행위·\
각국 재무부·의회(Assemblée nationale·Bundestag·Camera·Congreso)·신용평가사 발표문. \
2차: Reuters·Bloomberg·FT·Politico Europe·Handelsblatt·Les Echos·Il Sole 24 Ore·El País.
- 라벨 5종을 문장 끝에 표기: [확정](1차 출처) / [보도] / [추정](리서치사·애널리스트) / \
[시장](가격·프라이싱 스냅샷, 조회 시각 명시) / [미확인].
- **연도 혼동 금지**: {prev_year}년 사건과 {year}년 사건을 뒤섞지 말 것. 반복형 사건(ECB 회의·\
HICP 속보·PMI·예산 표결)은 발생 연·월·일을 반드시 표기. "지난달·최근·이번 주"류 상대 표현 금지 — \
절대 날짜만.
- 컨센서스가 있는 지표는 `실제(예상, 전월)` 형식으로 기록(예: `HICP 2.1%(e2.0%, 전월 2.0%)`). \
참조 기간(예 "8월분")과 발표일을 구분해 쓸 것.
- 미확인은 추정으로 채우지 말 것. 대신 **무엇을 어디서 찾았는데 없었는지**를 `미확인·공백`에 \
남길 것(추가 조사 목록으로 쓰인다). "범위에서 제외" 같은 판단은 쓰지 말 것 — 조사 대상은 전부 조사.
- 공개된 1차 수치(예: ECB 스태프 전망의 모든 연도, 통계청 세부 항목)는 빠짐없이 기록. \
수치가 있는데 기록하지 않는 것은 결함.
- 검색 예산 30~40회. 핵심 1차 원문은 WebFetch로 직접 확인(보도 재인용 금지 원칙).
- 산출은 **표준출력 마크다운 한 덩어리**. 파일을 쓰지 말 것. 한국어(고유명사·원문 인용·수치 원문 유지). \
개조식·명사형 종결. 1인칭·메타서술 금지.

## 이미 확인된 사실 (결정론 수집 — 재조사 금지, 그대로 인용 가능)
{known}

## 이 축과 관련된 Bloomberg Intelligence(BI) 문서 맥락 (발췌)
{bi_context}

## 조사 기간 등록 일정 (edition.json)
{events}

## 출력 형식 (엄수)
```
## 핵심 발견
- (불릿 8~12개, 각 1~2문장, 문장 끝 라벨. 이 축에서 리포트 판단을 바꿀 사실 순)

## 상세
### Q1. <질문 요지>
- (사실. 발표일·수치·기관·URL. 원문 인용은 영문/원어 + 번역)
...

## BI 주장 검증
| BI 주장(요지·문서 날짜) | 판정(지지/반박/부분/미결) | 1차 근거 | URL |
|---|---|---|---|

## 수치 레코드
| metric | value | unit | period | geo | consensus | previous | label | source_name | url | published | note |
|---|---|---|---|---|---|---|---|---|---|---|---|

## 시장 스냅샷 (해당 시)
| instrument | value | as_of(UTC 또는 KST 명시) | change_vs | source | url |
|---|---|---|---|---|---|

## 미확인·공백
- (질문 번호 · 찾은 곳 · 찾지 못한 것 · 공개 예정일이 있으면 그 날짜)

## 출처 목록
| # | 제목 | 기관 | URL | 발행일 |
|---|---|---|---|---|
```
"""

POLITICS_REQUIREMENTS = """\
## 정치 축 필수 요건 (국가·사안마다 전부 채울 것)
1. **행위자 실명**: 대통령·총리·재무장관·주요 정당 대표·원내 지도부·핵심 반대파 — 이름·직함·소속.
2. **의회 구도(산술)**: 원내 의석 총수, 정파·정당별 의석, 과반선, 불신임·예산 통과에 필요한 표 계산, \
기권·결석 시나리오. 상원·연방참사원 등 제2원 구도 포함.
3. **사건 일지**: {window} 동안의 사건을 날짜순 표(날짜 | 사건 | 행위자 | 출처)로. 기간 이후 \
{horizon_to}까지 예정 일정도 별도 표.
4. **정책 내용**: 예산안·개혁안의 실제 수치(세입·세출 항목, 적자 목표 %GDP, 부채비율, 절감액, \
증세·감세 항목)와 쟁점 조항. "예산 갈등" 같은 요약어로 끝내지 말 것.
5. **시장 전달경로**: 국채 스프레드(대 Bund, bp, 날짜별), CDS, 신용등급·전망과 다음 평가 일정\
(S&P·Moody's·Fitch·DBRS·Scope 날짜), 재정 충격(%GDP), 은행주·주가 반응.
6. **여론조사**: 최신 정당 지지율·지도자 지지도(조사기관·조사일·표본), 추세.
7. **시나리오**: 기본·위험·완화 각 시나리오의 **트리거(날짜·표결·조건)**, 대략 확률(출처가 있으면 \
출처 확률, 없으면 [추정] 표기), 스프레드·등급 함의.
"""


# ---------------------------------------------------------------------------
# 리서치 축 (R01~R12)
# ---------------------------------------------------------------------------

RESEARCH_AXES: dict[str, dict[str, Any]] = {
    "R01_ecb": {
        "title": "ECB 1차 원문 — 결정·성명·스태프 전망·기자회견·의사록·위원 발언 지형·TPI/대차대조표·OIS",
        "groups": ("ECB",),
        "geos": ("EA", "ECB"),
        "questions": """\
1. {last_meeting} 통화정책 결정: DFR·MRO·MLF 결정치·변경폭·발효일, 표결 구도(만장일치 여부·반대 위원). \
보도자료(Monetary policy decisions)와 통화정책 성명(Monetary policy statement) 원문의 **경로 문구·\
리스크 평가·데이터 의존 문구**를 영문 원문 + 번역으로 인용(ecb.europa.eu URL).
2. 스태프 거시전망: 가장 최근 전망 회차(3·6·9·12월 회의; {last_meeting}이 전망 회차면 해당 회차)의 \
실질GDP·HICP 헤드라인·HICP 코어 {year}·{next_year}·{next2_year} 수치와 **직전 전망 회차 대비 변화폭**, \
기술적 가정(Brent·가스·EUR/USD·금리 경로), 대안 시나리오(있으면 수치 포함). 전 연도 수치를 빠짐없이 기록.
3. 기자회견 Q&A: 총재 발언 중 향후 경로·인상/인하 논의 여부·의견 분포·에너지 충격 대응·임금·기대인플레·\
환율·국가 스프레드(특히 프랑스)·TPI 관련 문답을 원문 인용. 시장이 주목한 문구와 그 해석.
4. 의사록(Account of the monetary policy meeting): 조사 기간 안에 공개된 의사록 전부 — 공개일, 대상 회의, \
정책위원회 논의 쟁점, 소수 의견, 핵심 문장 원문 인용. {next_meeting} 이전에 공개될 의사록 일정.
5. 정책위원회 위원 발언 지형: 조사 기간 중 공개 발언한 위원 **8명 이상**(집행이사회 + 주요국 중앙은행 총재\
— 독·프·이·스·네·오스트리아·벨기에·핀란드·발트·포르투갈 등). 위원마다 날짜·장소/매체·원문 인용·URL·\
다음 회의 함의. 마지막에 **매파–중도–비둘기 5단 지형표**(위원 | 직함 | 성향 | 근거 발언 날짜) 작성.
6. 대차대조표·TPI: APP·PEPP 보유 잔액과 감소 속도(최근 월 공시), 총자산, 초과유동성, 대출(TLTRO) 잔액, \
운영체계 개편 현황. TPI 발동 요건(4개 적격성 기준)·조사 기간 중 TPI·국가 스프레드에 대한 위원·총재 언급 원문.
7. 시장 프라이싱: €STR OIS 기준 {next_meeting} 회의 및 이후 회의별 내재 DFR·누적 bp·변경 확률 — \
{as_of} 시점과 {ois_prev_date} 무렵 비교. 결정일 전후 Bund 2y·EUR/USD 반응.
8. 전망 분포: Bloomberg·Reuters 이코노미스트 설문(조사일·중앙값·분포), 주요 IB(GS·JPM·MS·DB·BNP·\
Barclays·UBS·ING 등) 경로 전망과 {next_meeting} 회의 컨센서스.
9. {next_meeting} 회의 전 관전 일정: 위원 연설 일정, 의사록 공개일, 주요 데이터.""",
        "budget": "Q1~Q4 ECB 원문 14회, Q5 위원 발언 10회, Q6~Q9 12회",
    },
    "R02_inflation": {
        "title": "유로존 물가 — HICP 속보·확정·구성 기여도·국가별·기저효과·에너지 전가·임금·기대인플레",
        "groups": ("EA_MACRO", "ECB"),
        "geos": ("EA", "DE", "FR", "IT", "ES"),
        "questions": """\
1. 조사 기간에 발표된 유로존 HICP 속보·확정(참조월 명시): 헤드라인·코어(에너지·식품·주류·담배 제외)·\
서비스·비에너지 공산품·식품·에너지 YoY·MoM, 컨센서스, 전월치, 수정 여부. Eurostat 분류·데이터셋 변경\
(분류 체계 개편 여부)이 있으면 그 내용과 시계열 비교 주의점.
2. 구성 기여도: Eurostat 가중치 또는 ECB·기관이 공표한 항목별 기여도(%p). 헤드라인 변화가 어떤 \
항목에서 나왔는지 수치로.
3. 국가별: 독일(Destatis)·프랑스(INSEE)·이탈리아(ISTAT)·스페인(INE)·네덜란드(CBS) HICP 헤드라인·코어와 \
발표일, 국가별 에너지·서비스 요인(규제 요금·세금 변경 포함).
4. **기저효과 시점**: {prev_year}년 같은 달~향후 6개월 에너지·서비스 가격 흐름을 근거로 향후 몇 개월에 \
헤드라인이 기저효과로 오르고 내리는지 — 기관(ECB·EC·IB)의 월별 경로 추정을 수치로 인용.
5. 에너지 전가: 원유·가스 도매가 → 소비자 에너지 가격 전가 시차(연료 즉시, 전기·가스 요금 수개월), \
각국 규제 요금 개편 일정, 에너지 가격 상한·보조금 종료 일정.
6. **임금 방향**: ECB 협상임금 지표(최신 분기), ECB wage tracker의 향후 분기 경로, Indeed 임금 추적기, \
근로자 1인당 보상·단위노동비용(최신 분기), 주요 단체협약(독일 금속·공공부문 등) 타결률 — 가속/둔화 판단 근거.
7. 기대인플레: ECB 소비자기대조사(CES) 1년·3년·5년, SPF 최신 회차, 5y5y 인플레이션 스왑(날짜), \
EC 서베이 기업 판매가격 기대.
8. 생산자물가·수입물가 최신 발표, 식품 원자재 가격.
9. 전망: ECB 스태프·EC·컨센서스·IB의 {year}·{next_year} HICP·코어, 목표(2%) 복귀 시점 논쟁.""",
        "budget": "Q1~Q3 12회, Q4~Q6 12회, Q7~Q9 10회",
    },
    "R03_growth_labour": {
        "title": "유로존 실물·고용 — GDP 지출 구성·PMI vs 산업생산·서베이·DE/FR/IT/ES 각국·노동시장·나우캐스트",
        "groups": ("EA_MACRO", "DE", "FR", "IT", "ES"),
        "geos": ("EA", "DE", "FR", "IT", "ES"),
        "questions": """\
1. 유로존 GDP: 조사 기간에 발표된 분기 GDP 추정(속보·2차·3차) QoQ·YoY와 수정 내역, **지출 항목별 기여도\
(가계소비·정부소비·고정투자·순수출·재고, %p)**. 아일랜드 등 특이 요인의 영향(아일랜드 제외 성장률 공표치 포함). \
**순수출과 재고가 서로 상쇄된 구조인지** 수치로.
2. 서베이: 유로존 PMI(종합·제조·서비스, 속보/확정 구분)와 하위지수(신규주문·고용·가격), EC 경제심리지수(ESI)·\
소비자신뢰, Sentix.
3. **PMI와 산업생산의 괴리**: 제조업 PMI와 유로존·독일 산업생산(최신 월, MoM·YoY)이 어긋날 때의 원인 \
(에너지 집약 업종, 선주문, 아일랜드 제약, 재고, 조사 대상 차이) — 기관·이코노미스트 해설 인용.
4. 독일: 분기 GDP(Destatis, 지출 구성), Ifo·ZEW, 산업생산·제조업 수주·수출, 재정패키지(인프라 특별기금·국방) \
집행 실적, 에너지 집약 산업.
5. 프랑스: GDP(INSEE), INSEE 기업심리, Banque de France 월간 서베이·나우캐스트, 가계 저축률, 정치 불확실성의 \
투자·소비 영향 분석.
6. 이탈리아: GDP(ISTAT), 산업생산, 신뢰지수, PNRR(회복기금) 집행 속도.
7. 스페인: GDP(INE), 고용(사회보장 가입자)·관광·이민 효과, 투자.
8. 노동시장: 유로존 실업률(최신 월)·고용 증가율·구인율·근로시간, 노동 비축(labour hoarding) 논의, 국가별 실업률.
9. 나우캐스트·전망: 다음 분기 GDP 나우캐스트(ECB·각국 중앙은행·IB), {year}·{next_year} 성장 전망(ECB 스태프·EC·IMF·OECD·컨센서스).""",
        "budget": "Q1~Q3 12회, Q4~Q7 16회, Q8~Q9 8회",
    },
    "R04_markets_fx": {
        "title": "유럽 금융시장·환율 — 금리 곡선·국채 스프레드·EUR/USD·EUR/KRW 동인·주식·섹터·자금흐름",
        "groups": ("ECB", "EA_MACRO", "GLOBAL"),
        "geos": ("EA", "DE", "FR", "IT", "ES", "US"),
        "questions": """\
1. 금리: 독일 Bund 2y·10y·30y — {window_from}·{window_to} 수준과 기간 중 고저, 곡선 기울기(2s10s·10s30s), \
기간프리미엄·스왑 스프레드 논의, 발행 공급(각국 분기 발행계획·입찰 결과).
2. 스프레드: OAT·BTP·Bonos·기타(벨기에·오스트리아·포르투갈)–Bund 10y 스프레드의 기간 중 추이와 변동 **원인별 \
분해**(정치·재정·등급·공급). 프랑스와 이탈리아 스프레드 역전 여부 등 구조 변화.
3. **EUR/USD 동인**: 기간 초·말 수준, 고저, 금리차(2y 독·미), 위험선호, 연준 경로, 무역·자금흐름 — 기관 해설 인용.
4. **EUR/KRW 동인**: EUR/KRW·USD/KRW 기간 초·말·고저, 원화 측 요인(한국 수출·외국인 주식 자금·BOK·국민연금 \
환헤지), 유로 측 요인. 한국은행·KCIF 등 국내 기관 해설 포함.
5. 기타 통화: EUR/GBP·EUR/CHF·EUR/JPY·EUR/CNY 수준과 변화 요인.
6. 주식: STOXX 600·Euro Stoxx 50·DAX·CAC 40·FTSE MIB·IBEX 35 기간 수익률·연초 대비, 섹터(은행·자동차·방산·\
에너지·유틸리티·럭셔리·헬스케어) 성과, 12M 선행 PER, 실적 시즌 결과(EPS 증가율·서프라이즈 비율), VSTOXX.
7. 자금흐름: 유럽 주식·채권 펀드 순유출입(EPFR·LSEG Lipper·BofA), 외국인 유로존 국채 순매수(ECB 국제수지).
8. 시장 이벤트: 기간 중 글로벌 채권 매도·위험회피 사건과 유럽 파급(날짜·폭).""",
        "budget": "Q1~Q2 12회, Q3~Q5 12회, Q6~Q8 12회",
    },
    "R05_credit_banks_housing": {
        "title": "신용·은행·주택 — BLS·대출·대출금리·은행 실적·자산건전성·회사채·주택가격",
        "groups": ("EA_MACRO", "ECB"),
        "geos": ("EA", "DE", "FR", "IT", "ES"),
        "questions": """\
1. ECB 은행대출서베이(BLS) 최신 회차(발표일·대상 분기): 기업·가계(주택·소비) 대출 기준 변화·수요 변화 순비율, \
다음 분기 예상, 기준 강화 요인. 다음 BLS 발표 예정일.
2. 대출 증가율: 가계·비금융기업 대출(최신 월, YoY, M3 발표), 통화량 M1·M3, 신규 대출 흐름.
3. 대출 금리(MIR): 신규 주택담보대출·기업대출 금리 최신 월, 정책금리 전가 속도 해설.
4. 은행 실적·수익성: 최근 분기 유럽 주요 은행 실적(순이자이익·ROE·충당금), 금리 인상/동결의 NII 민감도, \
은행세(이탈리아·스페인 등) 논의, 은행 M&A(국경 간 통합 포함) 진행 상황.
5. 자산건전성: NPL 비율(EBA 리스크 대시보드·ECB 감독 통계), 상업용 부동산 익스포저, Stage 2 대출 비중.
6. 회사채: 유로 IG·HY 스프레드(iTraxx Main·Crossover 또는 지수 OAS) 기간 중 추이, 발행량, 디폴트율 전망.
7. 주택: Eurostat 주택가격지수(최신 분기, YoY)와 국가별(DE·FR·IT·ES·NL), 주택거래·건축허가, 주담대 금리 영향.
8. 금융안정: ECB 금융안정보고서·ESRB 경고·거시건전성 조치(경기대응완충자본 등) 최신 사항.""",
        "budget": "Q1~Q3 12회, Q4~Q5 10회, Q6~Q8 12회",
    },
    "R06_politics_fr": {
        "title": "프랑스 정치·재정 — 정부·의회 산술·예산안·불신임·49.3·등급·스프레드·대선 레이스",
        "groups": ("FR",),
        "geos": ("FR",),
        "politics": True,
        "questions": """\
1. 행위자: 대통령·총리·경제재정장관·예산장관, 원내 주요 정파(범여권·공화당·RN·LFI·사회당·녹색·공산) 대표와 \
원내대표 — 실명과 {window} 중 입장.
2. 국민의회 산술: 577석 정파별 의석, 과반 289, 불신임안 가결 요건(재적 과반 찬성), 각 정파가 불신임에 찬성할 \
조건, 상원 구도.
3. 예산 절차: {next_year} 예산안(PLF)·사회보장재정법안(PLFSS) 제출일·국무회의·의회 심의 일정, 헌법상 심의 기한\
(70일·50일), 49.3조 사용 여부와 그에 따른 불신임 표결 일정, 특별법·예산 지연 시 대안 절차.
4. 예산 내용: 적자 목표(%GDP, {year}·{next_year}), 부채비율, 절감·증세 항목과 규모(€bn), 연금·부유세 등 쟁점, \
고등재정위원회(HCFP) 의견.
5. 사건 일지와 기간 중 정부 안정성 사건(개각·사임·불신임·해산 논의).
6. 시장 전달경로: OAT–Bund 10y 스프레드(날짜별, bp)와 OAT–BTP 비교, CDS, 신용등급(S&P·Moody's·Fitch·DBRS)\
현재 등급·전망과 **다음 평가 예정일**, 은행주 반응, ECB/TPI 관련 언급.
7. 여론·대선 레이스: 차기 대선 후보군(RN·범여권·좌파·공화당) 지지율(조사기관·조사일), 정당 지지율 추세.
8. 시나리오: 예산 통과 / 49.3+불신임 / 해산·조기총선 — 트리거 날짜, 확률(출처), 스프레드·등급 함의.""",
        "budget": "Q1~Q3 12회, Q4~Q5 10회, Q6~Q8 14회",
    },
    "R07_politics_de": {
        "title": "독일 정치·재정 — 연정·연방의회/연방참사원 산술·예산·부채제동·특별기금·AfD·주선거",
        "groups": ("DE",),
        "geos": ("DE",),
        "politics": True,
        "questions": """\
1. 행위자: 연방총리·부총리 겸 재무장관·경제장관, 연정 정당 대표·원내대표, AfD·녹색·좌파 지도부 — 실명과 \
{window} 중 입장.
2. 의회 산술: 연방의회(Bundestag) 정당별 의석·과반선·연정 의석, 헌법 개정 2/3 요건과 차단 소수(AfD+좌파), \
연방참사원(Bundesrat) 표 분포(주정부 연정 구성별)와 동의법안 통과 조건.
3. 재정: {next_year} 연방예산안 심의 일정·총지출·순차입, 부채제동(Schuldenbremse) 개혁 논의, 인프라 특별기금·\
국방비 예외 조항 집행 실적(집행률), 중기 재정계획 공백(€bn), 사회보장(연금·건강보험) 재원 논쟁.
4. 사건 일지: 연정 갈등·합의(날짜), 연금·징병·이민·에너지 정책 결정.
5. AfD와 주선거: 최근·예정 주선거 결과/일정(날짜·득표율·의석), 연방 여론조사 정당 지지율(조사기관·조사일), \
AfD 1위 여부, 방화벽(Brandmauer) 논쟁.
6. 산업·에너지 정책: 전기요금 대책·산업전기요금·보조금, 자동차 산업 구조조정.
7. 시장 전달경로: Bund 공급 증가·기간프리미엄, 재정 충격 규모(%GDP)와 성장 기여 추정(Bundesbank·연구소), \
독일 주가·섹터 반응.
8. 시나리오: 연정 안정 / 예산 교착 / 연정 붕괴 — 트리거·확률·시장 함의.""",
        "budget": "Q1~Q3 12회, Q4~Q6 12회, Q7~Q8 10회",
    },
    "R08_politics_it_es_other": {
        "title": "이탈리아·스페인·기타 회원국 정치·재정 — IT·ES·NL·PL 및 기간 중 선거·정부 구성 국가",
        "groups": ("IT", "ES"),
        "geos": ("IT", "ES", "NL", "PL", "BE", "PT", "AT"),
        "politics": True,
        "questions": """\
1. 이탈리아: 총리·재무장관·연정 3당 대표, 양원 의석 산술, {next_year} 예산(DPB 제출일·적자 목표·주요 항목), \
과다적자절차(EDP) 종료 전망, 등급 평가 일정·결과, BTP–Bund 스프레드, 지방선거·국민투표 일정, 여론조사.
2. 스페인: 총리와 소수정부 지지 구조(연정·지지 정당 의석, 과반 176), {next_year} 예산 제출·통과 가능성, \
부패 수사·사법 이슈, 조기총선 가능성, 카탈루냐 정당 입장, 여론조사, Bonos 스프레드·등급.
3. 네덜란드: 최근 총선 결과(의석)·연정 협상 경과·정부 구성 일정, 재정·연금 개혁 함의.
4. 폴란드·중부유럽: 대통령–정부 관계, 예산·국방비, 헝가리·체코·슬로바키아 등 EU 관계 쟁점.
5. 기타: 벨기에·포르투갈·오스트리아·그리스 등 **조사 기간 중 선거·정부 구성·예산 위기가 있었던 모든 회원국** — \
국가마다 행위자·의석·일정·재정 수치·스프레드.
6. 공통: 각국 {next_year} 예산계획(DBP) 집행위 제출 일정(10월 중순)과 EU 재정규칙(순지출 경로) 준수 평가.""",
        "budget": "Q1 12회, Q2 10회, Q3~Q6 14회",
    },
    "R09_eu_institutions_trade": {
        "title": "EU 제도·통상 — MFF·방위(SAFE·NATO)·우크라이나 재원·러시아 자산·미–EU 관세·대중 무역방어",
        "groups": ("EU_POLICY", "GLOBAL"),
        "geos": ("EU", "US", "CN"),
        "politics": True,
        "questions": """\
1. 행위자: 집행위원장·통상담당·경제담당 집행위원, 유럽이사회 의장, 주요 회원국 정상의 입장 — 실명.
2. MFF(다년도 재정체계) 차기 기간 협상: 총액(%GNI·€bn), 신규 자체재원, 회원국 입장, 의회·이사회 일정.
3. 방위: SAFE 대출 배정(국가별 €bn)·집행, NATO 국방비 목표 이행(국가별 %GDP), 유럽 방위산업 조달, 재정규칙 \
국방 예외 조항 활성화 국가.
4. 우크라이나 재원: 러시아 동결자산 활용(배상 대출 등) 설계·법적 쟁점·반대 회원국, 지원 규모·일정, 제재 패키지.
5. 미–EU 통상: 관세 합의 이행 상태(자동차·철강·의약품·반도체 세율), EU 측 입법 조치, 232조 조사, 디지털 규제 \
갈등, 추가 관세 위협 — 날짜·세율·대상 교역액.
6. 대중 무역방어: EV 관세·세이프가드·반덤핑 조사, 희토류·핵심광물 수출통제 영향, 중국산 수입 급증 통계.
7. 경쟁력·규제: 옴니버스 간소화, 에너지·산업 정책, 자본시장동맹(저축·투자 연합) 진전.
8. 일정: {horizon_to}까지 EU 정상회의·이사회·의회 표결·집행위 발표 일정표.""",
        "budget": "Q1~Q4 16회, Q5~Q6 12회, Q7~Q8 6회",
    },
    "R10_external_energy": {
        "title": "대외·에너지 — 중동 전쟁·원유·가스·TTF·저장률·러시아·우크라이나·중국 쇼크·미국 파급",
        "groups": ("ENERGY_EXTERNAL", "GLOBAL"),
        "geos": ("GLOBAL", "US", "CN", "RU", "UA"),
        "questions": """\
1. 중동(이란) 분쟁: 조사 기간 중 전황·호르무즈 해협 통항·협상 경과(날짜), 원유 공급 차질 규모(mb/d), OPEC+ 결정.
2. 원유: Brent·WTI 기간 초·말·고저·월평균, 선물 곡선(백워데이션), 기관 유가 전망(EIA·IEA·IB).
3. **가스**: TTF 기간 초·말·고저, 유럽 가스 저장률(AGSI+, 날짜별 %)과 목표, LNG 도입량·가격, 겨울 수급 전망. \
유가 대비 가스 가격의 상대 흐름과 유럽 경제 영향이 더 큰 이유(전기요금 연동·산업 사용).
4. 러시아·우크라이나: 전황·휴전 협상·에너지 인프라 공격·하이브리드 공격 사건(날짜), 러시아 에너지 수입 단계적 \
금지 일정.
5. 중국 쇼크: 중국의 대EU 수출 물량·가격(최신 월), 산업별 잠식(자동차·기계·화학), 기관의 유로존 GDP 영향 추정(%).
6. 미국 파급: 연준 결정·경로, 미 국채금리·달러, 미국 성장이 유럽 수출에 미치는 경로.
7. 에너지 → 물가·성장 전달 추정: 유가/가스 10% 충격의 유로존 HICP·GDP 영향(ECB·EC 민감도 수치).""",
        "budget": "Q1~Q3 14회, Q4~Q5 10회, Q6~Q7 8회",
    },
    "R11_uk_periphery": {
        "title": "영국·주변부 — BOE·길트·예산·영국 정치·SNB·Riksbank·Norges",
        "groups": ("UK",),
        "geos": ("UK", "CH", "SE", "NO"),
        "politics": True,
        "questions": """\
1. BOE: 조사 기간 중 통화정책위원회 결정(Bank Rate·표결 분포·위원별)·가이던스, QT(국채 매각) 속도 결정, \
통화정책보고서(해당 시). 다음 회의 일정과 시장 프라이싱.
2. 영국 지표: CPI·코어·서비스(최신 월, 컨센서스), 임금·실업률, 월간 GDP·분기 GDP, PMI.
3. 길트: 2y·10y·30y 수준과 고저, 재정 프리미엄 논의, DMO 발행 계획.
4. 재정: 차기 예산(Budget) 일정, 재정 여유(headroom) 추정, 증세·지출 논쟁, OBR 전망 일정, 재무장관 발언.
5. 영국 정치: 총리·노동당 내부 리더십 논쟁, Reform UK·보수당·자민당 지지율(조사기관·조사일), 보궐선거·지방선거 결과, \
정부 안정성.
6. SNB: 정책금리·환율 개입·CHF, 스위스 관세 협상. Riksbank·Norges Bank: 결정·물가.
7. 유로존과의 차이: 물가·금리·재정 프리미엄 비교(수치)와 EUR/GBP 함의.""",
        "budget": "Q1~Q3 14회, Q4~Q5 12회, Q6~Q7 8회",
    },
    "R12_calendar_consensus": {
        "title": "지표 실적·향후 일정·기관 전망·시나리오 재료",
        "groups": ("EA_MACRO", "ECB"),
        "geos": (),
        "questions": """\
1. **최근 4주 실적표**({lookback_from} ~ {as_of} 발표분 전량): 발표일 | 국가 | 지표(참조 기간) | 실제 | 예상 | 이전 | \
수정치 | 출처 URL. 대상: 유로존·독일·프랑스·이탈리아·스페인·영국·스위스의 HICP/CPI(속보·확정·코어), PPI, GDP, \
PMI(속보·확정), Ifo·ZEW·INSEE·ISTAT·ESI·소비자신뢰, 산업생산, 소매판매, 실업률, 무역수지, 경상수지, M3·대출, \
협상임금, 중앙은행 결정. **최소 40행.** 컨센서스 출처(Bloomberg·Reuters·Investing·ForexFactory) 표기.
2. **향후 30일 일정**({horizon_from} ~ {horizon_to}): 발표일·시간(CET/CEST 및 KST) | 국가 | 지표·이벤트(참조 기간) | \
컨센서스 | 이전 | 중요도(高/中/低). 경제지표 외에 **ECB 회의·의사록·위원 연설, 신용등급 평가일, 예산 제출·표결, \
선거, EU 정상회의, 국채 입찰**을 포함.
3. 기관 전망 비교표: ECB 스태프·EC·IMF·OECD·Consensus Economics/Bloomberg 설문의 유로존·DE·FR·IT·ES \
{year}·{next_year} GDP·HICP (발표일 명시).
4. 시나리오 재료: 에너지 재충격·정치 위기(프랑스 등)·관세 확전·중국 수출 충격·채권 매도 — 기관이 제시한 \
시나리오별 GDP·HICP 영향(ppt)과 트리거.
5. 교차 확인 규칙: 1차(Eurostat·ECB·각국 통계청·S&P Global 릴리스 캘린더) vs 2차(Investing·ForexFactory·\
Trading Economics) 불일치는 note에. 시간대는 원문 표기 병기 후 KST 변환.""",
        "budget": "Q1 15회, Q2 12회, Q3~Q5 10회",
    },
}

# 축 → BI 섹션 그룹(맥락 블록 구성용). 테스트·러너가 공유.
AXIS_GROUPS: dict[str, tuple[str, ...]] = {
    k: v["groups"] for k, v in RESEARCH_AXES.items()
}


# ---------------------------------------------------------------------------
# 웹 시계열 (llm_web 등급) — contract §3 형식
# ---------------------------------------------------------------------------

WEB_SERIES_HEADER = """\
유럽 거시경제 **시계열 수집** 과제(Sonnet). 기준 시점 {as_of} (KST). WebSearch·WebFetch만 사용해 아래 시계열을 \
수집하고 **JSON 한 덩어리**로 출력할 것. 결과는 코드가 `llm_web` 등급으로 흡수하고 BI 원문·결정론 수치와 교차 검증한다.

## 효율·정확성 지침
- 월별 개별 검색 금지. 시계열이 한 표에 있는 **종합 출처(S&P Global/HCOB 릴리스 아카이브·Investing.com 과거 발표·\
Trading Economics·중앙은행 자료)를 WebFetch**로 받아 파싱하는 것을 최우선. 검색 예산 25~30회.
- 확인되지 않은 기간은 `null`. 추정·보간 금지. x_labels는 결측 기간도 빠뜨리지 않고 연속 격자로.
- 각 시리즈에 `source`(기관)·`url`·`published`(최신 관측 발표일)·`unit`·`frequency`·`note`를 부착.
- `status` 배열(data와 같은 길이): 관측별 `final|flash|estimate|null`.

## 이미 확인된 사실 (참고, 수치가 겹치면 이 값과 대조해 note에 불일치 기록)
{known}

## 출력 형식 (엄수 — JSON 외 텍스트는 코드펜스 밖에 최소한으로)
```json
{{
  "as_of": "{as_of}",
  "series": {{
    "<series_id>": {{
      "title": "...", "unit": "...", "frequency": "M|D|meeting",
      "x_labels": ["..."], "data": [0.0, null], "status": ["final", null],
      "source": "...", "url": "...", "published": "YYYY-MM-DD", "note": "..."
    }}
  }},
  "unresolved": ["..."]
}}
```
"""

WEB_SERIES: dict[str, dict[str, str]] = {
    "W1_pmi": {
        "title": "HCOB PMI — 유로존·DE·FR·IT·ES 종합·제조·서비스",
        "body": """\
## 수집 대상 (월별, {series_start} ~ {as_of} 시점 최신 발표)
- 지역 5개(유로존 `ea`·독일 `de`·프랑스 `fr`·이탈리아 `it`·스페인 `es`) × 지수 3개(`composite`·`manufacturing`·\
`services`) = 15개 시리즈. id 규칙 `<geo>_pmi_<kind>` (예 `ea_pmi_composite`, `it_pmi_services`).
- 이탈리아·스페인은 속보(flash)가 없으므로 확정치만. 유로존·독일·프랑스는 최신 월이 속보이면 `status`에 `flash`.
- 확정치가 속보를 수정했으면 확정치를 쓰고 note에 `YYYY-MM flash x → final y` 형식으로 기록.
- 제조업은 headline PMI(가중 합성지수)이며 생산지수(output index)와 구분할 것.""",
    },
    "W2_ois": {
        "title": "€STR OIS 내재 ECB 예금금리(DFR) 경로 — 회의별, 두 시점",
        "body": """\
## 수집 대상
- `ois_dfr_asof`: {as_of} 시점(또는 직전 영업일) 기준 ECB 회의별 내재 DFR(%) — x_labels는 **회의일**(YYYY-MM-DD), \
{next_meeting} 회의부터 약 12개월 뒤 회의까지.
- `ois_dfr_prev`: {ois_prev_date} 무렵(±3영업일, 실제 날짜 note) 같은 회의 격자의 내재 DFR.
- `ois_cum_bp_asof`: 현재 DFR 대비 회의별 누적 변화(bp) — 출처가 bp로만 제시하면 이것을 우선 채우고 DFR 환산식을 note에.
- 현재 DFR 값과 기준일을 note에 명시. 출처: Bloomberg WIRP·Reuters 보도·IB 리서치·ECB 위원 발언 보도 중 날짜가 \
명시된 것만. 서로 다른 출처를 한 시리즈에 섞지 말 것(섞었다면 note에 관측별 출처).
- 회의 일정은 ECB 공식 일정(ecb.europa.eu)으로 확인.""",
    },
}


# ---------------------------------------------------------------------------
# 발표 대기(컨센서스 선반영) — W3 컨센서스 수집 · W4 실제치 수집
# ---------------------------------------------------------------------------

RELEASE_JOBS: dict[str, dict[str, str]] = {
    "W3_pending": {
        "title": "발표 대기 지표 컨센서스 — 초안 기준일 이후 보고 전 발표분",
        "dest": "pending_releases.json",
    },
    "W4_actuals": {
        "title": "발표 대기 지표 실제치 — 발표 후 확인",
        "dest": "pending_actuals.json",
    },
}

PENDING_PROMPT = """유럽 거시경제 월간 리포트({month_label}호, 보고일 {report_date}) **발표 대기 지표 컨센서스** 수집(Sonnet). 기준 시점 {as_of} (KST). 리포트 초안을 {as_of} 기준으로 먼저 쓰고, **{pending_from} ~ {pending_to}**(양끝 포함)에 발표되는 지표는 컨센서스를 기준점으로 서술한 뒤 발표 후 해당 부분만 고친다. 그 기준점을 수집하는 과제.

## 대상
- 위 기간에 발표 예정인 유로존·독일·프랑스·이탈리아·스페인·영국 주요 지표 **전부**: HICP/CPI 속보(헤드라인·근원·서비스), PMI(제조·서비스·종합, 속보·확정), 실업률, 소매판매, 산업생산, 심리지표(Ifo·ZEW·INSEE·EC), GDP, 무역, M3·대출, ECB 의사록(account), 중앙은행 결정. ECB 위원 연설·예산안 제출·신용등급 평가 등 비지표 이벤트도 포함(consensus null).
- 항목마다: 발표일·시각(CET와 KST), 참조 기간, 컨센서스 중앙값과 출처(Bloomberg·Reuters 설문, Investing.com, ForexFactory, Trading Economics 중 명시), 예상 범위(있으면), 직전치(수정 전·후), 중요도(high|mid|low).
- **해석 포인트**: 상회 시 의미(`above_means`)·하회 시 의미(`below_means`)를 각각 한 문장. 예: HICP 근원이 컨센서스를 상회하면 10월 회의 추가 인상 가능성 확대, 하회하면 연내 1회 인상 후 동결 경로 강화. 부합 시 의미(`inline_means`)도.
- 발표일은 공식 캘린더(Eurostat 릴리스 캘린더, 각국 통계청, S&P Global, ECB)로 확인. 연도 혼동 금지({prev_year}년 vs {year}년).

## 이미 확인된 사실 (참고)
{known}

## 출력 (JSON 하나, 코드펜스)
```json
{{
  "as_of": "{as_of}",
  "window": {{"from": "{pending_from}", "to": "{pending_to}"}},
  "releases": [
    {{"id": "ea_hicp_flash_headline_<참조월 YYYYMM>", "date": "YYYY-MM-DD", "time_cet": "11:00", "time_kst": "18:00",
      "geo": "EA|DE|FR|IT|ES|UK", "kind": "data|central_bank|speech|politics|other",
      "indicator": "HICP 속보 헤드라인", "period": "YYYY-MM", "unit": "% YoY",
      "consensus": 0.0, "consensus_source": "...", "range_low": null, "range_high": null,
      "prior": 0.0, "prior_revised": null, "importance": "high|mid|low",
      "above_means": "...", "below_means": "...", "inline_means": "...",
      "source_url": "...", "note": ""}}
  ],
  "unresolved": ["..."]
}}
```
"""

ACTUALS_PROMPT = """유럽 거시경제 월간 리포트({month_label}호) **발표 대기 지표의 실제 발표치** 확인(Sonnet). 기준 시점 {as_of} (KST).
아래 목록의 각 id에 대해 실제 발표치를 1차 출처(Eurostat·각국 통계청·S&P Global·ECB)로 확인할 것. 아직 발표 전이면 `actual: null`, `status: "not_released"`. 직전치가 수정됐으면 `prior_revised`. 컨센서스는 목록 값을 그대로 둔다.

## 목록
{pending_list}

## 출력 (JSON 하나, 코드펜스)
```json
{{"as_of": "{as_of}", "releases": [
  {{"id": "...", "actual": 0.0, "status": "released|not_released", "prior_revised": null,
    "published_at": "YYYY-MM-DD HH:MM CET", "source": "...", "url": "...",
    "vs_consensus": "above|below|inline|n/a", "detail": "구성 항목 등 한두 문장(예: 근원 x.x%, 서비스 x.x%)"}}
]}}
```
"""


def build_release_prompt(key: str, ed: Any, known: str, pending: str = "") -> str:
    v = edition_vars(ed)
    pw = getattr(ed, "pending_window", None) or {"from": ed.as_of, "to": ed.as_of}
    v.update(
        known=known.strip() or KNOWN_PLACEHOLDER,
        pending_from=pw["from"],
        pending_to=pw["to"],
        pending_list=pending or "(목록 없음)",
    )
    tmpl = PENDING_PROMPT if key == "W3_pending" else ACTUALS_PROMPT
    return tmpl.format(**v)


# ---------------------------------------------------------------------------
# 보충 리서치(갭) 모드
# ---------------------------------------------------------------------------

GAP_HEADER = """\
유럽 거시경제 월간 리포트({month_label}호, 보고일 {report_date}·{phase_ko}) 보충 리서치(Sonnet). 기준 시점 **{as_of} (KST)**, \
조사 대상 기간 {window}. 집필·감사 과정에서 본문에 필요하지만 근거가 없던 질문 목록(라운드 {round_id}, 묶음 {n}).

## 규약
- 질문마다 **답(수치·날짜·행위자·원문 인용) + 1차 출처 URL + 발표일**을 제시할 것. 라벨 [확정]/[보도]/[추정]/[시장]/[미확인].
- 공개 자료가 있는데 "확인 불가"로 끝내지 말 것. 1차 출처가 없으면 신뢰 가능한 2차 출처로 답하고 라벨로 구분.
- 정말 **미공개**(예: 아직 발표 전, 비공개 회의)이면 `미공개`로 판정하고 ① 공개 예정일 ② 대체 근거(가장 가까운 공개 \
수치·기관 추정) ③ 결론에 미치는 영향을 쓸 것.
- 연도 혼동 금지({prev_year}년 vs {year}년), 상대 날짜 금지. 검색 예산 질문당 4~6회, 총 30회 이내.
- 산출은 표준출력 마크다운. 한국어, 명사형 종결.

## 이미 확인된 사실 (재조사 금지)
{known}

## 질문
{questions}

## 출력 형식 (엄수)
```
## <gap id> — <질문 요지>
- 판정: 답변|부분|미공개
- 답: (수치·날짜·행위자·원문 인용. 라벨)
- 근거: (출처명 · 발표일 · URL)
- 미공개 시: 공개 예정일 · 대체 근거 · 결론 영향

(질문 수만큼 반복)

## 수치 레코드
| metric | value | unit | period | geo | label | source_name | url | published | gap_id |
|---|---|---|---|---|---|---|---|---|---|
```
"""


# ---------------------------------------------------------------------------
# 빌더
# ---------------------------------------------------------------------------


def resolve_axis(key: str) -> str:
    """'R01' 또는 'R01_ecb' → 'R01_ecb'."""
    for k in RESEARCH_AXES:
        if k == key or k.split("_", 1)[0] == key:
            return k
    raise KeyError(f"unknown axis {key}")


def resolve_web(key: str) -> str:
    for k in (*WEB_SERIES, *RELEASE_JOBS):
        if k == key or k.split("_", 1)[0] == key:
            return k
    raise KeyError(f"unknown web series {key}")


def build_axis_prompt(key: str, ed: Any, known: str, bi_context: str) -> str:
    full = resolve_axis(key)
    spec = RESEARCH_AXES[full]
    v = edition_vars(ed)
    v.update(
        known=known.strip() or KNOWN_PLACEHOLDER,
        bi_context=bi_context.strip() or BI_PLACEHOLDER,
        events=events_block(ed, spec.get("geos", ())),
    )
    parts = [RESEARCH_HEADER.format(**v)]
    parts.append(f"\n## 축: {full} — {spec['title']}\n")
    if spec.get("politics"):
        parts.append(POLITICS_REQUIREMENTS.format(**v))
    parts.append(f"\n## 조사 질문\n{spec['questions'].format(**v)}\n")
    parts.append(f"\n## 검색 예산 배분 안내\n{spec['budget']}\n")
    return "".join(parts)


def build_web_series_prompt(key: str, ed: Any, known: str) -> str:
    full = resolve_web(key)
    v = edition_vars(ed)
    v["known"] = known.strip() or KNOWN_PLACEHOLDER
    spec = WEB_SERIES[full]
    return (
        WEB_SERIES_HEADER.format(**v)
        + f"\n## 과제: {full} — {spec['title']}\n"
        + spec["body"].format(**v)
        + "\n"
    )


def build_gap_prompt(
    round_id: str, n: int, items: list[dict], ed: Any, known: str
) -> str:
    v = edition_vars(ed)
    lines = []
    for it in items:
        lines.append(f"### {it.get('id', '?')}\n- 질문: {it.get('question', '')}")
        if it.get("context"):
            lines.append(f"- 맥락: {it['context']}")
    v.update(
        known=known.strip() or KNOWN_PLACEHOLDER,
        round_id=round_id,
        n=str(n),
        questions="\n".join(lines),
    )
    return GAP_HEADER.format(**v)


def axis_catalog() -> str:
    """사람이 읽는 축 목록(JSON)."""
    return json.dumps(
        {
            k: v["title"]
            for k, v in {**RESEARCH_AXES, **WEB_SERIES, **RELEASE_JOBS}.items()
        },
        ensure_ascii=False,
        indent=1,
    )
