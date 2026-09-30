# 유럽 매크로 월간 리포트 v3 — 운영 매뉴얼

- 버전 **v3.0.0** (2026-09-30, 첫 회차 2026-09호). v2 매뉴얼은 `MANUAL_v2.md`에 보존
- 코드 `src/indepth_analysis/skills/euro_macro/monthly_brief/` · 설계 `V3_PLAN.md` · 모듈 계약 `V3_CONTRACTS.md` · 변경 `CHANGELOG.md`
- 회차 루트 `reports/euro_macro/monthly_brief/<YYYY-MM>/` (이하 `ROOT`)

## 1. 산출물

한 달치 유럽 매크로를 **3회 보고**로 낸다. 매 보고의 리포트·해설본은 앞 보고를 읽지 않아도 되는 독립 완결본이다.

| 단계 | H1 태그 | 예(2026-09호) | 성격 |
|---|---|---|---|
| preview | `[Preview]` | 10/5 보고, 기준 10/2 | 전량 집필 |
| interim | `[Interim]` | 10/12 보고, 기준 10/9 | 확정치·신규 사건 반영(증분 모드 — v3.1 예정) |
| final | `[Final]` | 10/19 보고, 기준 10/16 | 전 장 재정리 + 10장 '보고 간 판단 변화' |

| 파일 | 내용 |
|---|---|
| `{보고일}_europe_macro_{phase}_report.md` | 풀 리포트(5~7만 자, KCIF식 개조식, `STYLE_BRIEF.md`) |
| `{보고일}_europe_macro_{phase}_explainer.md` | 해설본(4~5만 자, 리포트 장과 1:1 교재 + 용어사전) |
| `{보고일}_europe_macro_{phase}_index.md` | 허브(Briefing 진입점, 절대경로 링크) |
| `data/chart_pack.json` + `data/charts/<id>.csv` | PowerPoint 차트 입력(30종+, 코드 생성, 스키마는 `chart_pack.py` docstring) |
| `data/table_pack.json` + `data/tables.md` | 표 입력(9종+) |
| `data/facts.md` | 지표별 최신값·직전값·변화(코드 산출) |
| `session.json` · `documents/doc_cards.md` · `sections/<GROUP>.md` | BI 컬렉션 계약(SSR 동형, Briefing 연동용) |
| `_editorial/{phase}_editorial.md` | 방법·출처·남은 공백(독자 본문과 분리) |

장표 텍스트는 만들지 않는다(사용자 결정 2026-09-30 — 장표는 Claude for PowerPoint 작업용 PPT에서 제작).

## 2. 사전 준비

1. Mendeley 컬렉션 `EUROPE YYYYMM`에 BI PDF 업로드, 토큰 `~/.mendeley_token.json` 유효(만료 시 earnings `mendeley-login`)
2. `which claude` · 로그인 상태(Sonnet 리서치·카드는 `claude -p` 서브프로세스 또는 `report_cli` 폴백)
3. 네트워크: Eurostat API·ECB Data Portal·Bundesbank·FRED·yfinance
4. ECB 회의 일정 확인(`edition.json`의 `ecb.last_meeting`·`next_meeting`)

## 3. 표준 절차 (단계마다)

```bash
R=reports/euro_macro/monthly_brief/2026-09
M=indepth_analysis.skills.euro_macro.monthly_brief

# 0) 회차 설정 (단계 전환 시 phase·as-of·report-date만 바꿔 재실행 — events 보존)
uv run python -m $M.edition init --month 2026-09 --phase preview \
  --as-of 2026-10-02 --report-date 2026-10-05 --ecb-last 2026-09-10 --ecb-next 2026-10-29

# 1) 수집·카드·데이터 (멱등)
uv run indepth report euro-macro-monthly-brief --month 2026-09 --stage fetch intake cards data
#   fetch  : Mendeley EUROPE·WEEKLY 다운로드·텍스트화·주간덱 유럽 인덱스
#   intake : 메타 파싱(발행시각·계열·국가)·sha16 중복(월 간 포함)·session.json·sections 스캐폴드
#   cards  : 카드 없는 문서만 Sonnet 카드(key_numbers 원문 대조 검증) → scaffold 재실행
#   data   : series_store(91 시리즈) → chart_pack·table_pack·facts → validate_pack

# 2) 웹 리서치 12축 + 웹 시계열(PMI·OIS) — Sonnet, 병렬 8, 축당 최대 30분
uv run indepth report euro-macro-monthly-brief --month 2026-09 --stage research
#   개별: uv run python -m $M.research --root $R --axes R06 R07 --web W1  [--dry-run]
#   완료 확인: $R/_work/logs/*.err 의 exit=0, research/R01~R12.md, data/web_series_W*.json

# 3) 웹 시계열 반영(PMI·OIS 차트 생성) + Workflow 인자
uv run indepth report euro-macro-monthly-brief --month 2026-09 --stage data workflow-args
```

