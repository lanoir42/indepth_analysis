# 유럽 매크로 월간 브리프 v2 — 운영 매뉴얼

- 버전: **v2.0.0** (2026-09-10, 도그푸딩 회차 2026-08호 / 9-14 보고)
- 코드: `src/indepth_analysis/skills/euro_macro/monthly_brief/` (`__version__`), 문서: 이 디렉터리(`MANUAL.md`, `CHANGELOG.md`)
- 산출 루트: `reports/euro_macro/monthly_brief/<YYYY-MM>/` (Briefing 저널 라벨 `indepth_analysis/euro_macro/monthly_brief/<YYYY-MM>`)

## 1. 무엇을 만드는가

한 달치 유럽 매크로 현황을 **세 단계 세트**로 낸다. 월간 보고일 근처에 ECB 결정이 오기 때문이다.

| 단계 | 시점 | 산출(4종 + 데이터) | 생성 방식 |
|---|---|---|---|
| preview | 결정 1~2주 전(보고 필요 시) | `{date}_europe_macro_preview_{index,report,explainer,slide}.md` | 전량 집필 |
| spot | 결정 직후(월간 보고일) | `{date}_europe_macro_spot_*.md` | preview 최종본 + 신규 리서치(N01·N09) 델타 |
| review | 결정 1~2주 후 | `{date}_europe_macro_review_*.md` | spot 최종본 + 신규 리서치 델타 + 전망 채점 |

문서 성격: **리포트·해설서 = 연구보고서형 산문**(`STYLE_PROSE.md`, 표·차트는 부록), **장표 = R&I 주간 덱 개조식**(`~/.claude/styles/report-brief-style.md` + 과거 유럽 장표 규격 D2). 모든 단계에 **부록 G(최근 4주 지표 실적·향후 1주 발표 일정·8~30일 주요 일정)** 포함.

데이터: `data/slide_data.json`(차트 시계열 전량, Claude for PowerPoint 입력), `data/slide_spec_{phase}.json`(장표 레이아웃·불릿·차트 매핑), `data/datapack.json`+`DATAPACK.md`(수치 정본·검산·충돌·인용금지·미확인), `data/indicator_calendar_{phase}.md`.

## 2. 사용 전 준비 (체크리스트)

1. **Mendeley**: 컬렉션 `EUROPE YYYYMM`에 Bloomberg Intelligence PDF 업로드 완료. WEEKLY 컬렉션에 최신 `YYYYMMDD_거시경제_동향` 업로드 확인. 토큰 `~/.mendeley_token.json` 유효(만료 시 earnings 프로젝트 `mendeley-login`).
2. **claude CLI** PATH(`which claude`), 세션 로그인 상태. Sonnet 리서치는 축별 `claude -p` 세션(각자 WebSearch 예산)이라 동시 8개까지 병렬.
3. **로컬 DB**: optionsdeck 스냅샷(`~/.optionsdeck-gb/data/macro.db`, launchd 자동), `data/macro_calendar.db`(HICP 골든 체인), `references/references.db`.
4. **KCIF**: `uv run indepth kcif daily`가 최근까지 돌았는지(`references/KCIF_md/` 최신 파일 날짜).
5. **네트워크**: yfinance·ECB Data Portal(`data-api.ecb.europa.eu`)·ForexFactory JSON 접근 가능.
6. 보고 날짜·ECB 회의 일정 확인(ECB 캘린더). 결정 발표 14:15 CET(=21:15 KST, 서머타임), 기자회견 14:45 CET.

## 3. 표준 절차

### 3-1. 결정론·Sonnet 단계 (CLI)
```bash
# 1) 수집·인덱스·백본·시장 시계열 (멱등, 재실행 안전)
uv run indepth report euro-macro-monthly-brief --month 2026-08 --as-of 2026-09-10 \
  --stage fetch backbone market
# 2) Sonnet 리서치(N02~N09) + 시계열 에이전트(S1~S3) — ECB 결정 전에는 N01 제외
uv run indepth report euro-macro-monthly-brief --month 2026-08 --as-of 2026-09-10 \
  --stage research series --axes N02 N03 N04 N05 N06 N07 N08 N09
# 3) 결정 직후(spot): N01 + N09 재실행(접미 _spot)
uv run python -m indepth_analysis.skills.euro_macro.monthly_brief.research \
  --root reports/euro_macro/monthly_brief/2026-08 --month 2026-08 --as-of 2026-09-11 \
  --axes N01 N09 --suffix _spot
```
산출: `references/mendeley_europe/YYYYMM/*.{pdf,md}`, `references/mendeley_weekly/*`, `references.db weekly_europe_sections`(FTS), `data/backbone_seed.json`, `data/series_S1~S4*.json`, `research/N*.md`, `_work/logs/*.err`(각 `exit=` 확인).

