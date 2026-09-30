# ruff: noqa: E501
"""월간 유럽 매크로 브리프 v2 — Sonnet 웹리서치·시계열 수집 프롬프트.

모든 프롬프트는 ``claude -p`` 사용자 프롬프트로 전달된다(``<system>`` 태그 금지).
플레이스홀더: ``{month_label}``(예 "2026년 8월"), ``{as_of}``(예 "2026-09-10"),
``{window}``(예 "2026-08-01 ~ 2026-09-10"), ``{known}``(재조사 금지 사실 블록).
"""

from __future__ import annotations

RESEARCH_HEADER = """\
당신은 팀 Noir의 유럽 매크로 웹리서처(Sonnet)입니다. 기준 시점 **{as_of} (KST)**. \
조사 대상 기간은 **{window}** (대상 월 {month_label}, 이후 발표된 확정치·사건 포함).

## 공통 규약 (위반 시 산출물 폐기)
- 모든 사실에 **발표일·수치·기관(1차 출처 우선)·URL**을 붙일 것. 1차 출처: ECB·\
Eurostat·각국 통계청·S&P Global·Ifo·ZEW·EU집행위·재무부. 2차: Reuters·Bloomberg·FT·\
Politico·Handelsblatt·Les Echos.
- 라벨 5종을 문장 끝에 표기: [확정](1차 출처) / [보도] / [추정](리서치사·애널리스트) / \
[시장](가격·프라이싱 스냅샷, 조회 시각 명시) / [미확인].
- **연도 혼동 금지**: 2025년 사건과 2026년 사건을 뒤섞지 말 것. 반복형 사건(ECB 회의·\
HICP flash·PMI)은 발생 연·월을 반드시 표기. "지난달"류 상대 표현 금지.
- 컨센서스가 있는 지표는 `실제(예상, 전월)` 형식으로 기록(예: HICP 3.3%(e3.3%, 전월 2.9%)).
- 미확인은 추정으로 채우지 말 것. 검색 예산 30~40회, WebFetch로 1차 원문 확인 우선.
- 산출은 **표준출력 마크다운**. 파일을 쓰지 말 것. 한국어(고유명사·수치 원문 유지). \
개조식·명사형 종결. 1인칭·메타서술 금지.

## 이미 확인된 사실 (재조사 금지, 그대로 인용 가능)
{known}

## 출력 형식 (엄수)
```
## 핵심 발견
- (불릿 6~10개, 문장 끝 라벨)

## 상세
### Q1. <질문 요지>
- (사실. 발표일·수치·기관·URL)
...

## 수치 레코드
| metric | value | unit | period | geo | consensus | previous | label | source_name | url | published | note |
|---|---|---|---|---|---|---|---|---|---|---|---|

## 시장 스냅샷 (해당 시)
| instrument | value | as_of(UTC 또는 KST 명시) | change_vs | source | url |

## 미확인·공백
- (조사했으나 확인 실패)

## 출처 목록
| # | 제목 | 기관 | URL | 발행일 |
```
"""

