# v3 모듈·파일 계약 (개발 기준)

패키지 `src/indepth_analysis/skills/euro_macro/monthly_brief/` (이하 `mb/`). 모든 경로는 저장소 루트 기준 상대경로.
회차 루트 `ROOT = reports/euro_macro/monthly_brief/<YYYY-MM>/`. 단계 `phase ∈ {preview, interim, final}`.

## 0. 소유권
| 모듈 | 담당 |
|---|---|
| `mb/edition.py`, `mb/__init__.py`, `cli.py`, `mb/finalize.py`, `mb/hub.py`, `mb/workflow/` | 통합(메인) |
| `mb/intake.py`, `mb/cards.py`, `mb/contract.py` | WP1 |
| `mb/datastore/`(`eurostat.py`,`ecb.py`,`market.py`,`web_series.py`,`registry.py`,`store.py`), `mb/chart_pack.py`, `mb/table_pack.py`, `mb/validate_pack.py`, `mb/facts.py` | WP2 |
| `mb/prompts.py`(v3 재작성, v2 상수는 `prompts_v2.py`로 보존), `mb/research.py`(v3 축 대응), `mb/roles/*.md`, `mb/STYLE_BRIEF.md`, `mb/coverage.yaml` | WP3·WP4 |
다른 담당 파일은 수정 금지. 커밋 금지(통합 담당이 일괄).

## 1. edition.json (`ROOT/edition.json`, `mb/edition.py`)
```json
{"version":"3.0.0","month":"2026-09","collection":"EUROPE 202609","phase":"preview",
 "as_of":"2026-10-02","report_date":"2026-10-05",
 "window":{"from":"2026-09-01","to":"2026-10-02"},
 "root":"reports/euro_macro/monthly_brief/2026-09",
 "prior_month_root":"reports/euro_macro/monthly_brief/2026-08",
 "ecb":{"last_meeting":"2026-09-10","next_meeting":"2026-10-29"},
 "events":[{"date":"2026-10-01","geo":"EA","kind":"data","title":"9월 HICP 속보"}],
 "phase_bases":{"interim":"preview","final":"interim"}}
```
`from indepth_analysis.skills.euro_macro.monthly_brief.edition import Edition, load_edition`
- `Edition` dataclass 필드 = 위 키. `Edition.month_label` → "2026년 9월", `Edition.path(*parts)` → `Path(root, *parts)`.

## 2. WP1 Intake 산출
- `references/mendeley_europe/<YYYYMM>/*.{pdf,md}` (기존 `sources.fetch_folder`)
- `references/references.db` 표 `europe_docs`(PK `sha16`): `sha16, collection, yyyymm, title, series(PREVIEW|REACT|INSIGHT|WEEK_AHEAD|FAULT_LINES|ECO_WRAP|OUTLOOK|PRIMER|OTHER), geo(EA|DE|FR|IT|ES|UK|EU|ECB|GLOBAL|US|CN|OTHER), groups_json, published_at(ISO), author, pages, chars, pdf_path, md_path, dup_of(sha16|null), fragment(0/1), first_seen_collection`
- 카드 `references/mendeley_europe/cards/<sha16>.json` (월 간 재사용):
```json
{"sha16":"…","title_ko":"…","published_at":"2026-09-17T08:10","series":"REACT","geo":"EA",
 "groups":["EA_INFLATION","ECB"],"summary_ko":["불릿 3~5개, 각 1~2문장"],
 "key_numbers":[{"metric":"HICP headline","geo":"EA","period":"2026-08","value":3.2,"unit":"% YoY","kind":"actual|forecast|consensus|estimate","note":""}],
 "claims":[{"claim_ko":"…","stance":"hawkish|dovish|upside|downside|neutral","horizon":"…","confidence":"high|mid|low"}],
 "forecasts":[{"variable":"DFR","value":2.75,"by":"2026-12","source_view":"BI"}],
 "politics":[{"country":"FR","actors":["…"],"event":"…","date":"…"}],
 "importance":1-5,"card_model":"sonnet","card_version":"3.0"}
```
- 그룹 10종 `ECB, EA_MACRO, DE, FR, IT, ES, UK, EU_POLICY, ENERGY_EXTERNAL, GLOBAL` (문서는 복수 그룹 가능, 1차 그룹=첫 원소).
- `ROOT/session.json` (SSR 계약 동형):
```json
{"session_type":"europe_monthly","ticker":"EUROPE","session_name":"2026-09 EUROPE MONTHLY",
 "collection":"EUROPE 202609","period":{"from":"2026-09-01","to":"2026-10-02"},
 "phase":"preview","phases":{"preview":{"report":"…md","explainer":"…md","index":"…md","report_date":"2026-10-05"}},
 "groups_covered":[{"group":"FR","n_docs":9,"section":"sections/FR.md","latest_doc":"2026-09-28"}],
 "documents":[{"sha16":"…","series":"INSIGHT","geo":"FR","groups":["FR"],"date":"2026-09-24","title":"…","path":"references/mendeley_europe/202609/….pdf","card":true,"dup_of":null,"fragment":false}],
 "uncarded":[],"data":{"chart_pack":"data/chart_pack.json","table_pack":"data/table_pack.json"},
 "generated_at":"…","pipeline_version":"3.0.0"}
```
`phases`는 통합 담당이 finalize에서 채운다(WP1은 `{}`로 둔다).
- `ROOT/documents/doc_cards.md` (그룹별 카드 목록, 발행일순), `ROOT/sections/<GROUP>.md` (결정론 스캐폴드: 문서 목록·카드 요지·핵심 수치 표, 끝에 `<!-- NARRATIVE -->` 자리표시자 — Opus 단계가 대체).
- CLI 진입점: `python -m …monthly_brief.intake scaffold --month 2026-09 [--root] [--as-of]`, `python -m …monthly_brief.cards run --month 2026-09 [--limit N] [--concurrency 6]` (uncarded만), 재실행 멱등.