### 3-1. Opus 단계 (Claude Code Workflow)

Claude Code 세션에서:
```
Workflow(scriptPath="<repo>/src/indepth_analysis/skills/euro_macro/monthly_brief/workflow/noir_v3.js",
         args=<$R/_work/workflow_args_<phase>.json 의 내용(JSON 객체)>)
```
- Prepare: BI 그룹 섹션 서술(10그룹 병렬) ∥ Quant `data/NUMBERS.md`
- Design: Advisor `02_advisor_{phase}.md` (effort high)
- Write: 장별 리포트(ch01~ch09, final은 ch10 포함) → 같은 장 해설본 (pipeline, ch02·ch06·ch09 high)
- Assemble: 리포트 Polish(요약·부록, high) → 해설본 Polish(용어사전)
- Audit: 리포트 fact·logic·style·coverage + 해설본 fact·style·coverage + 독자질문(8병렬) → 라운드 1 공백 보충 리서치(Sonnet `--gaps`) → fixer. 최대 2라운드
- Harmonize: 리포트↔해설본 정합 → 결정론 게이트 수정 루프
- Editorial: `_editorial/{phase}_editorial.md`
- 중단 시 `Workflow(scriptPath, resumeFromRunId)`. 초안에서 감사만 다시: args에 `"startRev": {"report": "preview_report_r2", "explainer": "preview_explainer_r2", "round": 2}`

### 3-2. 마감

```bash
# 게이트 단독 확인
uv run python -m $M.finalize gate --root $R --file drafts/preview_report_r4.md --kind report
# 확정: 게이트 → 최종 파일 복사·데이터 스냅샷(*_{phase}.json, NUMBERS_{phase}.md) → 허브 → session.json 단계 기록
uv run python -m $M.finalize promote --root $R --report preview_report_r4 --explainer preview_explainer_r4 --register
# Notion (사용자 승인 시)
uv run indepth publish $R/2026-10-05_europe_macro_preview_report.md
uv run indepth publish $R/2026-10-05_europe_macro_preview_explainer.md \
  --attach $R/data/chart_pack.json $R/data/table_pack.json
```
게이트 FAIL(=차단): H1 단계 태그, 파이프라인 용어·조사 라벨·거부 문장, 문체 금지어, 상대 날짜, 없는 차트·표 참조, `lint-temporal` HIGH. WARN(자문): `A가 아니라 B` 과다, 분량 이탈, `lint-numeric` HIGH. 참고문헌 절·`_editorial/`은 검사 제외.

## 4. 품질 원칙 (역할 지시서 `roles/_common.md`·`STYLE_BRIEF.md` 정본)

- **수치는 코드가, 해석은 모델이**: 시계열·표·변화율은 `chart_pack`·`table_pack`·`facts`(코드). 모델은 인용·해석만. 손 전사 금지.
- **입력 우선순위**: 코드 산출 > 1차 출처 리서치(R*·G*) > BI 카드·섹션 > 주간 덱. BI 추정은 기관·날짜를 붙여 실측과 구분.
- **거부 문장 금지**: 근거가 없으면 gaps 파일에 질문 → 보충 리서치. 진짜 미공개만 공개 예정일·결론 영향과 함께 서술.
- **독자 본문과 작업 기록 분리**: 방법·검증·공백은 `_editorial/`.
- **정치 장(ch06)**: 국가별 행위자 실명·의석 산술·일정·정책 내용·시장 전달경로·시나리오(`coverage.yaml`).
- **해설본**: 배경 → 작동 원리 → 이번 달 수치 풀이 예제 → 전년~올해 경과 → 독자 질문 답. 리포트 중복 20% 이하.