RESEARCH_AXES: dict[str, dict[str, str]] = {
    "N01_ecb_september": {
        "title": "ECB 9월 통화정책회의 결정·성명·스태프 전망·기자회견·시장 반응",
        "questions": """\
1. 2026-09-10 ECB 통화정책 결정: 3대 정책금리(DFR·MRO·MLF) 결정치·변경폭·발효일. \
성명서 원문(ecb.europa.eu press release) 핵심 문장 인용(영문 원문 + 번역).
2. 9월 ECB 스태프 거시전망: 실질GDP 2026·2027·2028, HICP 헤드라인·코어 2026·2027·2028 \
— 6월 전망 대비 변경폭. 에너지 가격 가정(유가·가스).
3. 라가르드 기자회견(14:45 CET): 향후 경로 가이던스 문구, 12월 추가 인상 여지, \
데이터 의존·회의별 접근 표현, 성장 리스크 평가, 임금·기대인플레 언급, 표결 만장일치 여부.
4. 시장 반응(9/10 종가·9/11 아시아 오전): EUR/USD, Bund 2y·10y, OAT-Bund·BTP-Bund 스프레드, \
STOXX 600·은행지수, OIS 내재 12월·2027년 경로(회의 전 vs 후).
5. 이코노미스트·IB 반응: Bloomberg 설문 사전 컨센서스(인상 확률·전망 분포), 회의 후 \
주요 IB(GS·JPM·DB·Barclays·Nomura·BNP) 경로 수정 요지.
6. 6월(6/11)·7월(7/23) 회의와의 연속성: 6월 인상 25bp → 7월 동결 → 9월 결정. \
7월 의사록(8월 공개) 요지 재확인.
7. 다음 회의 일정(10월·12월)과 12월 회의 스태프 전망 갱신 여부. TPI·PEPP·APP 재투자 등 \
대차대조표 언급.""",
        "budget": "Q1~Q3 ECB 원문 12회, Q4 시장 10회, Q5~Q7 10회",
    },
    "N02_inflation": {
        "title": "유로존 물가 — 8월 HICP flash·구성·국가별·기대인플레·임금·PPI",
        "questions": """\
1. 8월 HICP flash(2026-09-02 Eurostat): 헤드라인·코어(식품·에너지·주류·담배 제외)·\
서비스·비에너지 산업재·식품·에너지 YoY 및 MoM, 컨센서스 대비. 7월 확정치(8/19 발표) 대비.
2. 8월 국가별 HICP flash: 독일(연방통계청 8/28~31)·프랑스(INSEE)·이탈리아(ISTAT)·스페인(INE) \
헤드라인·코어, 각국 에너지 기여.
3. 에너지 인플레 경로: 이란 전쟁發 유가(Brent 8월 평균·9월 초 수준), 유럽 가스(TTF) 8월 \
추이, 소비자 에너지가격 전가 시차 논의. 2025년 8월과의 기저효과.
4. ECB 협상임금 지표(negotiated wages) 2Q26(8월 말 발표)·Indeed 임금 트래커·ECB 임금 \
트래커 3Q~4Q 전망. 단위노동비용.
5. 기대인플레: ECB 소비자기대조사(CES) 7·8월 1년·3년, SPF 3Q26, 5y5y 인플레 스왑 8월 말.
6. 7월 PPI(9/3)·수입물가, 서비스 물가 끈끈함(패키지 휴가·항공 등 8월 특이요인).
7. 2026년 하반기~2027년 HICP 컨센서스(Bloomberg 설문 8월·9월), 3% 상회 지속 기간 논의.""",
        "budget": "Q1~Q2 12회, Q3~Q4 10회, Q5~Q7 10회",
    },
    "N03_real_economy": {
        "title": "유로존 실물 — 2Q GDP 확정·국가별·8월 PMI·서베이·산업생산·소비·고용",
        "questions": """\
1. 2Q26 GDP: Eurostat 2차 추정(8/14)·3차(9/5) 유로존·EU QoQ/YoY, 국가별(DE·FR·IT·ES·NL·IE) \
확정치와 수정 내역(프랑스 하향 수정 포함). 지출항목별 기여(소비·투자·순수출·재고).
2. 8월 PMI 최종(9/1 제조·9/3 서비스·종합) 유로존·독일·프랑스·이탈리아·스페인, 신규주문·\
고용·투입/산출가격 하위지수. 9월 flash 예정일.
3. 독일: 8월 Ifo(8/25)·ZEW(8/18)·7월 산업생산(9/8)·제조업 수주(9/5)·수출(9/8). 재정패키지·\
인프라 지출 집행 상황.
4. 프랑스: INSEE 기업심리 8월, 소비자 저축의향, 2Q GDP 하향과 3Q 전망(Banque de France 8월 말 \
월간 서베이).
5. 이탈리아·스페인: 8월 신뢰지수, 산업생산, 스페인 고용·관광.
6. 유로존 7월 실업률(9/1)·6월 확정, 고용 성장, 구인율. 7월 소매판매(9/4), 소비자신뢰 8월 flash·확정.
7. 3Q26 GDP 나우캐스트(ECB·Bloomberg·은행), 2026·2027 성장 컨센서스 8~9월 갱신.""",
        "budget": "Q1~Q2 12회, Q3~Q5 12회, Q6~Q7 8회",
    },
    "N04_markets": {
        "title": "유럽 금융시장 — 환율·국채·스프레드·주식·글로벌 채권 매도·은행",
        "questions": """\
1. EUR/USD: 7/31·8/29·9/9 종가, 8월 고저, 월간 변동 요인(ECB 인상 기대·Fed·달러). \
EUR/GBP·EUR/JPY·EUR/CHF 8월 말 수준.
2. 독일 Bund 2y·10y·30y: 7/31·8/29·9/9 수준과 8월 변동폭, 실질금리·기간프리미엄 논의.
3. 스프레드: OAT-Bund 10y, BTP-Bund 10y, Bonos-Bund 8월 추이와 9월 초 수준 — 프랑스 \
정치·예산 리스크 반영, 이탈리아 등급 상향 여부.
4. 8월 글로벌 채권 매도(global bond rout): 배경(재정·공급·인플레·일본 JGB)과 유럽 파급, \
ECB 시각(BI 'What Global Bond Market Rout Means for Policy' 논지와 대조).
5. 주식: STOXX 600 8월 수익률·YTD, 섹터(은행·자동차 SXAP·에너지·방산·유틸리티), DAX·CAC·\
FTSE MIB·IBEX 8월, 밸류에이션(12M fwd PER), 2Q 실적 시즌 결과(EPS 성장·서프라이즈 비율).
6. 은행: 유로존 은행지수 8월, NII 민감도, ECB 인상 수혜 논의, 대출 성장(7월 M3·대출 통계 8/27).
7. 자금흐름: 유럽 주식·채권 펀드 8월 순유입(EPFR·LSEG), 외국인 유로존 채권 매입.
8. 시장 내재 ECB 경로(ESTR OIS) 8/1·8/29·9/9 시점별: 9월·12월·2027년 6월 내재 DFR.""",
        "budget": "Q1~Q3 12회, Q4~Q6 12회, Q7~Q8 8회",
    },
    "N05_politics_fiscal": {
        "title": "유럽 정치·재정 — 프랑스·독일·이탈리아·스페인·EU 예산·방위비·정치 캘린더",
        "questions": """\
1. 프랑스: 2027 예산안 준비·2026 예산 집행, 정부 안정성(불신임·개각), 신용등급 이벤트(Fitch·\
Moody's·S&P 9~10월 일정), 재정적자·부채 목표, OAT 스프레드와의 연계. 8~9월 주요 사건 일지.
2. 독일: 8월 주(州)선거 결과(AfD 승리·연정 파장, BI 'AfD Win Poses New Test'), 연방 연정 \
안정성, 2026 예산·재정패키지 집행, 부채제동 개혁, 산업정책(전기요금·에너지).
3. 이탈리아: 2027 예산 방향(DPFP 9월), 적자 3% 하회·EDP 탈출 전망, 등급 상향, 멜로니 정부 \
지지율.
4. 스페인·네덜란드·기타: 예산 통과 가능성, 선거 일정, 정치 리스크.
5. EU 차원: 2028~2034 MFF 협상, SAFE 방위대출·방위비 지출, 우크라이나 지원·재건, 러시아 \
동결자산, 디지털·경쁩력(Draghi 후속), 8~9월 EU 정상회의·EU 집행위 연설(9월 State of the Union).
6. 정치 캘린더 2026-09~2026-12: 각국 선거·예산 표결·등급 평가·EU 정상회의 일정표(날짜 확정분만).
7. BI 'Higher Political Risk Clouds Policy Outlook'·'Election Blitz' 논지와 대조할 1차 사실.""",
        "budget": "Q1~Q2 14회, Q3~Q5 12회, Q6~Q7 8회",
    },
    "N06_external_energy": {
        "title": "대외·에너지 — 미·EU 관세, 중국 무역, 러시아·우크라이나, 이란 전쟁·유가·가스",
        "questions": """\
1. 미·EU 무역: 자동차 25% 관세(5/1 발표, 협상 기한 7/4) 이후 8~9월 상태, 철강·알루미늄·\
의약품·디지털세·232조 조사, EU 대응(보복 보류·협상), 7~8월 EU 대미 수출 통계.
2. 중국: EU-중국 무역(EV 관세·희토류·과잉공급 'China Shock 2.0', BI 0.7% GDP 논지), 10월 \
무역협상 전망, 7월 EU 대중 수입 급증 통계, 러시아 요인.
3. 러시아·우크라이나: 8~9월 전황·휴전 협상·에너지 인프라 공격, EU 제재 패키지, 하이브리드 \
공격(BI 'Hybrid Ops') 사건 목록(날짜).
4. 이란 전쟁(6개월째): 호르무즈 상황·협상, 8~9월 Brent·WTI 추이(월평균·고저), 유럽 가스 TTF·\
저장률(9월 초 %), 유럽 정제마진·연료 가격.
5. 에너지 정책: EU 가스 저장 목표 완화, 러시아 LNG 단계적 금지 일정, 전기요금 대책(독일 등).
6. 기후·물류: 라인강 저수위(BI 'Low River Levels') 산업 영향, 8월 이상기후.
7. 이민·국경: 8월 이민 급증(BI 'Migrant Surge') 사실관계·정치 파급.""",
        "budget": "Q1~Q2 12회, Q3~Q4 12회, Q5~Q7 8회",
    },
    "N07_uk_periphery": {
        "title": "영국·스위스·북유럽 주변부 — BOE·길트·SNB·Riksbank·Norges",
        "questions": """\
1. BOE 8월(8/6)·9월(9/17 예정) 회의: 기준금리·표결·가이던스, 7월 CPI(8/19)·8월 CPI(9/16 예정) \
컨센서스, 7월 고용·임금(8/12·9/15), 2Q GDP(8/14)·7월 월간 GDP(9/11 예정).
2. 길트 매도: 30y 길트 8월 고점, 재정(11월 예산·Healey 재무장관 대응), OBR 논쟁(BI 'OBR Wrong?').
3. 영국 PMI 8월·DMP 서베이, BI 'Two Charts Could Decide BOE' 논지 대조.
4. 스위스: SNB 9월 회의 전망, CHF, 관세(미·스위스 39%) 후속.
5. 스웨덴·노르웨이·덴마크: 8~9월 정책금리·CPI.
6. 유럽 장표 맥락에서 영국이 유로존과 다른 점(인플레 3% 부근·재정 프리미엄) 1~2문단용 사실.""",
        "budget": "Q1~Q2 14회, Q3 6회, Q4~Q6 10회",
    },
    "N08_consensus_outlook": {
        "title": "컨센서스·전망 — ECB 스태프 vs 설문 vs BI vs IB, 시나리오 재료",
        "questions": """\
1. Bloomberg 이코노미스트 월간 설문(8월·9월): 유로존 2026·2027 GDP·HICP·DFR 경로 중앙값·분포.
2. Consensus Economics/FocusEconomics 8~9월 유로존·독일·프랑스·이탈리아·스페인 전망 갱신.
3. EU집행위 여름 전망(있으면)·IMF 7월 WEO 업데이트·OECD 9월 중간전망(9/9~9/23 예정 여부) 유로존 수치.
4. 주요 IB 유로존 전망 8~9월 갱신(GS·JPM·MS·DB·UBS·Barclays·BNP·ING·Nordea): 성장·물가·ECB 최종금리.
5. 리스크 시나리오 재료: 에너지 재충격(유가 $110+), 프랑스 정치 위기, 미·EU 관세 확전, \
중국 수출 충격, 글로벌 채권 매도 — 각 시나리오에 대한 기관 추정 영향(GDP·HICP ppt).
6. 유로존 9~12월 주요 일정: HICP flash·PMI·GDP·ECB 회의·EU 정상회의·등급 평가·선거 날짜 확정분.
7. Bloomberg Intelligence 유로존 팀 8월 전망 논지(ECB 9월 인상 후 12월 초점, 임금 둔화, 3Q 견조)를 \
공개 자료로 교차 확인.""",
        "budget": "Q1~Q2 12회, Q3~Q4 12회, Q5~Q7 10회",
    },
    "N09_calendar_indicators": {
        "title": "지표 실적 스냅샷·향후 1주 발표 일정 (부록용)",
        "questions": """\
1. **최근 4주 실적표**(기준 시점 직전 28일간 발표된 유로존·독일·프랑스·이탈리아·스페인·영국·스위스 주요 지표 전량): 발표일 | 국가 | 지표(참조 기간) | 실제 | 예상(컨센서스) | 이전 | 수정치 | 출처 URL. 대상: HICP/CPI(flash·final·코어), PPI, GDP(잠정·확정), PMI(flash·final, 제조·서비스·종합), Ifo·ZEW·INSEE·ISTAT 심리, 산업생산, 소매판매, 실업률·고용, 무역수지, 경상수지, 소비자신뢰(EC), M3·대출, ECB 협상임금, 영국 CPI·GDP·고용·소매, 중앙은행 결정. 최소 40행. 컨센서스는 Bloomberg/Reuters/Investing/ForexFactory 중 출처 표기.
2. **향후 7일 발표 예정표**(기준 시점 익일부터 7일): 발표일·시간(CET 및 KST) | 국가 | 지표(참조 기간) | 컨센서스 | 이전 | 중요도(高/中/低) | 출처. ECB 위원 연설·EU 회의·국채 입찰·신용등급 평가일도 포함.
3. **향후 8~30일 주요 일정**(월간 보고 이후 관전용): ECB 회의·HICP flash·PMI flash·GDP·EU 정상회의·주요국 예산 제출·등급 평가·선거.
4. 각 표는 1차 출처(Eurostat 릴리스 캘린더, ECB 캘린더, 각국 통계청 캘린더, S&P Global PMI 캘린더)와 2차(Investing.com·ForexFactory·Trading Economics 캘린더)를 교차 확인하고 불일치는 note에 기록.
5. 시간대 변환 규칙: CET(UTC+2 서머타임 기준, 9~10월은 CEST) → KST(UTC+9). 변환 오류 방지 위해 원문 시간대를 함께 표기.""",
        "budget": "Q1 15회, Q2 10회, Q3~Q5 8회",
    },
}