## 3. WP2 Data 산출
- `ROOT/data/series_store.json`:
```json
{"as_of":"2026-10-02","generated_at":"…","series":{"ea_hicp_headline":{"title_ko":"유로존 HICP 헤드라인","unit":"% YoY","freq":"M","geo":"EA","concept":"hicp_headline_yoy",
 "tier":"api|local_db|market|llm_web","source":"Eurostat","dataset":"prc_hicp_minr","query":{…},"url":"…","fetched":"…",
 "points":[["2026-08",3.2,"final"]],"last_period":"2026-08"}}, "errors":{"<id>":"…"}}
```
status ∈ `final|flash|prelim|spot|estimate`. 결측 기간은 포인트 생략이 아니라 `null` 값으로 격자 정렬은 chart_pack 단계에서.
- `ROOT/data/chart_pack.json` + `ROOT/data/charts/<id>.csv` (long: `date,series_key,value,status,tier,source`), `ROOT/data/table_pack.json` — 스키마는 `mb/chart_pack.py` docstring에 정본으로 기술.
- `ROOT/data/facts.json` + `facts.md`: 지표별 최신값·직전값·변화·발표일(집필자 "알려진 사실"·Quant 입력).
- `ROOT/data/validation.json`: 검증기 결과(`status: PASS|WARN|FAIL`, 항목별).
- CLI: `python -m …monthly_brief.datastore.store build --root ROOT --as-of D`, `python -m …monthly_brief.chart_pack build --root ROOT`, `python -m …monthly_brief.validate_pack --root ROOT`.
- 웹 시계열(llm_web): `ROOT/data/web_series_<KEY>.json` (WP3가 프롬프트 제공, 형식은 v2 SERIES_HEADER와 동일한 `{"as_of","series":{id:{title,unit,frequency,x_labels,data,source,url,published,note}}}`) → store가 tier `llm_web`으로 흡수.

## 4. WP3 리서치 산출
- `ROOT/research/<AXIS>.md` (+ `_interim`/`_final` 접미는 증분 모드용, 10/6 이후), 로그 `ROOT/_work/logs/`.
- 축 키 `R01_ecb … R12_calendar_consensus`, 웹 시계열 `W1_pmi`, `W2_ois`. 보충 리서치 `G_<n>` (입력 `ROOT/_work/gaps_<round>.json` = `[{"id","question","context"}]`).
- 프롬프트 변수는 전부 `Edition` + `facts.md`에서 주입(월 하드코딩 금지).

## 5. 게이트 용어 (본문 금지 토큰 — finalize.py가 grep)
`정본, DATAPACK, datapack, §, 팀 Noir, Advisor, Quant, Chief, Polish, 감사, 채점, 본 단계, 본 회차, 본 문서, preview, spot, review, interim, 등재, [확정], [보도], [추정], [시장], [미확인]` 및 정규식 `\b[NSDRGW]\d{1,2}\b`, `\bBI-?\d+\b`, `\b[PSR]D-\d+\b`, `확인되지 않아`, `관측 대상에서 제외`, `인용하지 않는다`, `산출하지 않는다`.
(단, `_editorial/` 문서와 부록 참고문헌 표는 대상 외.)