## 5. 데이터 계층

| 등급 | 소스 | 예 |
|---|---|---|
| api | Eurostat JSON-stat, ECB Data Portal, Bundesbank, FRED | HICP(`prc_hicp_minr`·속보 `prc_hicp_fpd`·기여도 `prc_hicp_ctr`), GDP, 실업, ESI, 산업생산, 소매, 재정, 정책금리, €STR, 대출, EUR/USD·KRW |
| market | yfinance | 주가지수·섹터 ETF 프록시·Brent 선물·TTF |
| local_db | optionsdeck·캘린더 DB | 교차검증 |
| llm_web | Sonnet W1·W2 | PMI(국가·부문), OIS 내재 경로 — 검증기가 WARN·교차대조 |

- 원응답 캐시 `ROOT/_work/cache/` — `datastore.store build --offline`으로 재빌드
- 알려진 한계: OAT·BTP·Bonos 일별 10년물 무료 결정론 소스 없음(월간 IRS만), STOXX 섹터지수는 ETF 프록시, Eurostat 지역코드(EA·EA20·EA21)는 데이터셋별 자동 선택

## 6. 파일 지도

```
ROOT/
  edition.json  session.json  02_advisor_{phase}.md
  documents/doc_cards.md   sections/<GROUP>.md (BI 그룹 10종)
  research/  R01~R12.md  W1_pmi.md W2_ois.md  G_r1_*.md (보충)
  data/      series_store.json chart_pack.json charts/*.csv table_pack.json tables.md
             facts.{json,md} validation.json web_series_W*.json NUMBERS.md
             *_{phase}.json NUMBERS_{phase}.md  ← 단계 마감 스냅샷
  drafts/    {phase}_report_{ch}_r1.md → {phase}_report_rN.md → _rH(정합) → {phase}_report_final.md
  audit/     <draft>_audit_{fact,logic,style,coverage}.md  {phase}_reader_rN_audit_reader.md  *_fix_log.md
  _work/     logs/ cache/ gaps/ gaps_r1.json workflow_args_{phase}.json gates_{phase}.{json,md}
  _editorial/{phase}_editorial.md
  {보고일}_europe_macro_{phase}_{report,explainer,index}.md
references/mendeley_europe/<YYYYMM>/*.{pdf,md}   references/mendeley_europe/cards/<sha16>.json
references/references.db  europe_docs · europe_doc_files · weekly_europe_sections
```

## 7. Briefing 연동 (후속)

`session.json`은 earnings SSR 계약(`orchestrator/contracts/earnings-analysis-tab.md` §3.5·§6)과 동형: `session_type: "europe_monthly"`, `collection`, `period`, `groups_covered[]→sections/<GROUP>.md`, `documents[]{sha16,series,geo,groups,date,title,path,card,dup_of,prior_collection}`, `uncarded[]`, `phases{phase:{report,explainer,index,report_date}}`, `data{chart_pack,table_pack}`. 앱 측 구현은 파이프라인 안정화 후.

## 8. 장애 대응

| 증상 | 대응 |
|---|---|
| 카드 JSON 검증 실패 | 자동 1회 재시도, 남으면 `cards run` 재실행(누락분만) |
| 데이터 소스 실패 | 캐시 폴백(`series_store.json` `cache_fallbacks`), `errors` 확인 |
| 리서치 축 실패 | `$R/_work/logs/<축>.err` 확인 후 해당 축만 재실행(영수증으로 완료분 skip) |
| Workflow 중단 | `resumeFromRunId`, 또는 `startRev`로 감사부터 |
| 게이트 FAIL 잔존 | `finalize gate`로 위치 확인 후 수정, 오탐이면 `promote --force` + `_editorial/`에 사유 |
| Mendeley 폴더 None | `find_folder_by_name` 페이지네이션 — `sources._folder_id` 폴백 내장 |