# ---------------------------------------------------------------------------
# 시계열 수집 에이전트 (차트용 JSON) — weekly_brief 계승·확장
# ---------------------------------------------------------------------------

SERIES_HEADER = """\
당신은 유럽 거시경제 **시계열 데이터 수집** 전문가(Sonnet)입니다. 기준 시점 {as_of} (KST). \
WebSearch·WebFetch만 사용해 아래 시계열을 수집하고 **JSON 한 덩어리**로 출력하십시오.

## 효율 지침
- 월별 개별 검색 금지. 시계열 전체가 한 표에 있는 **종합 출처(Eurostat 데이터브라우저·ECB Data \
Portal·Trading Economics·Investing.com·S&P Global 릴리스 아카이브)를 1~2회 WebFetch**로 받아 \
파싱하는 것을 최우선. 검색 예산 25회 이내.
- 값이 확인되지 않는 월은 `null`. 값을 추정·보간하지 말 것. 최신 월은 flash/final 구분을 note에.
- 각 시리즈에 `source`(기관·URL)·`published`(최신 관측 발표일)·`unit`·`frequency`를 부착.

## 출력 형식 (엄수 — JSON 외 텍스트는 코드펜스 밖에 최소한으로)
```json
{{
  "as_of": "{as_of}",
  "series": {{
    "<series_id>": {{
      "title": "...", "unit": "%", "frequency": "M|Q|D",
      "x_labels": ["2024-01", ...], "data": [2.8, ...],
      "source": "Eurostat", "url": "...", "published": "YYYY-MM-DD", "note": "..."
    }}
  }},
  "unresolved": ["..."]
}}
```
"""