### 3-2. Opus 다이제스트 (Claude Code Agent, Opus medium)
- D1 BI Digest: `references/mendeley_europe/YYYYMM/*.md` → `research/D1_bi_digest.md` + `data/bi_claims.json`
- D2 Weekly Digest: `weekly_europe_sections` → `research/D2_weekly_europe_digest.md`(장표 규격·서사 연속성·전망 채점·후보 불릿)
- D0/K0는 결정론(`research/D0_prior_europe_slides.md`, `research/K0_kcif_europe.md`) — 이번 회차 스크립트는 `_work/`·대화 기록 참조, v2.1에서 CLI 단계로 편입 예정.

### 3-3. 팀 Noir Workflow (Claude Code, Opus 5 medium)
- 회차 루트에 `roles/`(역할 지시서 12종)·`STYLE_PROSE.md`·`_work/noir_workflow.js`·`_work/noir_spot_workflow.js`를 둔다(이번 회차 것을 복사해 ROOT 상수만 바꿈).
- preview: `Workflow(scriptPath=_work/noir_workflow.js, args={phase:'preview', asOf, reportDate})`
  → Design(Advisor ∥ Quant) → Write(Chief 3청크 → Polish) → Slide → Explainer → 문서별 3중 감사(수치·논리·문체)·수정 루프(최대 3라운드).
- spot/review: `Workflow(scriptPath=_work/noir_spot_workflow.js, args={phase:'spot', asOf, reportDate, baseFinal:'preview', newResearch:'...'})`
  → Advisor 델타 골자 ∥ Quant 갱신 → Delta Writer(변경 절만) → 3중 감사 루프.
- 모델 제한: 전 역할 Opus 5 effort medium. Fable은 오케스트레이션·결정론 코드·게이트만.

### 3-4. 마감 (게이트·파일명·허브·등록·Notion)
```bash
# preview (델타 = 전월 리포트·마지막 장표 대비)
_work/finalize_phase.sh preview 2026-09-10 preview_report_r6 preview_slide_r6 preview_explainer_r6 preview_delta_r2
# spot / review (6번째 인자 = 델타 리포트 회차, 7번째 = 이전 단계; 생략 시 spot→preview, review→spot)
_work/finalize_phase.sh spot 2026-09-14 spot_report_rS spot_slide_rS spot_explainer_rS spot_delta_r2
# 게이트 로그 _work/gates_{phase}.log 확인 후 등록
uv run python -m indepth_analysis.skills.euro_macro.monthly_brief.hub \
  --root reports/euro_macro/monthly_brief/2026-08 --report-date 2026-09-14 --month 2026-08 \
  --phase spot --register
# Notion (사용자 지시 2026-09-10: 단계마다 별도 페이지, 제목 태그 [Preview]/[Spot]/[Review])
for f in report explainer delta; do uv run indepth publish reports/euro_macro/monthly_brief/2026-08/2026-09-14_europe_macro_spot_$f.md; done
uv run indepth publish reports/euro_macro/monthly_brief/2026-08/2026-09-14_europe_macro_spot_slide.md \
  --attach reports/euro_macro/monthly_brief/2026-08/data/slide_data.json reports/euro_macro/monthly_brief/2026-08/data/slide_spec_spot.json
```
`finalize_phase.sh`가 하는 일: 최종본 복사 → **데이터 정본 스냅샷**(`data/datapack_{phase}.json`, `slide_data_{phase}.json` — 다음 단계 델타 비교의 기준) → H1 제목 태그 점검 → 게이트 → (spot·review) `delta_diff.py` 재실행 → 허브 → 토큰 리포트.
게이트: 금지어 0·`아니라/아닌` ≤3(장표 0)·상대날짜 0·`lint-temporal` HIGH 0·`lint-numeric` 자문. 허브 문서가 Briefing 진입점(요약·장표 텍스트·전 문서 절대경로 링크·BI PDF 링크·델타 리포트 링크).
Notion 페이지 제목은 파일의 H1에서 나오므로 H1이 `[Spot] …`로 시작해야 한다(장표 파일의 H1도 태그를 붙이되, 덱에 넣는 슬라이드 제목은 본문의 `Macroeconomic Brief: 유럽` 그대로). `lint-numeric` HIGH는 자문(정규식 오탐 — OIS 확률을 DFR로 읽는 등)이며 발행을 막지 않는다.