SERIES_AGENTS: dict[str, str] = {
    "S1_hicp": """\
## 수집 대상 (월별, 2024-01 ~ 최신 flash)
- `ea_hicp_headline_yoy`, `ea_hicp_core_yoy`(식품·에너지·주류·담배 제외), `ea_hicp_services_yoy`, \
`ea_hicp_energy_yoy`, `ea_hicp_food_yoy`, `ea_hicp_neig_yoy`(비에너지 산업재)
- 국가별 헤드라인 HICP YoY 2025-01~최신: `de_hicp_yoy`, `fr_hicp_yoy`, `it_hicp_yoy`, `es_hicp_yoy`
- `ea_negotiated_wages_yoy`(ECB 협상임금, 분기 2022Q1~2026Q2)
- `ea_ppi_yoy`(2024-01~최신)""",
    "S2_activity": """\
## 수집 대상
- PMI 월별 2024-01~2026-08(최종): `ea_pmi_composite`, `ea_pmi_manufacturing`, `ea_pmi_services`, \
`de_pmi_composite`, `fr_pmi_composite`, `it_pmi_composite`, `es_pmi_composite`
- GDP QoQ 분기 2023Q1~2026Q2(최신 추정): `ea_gdp_qoq`, `ea_gdp_yoy`, `de_gdp_qoq`, `fr_gdp_qoq`, \
`it_gdp_qoq`, `es_gdp_qoq`
- `ea_unemployment_rate` 월별 2024-01~2026-07, `ea_industrial_production_yoy` 2024-01~2026-07, \
`ea_retail_sales_yoy` 2024-01~2026-07, `ea_consumer_confidence` 2024-01~2026-08, \
`de_ifo_business_climate` 2024-01~2026-08, `de_zew_expectations` 2024-01~2026-08""",
    "S3_rates_markets": """\
## 수집 대상
- ECB 정책금리 변경 이력 2022-07~2026-09(결정일·DFR·MRO·MLF): `ecb_dfr`, `ecb_mro`, `ecb_mlf` \
(x_labels=결정 발효일)
- 일별 또는 주별(금요일) 2026-01-02~{as_of}: `eurusd`, `de_bund_10y`, `de_bund_2y`, `fr_oat_10y`, \
`it_btp_10y`, `es_bonos_10y`, `oat_bund_spread_bp`, `btp_bund_spread_bp`, `stoxx600`, `sx7e_banks`, \
`sxap_autos`, `dax`, `cac40`, `brent_usd`, `ttf_gas_eur_mwh`
- 월말 기준 2024-01~2026-08: `eurusd_monthly`, `de_bund_10y_monthly`, `stoxx600_monthly`
- OIS 내재 DFR(가능하면) 2026-09-09 기준 회의별: `estr_ois_implied_dfr` (x_labels=회의월)""",
}

KNOWN_FACTS_FALLBACK = """\
- ECB 2026-06-11 3대 정책금리 25bp 인상(DFR 2.25%·MRO 2.40%·MLF 2.65%, 6/17 발효) [확정]
- ECB 2026-07-23 동결(DFR 2.25% 유지), 라가르드 "긴축 종료로 해석 금물", 회의별 접근 [확정]
- Eurostat 2Q26 GDP 속보(7/30) 유로존 QoQ +0.4%·YoY +1.0%, EU +0.5%·+1.2%; 6월 실업률 6.3% [확정]
- 유로존 6월 HICP 2.8%(5월 3.2%); 7월 HICP 확정 2.9%, 코어 2.5% [확정]
- 미국 對EU 자동차 관세 25% 5/1 발표(15%→25%), 협상 기한 7/4 [보도]
- 이란 전쟁 6개월째(2026-03 개전), Brent 9/1 $96.02(FRED) [확정]
- 2026-08 주간 덱 마지막 유럽 장표는 8/10(ECB 7/23 동결·DFR 2.25%) — 이후 4주 유럽 장표 부재
"""