**변경 비교 리포트(델타 리포트, v2.1)**: 세 단계 모두 Workflow의 마지막 단계 `Delta Report`가 독립 문서 `drafts/{phase}_delta_rN.md`를 쓴다(역할 `roles/delta_report.md`, 사실·문체 감사 1회 + 수정 1회). preview는 전월 구판 리포트·마스터클래스 예측·마지막 유럽 장표 대비(결정론 차이 파일 없이 문서 대조), spot은 preview 대비, review는 spot 대비. 모든 델타 리포트는 `## 다음 단계 반영 목록`(PD/SD/RD-xx: 대상·현재 문장·문제·권고·근거·확정 시점)을 담고, 다음 단계 Delta Writer가 항목별로 반영·보류·기각을 처리하며 반영 문장 뒤에 `[Spot 버전 수정 PD-xx: …]` 주석(장표는 발표자 노트)을 남긴다. 근거는 결정론 차이 파일 `_work/delta_diff_{phase}.md`뿐이다 — 이 파일에 없는 변화는 서술 금지, 있는 유의미한 변화는 누락 금지가 감사 기준. 수동 재생성:
```bash
uv run python -m indepth_analysis.skills.euro_macro.monthly_brief.delta_diff \
  --root reports/euro_macro/monthly_brief/2026-08 --base preview --phase spot --cur-suffix rS
```

**토큰 사용량 리포트**(단계마다, `finalize_phase.sh`가 자동 실행): `uv run python -m indepth_analysis.skills.euro_macro.monthly_brief.usage_report --root <루트> --phase <단계> --since <파이프라인 시작 ISO> --session <메인 세션 id>` → `_work/usage_report_{phase}.md/.json`. Claude Code 트랜스크립트(메인·`claude -p`·Agent·Workflow)를 스캔해 역할·모델별 토큰과 API 정가 환산 USD, 그리고 플랜 사용량 스냅샷(5시간·7일 소진율, 키체인 OAuth로 조회·토큰 미출력)을 기록. 파이프라인 시작 전에도 한 번 실행해 두면 전후 차이로 이번 회차 플랜 소비분을 볼 수 있다. 환산액은 구독 과금이 아닌 정가 기준 참고치.

### 3-5. 장표 제작
Claude for PowerPoint에 `{date}_europe_macro_{phase}_slide.md`(불릿·발표자 노트·수치 대조표) + `data/slide_spec_{phase}.json` + `data/slide_data.json`을 입력. 차트는 D2 규격(선그래프 2 + 전월/당월 비교표 1).

## 4. 주의사항

- **연도 혼동**: 검색엔진이 2025년 사건을 2026년으로 노출하는 사례가 잦다(예: 2025-09-08 Bayrou 불신임). 리서처 규약·감사·`lint-temporal`이 3중으로 걸러도 최종 검토에서 ECB 회의·정치 사건의 연도를 한 번 더 본다.
- **시점 절단선**: 통계 개정(예: 2Q26 GDP 0.4%→0.6%, 9/7)이 BI 문서 발행일 전후로 갈린다. BI 인용 시 발행일을 함께 적고 DATAPACK §충돌을 확인한다.
- **Eurostat 벌크 API 정지**: 2025-12 이후 데이터가 비어 있으면 로컬 골든 체인(`backbone_seed.json eu_cpi_prints`)과 Euro Indicators 보도자료로 보강한다. 보간·외삽 금지.
- **Mendeley**: `find_folder_by_name`이 폴더 목록 페이지네이션 때문에 None을 줄 수 있음(`_folder_id` 폴백 내장). 문서 수가 늘어나는 중이면 `fetch`를 재실행(멱등). macOS 파일명이 NFD라 한글 `grep`이 안 맞음 — glob·절대경로 사용.
- **Briefing 링크**: 문서 간 링크는 절대경로만 탭 가능. 상대경로·`[[위키링크]]`·JSON 링크는 무효(JSON은 경로 텍스트로). PDF는 절대경로(≤8MB). 산출 파일명은 날짜 포함, `NN_`·`_`·`.` 접두 파일/폴더는 스캔 제외(계획서·작업 폴더는 의도적으로 제외).
- **장표 문체와 리포트 문체가 다르다**: 장표는 개조식(2단 표준, `→` 최대 1회, 300~520자, `>e`는 출처가 있을 때만), 리포트·해설서는 산문. 감사자도 문서 종류별로 다른 정본을 쓴다.
- **집필자 자가검증은 신뢰하지 않음**: 감사는 항상 별도 에이전트. 수정본은 재감사(라운드 2 이상에서 HIGH 0·PASS일 때만 종료).
- **WebSearch 예산**: Agent 툴 서브에이전트는 세션 공용 예산을 쓰므로 웹리서치는 반드시 `claude -p` 서브프로세스(`research.py`)로.
- **비밀**: `NOTION_TOKEN` 등은 출력 금지. Notion 발행은 선택(`uv run indepth publish`).

## 5. 정례 일정(권장) — **모든 단계는 사용자의 요청으로 시작한다(자동 실행 없음)**

각 단계 착수 시 사용자가 추가 자료(Mendeley 컬렉션 신규 PDF, 보도자료, 메모)를 제공할 수 있다. 제공 파일은 `references/mendeley_europe/<YYYYMM>/` 또는 회차 루트 `inbox/`에 두면 `fetch`(멱등 재실행)·D1 갱신·Quant 갱신 순으로 흡수한다.
- 결정 D-3~D-1: fetch/backbone/market/research/series → D1·D2 → preview Workflow → 마감·등록(프리뷰 보고 필요 시).
- 결정 이후(사용자 요청 시): N01·N09 `_spot` 리서치 → (추가 자료 있으면 fetch·D1 갱신) → spot Workflow → 마감·등록 → 월간 보고.
- D+10~14: N01 후속(위원 발언·시장 소화)·N09 재실행 `_review` → review Workflow → 등록.
- 다음 달: 컬렉션 `EUROPE YYYYMM` 신설 후 `fetch`부터 반복. 주간 인덱스는 증분.

## 6. 파일 지도
```
reports/euro_macro/monthly_brief/<YYYY-MM>/
  00_dev_plan.md · STYLE_PROSE.md · roles/*.md · 02_advisor_skeleton_{phase}.md
  research/  D0 D1 D2 K0 N01~N09(+_spot/_review) S1~S3
  data/      backbone_seed.json series_S1~S4*.json bi_claims.json datapack.json DATAPACK.md
             slide_data.json slide_spec_{phase}.json indicator_calendar_{phase}.md ff_calendar_week.json
  drafts/    {phase}_{report,slide,explainer,delta}_rN.md → *_final.md
  data/      datapack_{phase}.json slide_data_{phase}.json   ← 단계 마감 스냅샷(델타 비교 기준)
  _work/     delta_diff_{phase}.md   ← 결정론 차이 파일(spot·review)
  audit/     {draft}_audit_{fact,logic,style}.md · *_fix_log.md
  _work/     noir_workflow.js noir_spot_workflow.js finalize_phase.sh gates.sh run_*.sh logs/
  {date}_europe_macro_{phase}_{index,report,explainer,slide,delta}.md   ← Briefing 등록·Notion 발행 대상 (H1은 [Phase] 태그로 시작)
```

## 7. 장애 대응
| 증상 | 대응 |
|---|---|
| 리서치 `.err`에 `exit=1`/빈 출력 | 해당 축만 `--axes Nxx` 재실행(기존 산출 2,000자 초과 시 skip → 파일 삭제 후) |
| 시계열 JSON 파싱 실패(`exit=65`) | `research/Sx.md`의 코드펜스 확인 후 `parse_series_json` 재시도, 또는 S4 로컬로 대체 |
| Workflow 중단 | `Workflow(scriptPath, resumeFromRunId)`로 재개(완료 에이전트는 캐시) |
| 게이트 HIGH 잔존 | Final 1회 추가(`roles/final.md`) 후 재게이트; 오탐이면 `_work/gates_*.log`에 사유 기록 |
| `briefing register` 2분 초과 | 정상(스마트 요약 LLM). 백그라운드 실행 후 `journal.db` reports 행 확인 |
