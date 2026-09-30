# CHANGELOG — 유럽 매크로 월간 리포트

## v3.1.0-pre — 2026-09-30 (컨센서스 선반영 초안)
- 사용자 제안: 보고 직전 발표 지표는 컨센서스를 기준점으로 초안을 먼저 쓰고, 발표 후 해당 블록만 패치.
- `edition.release_cutoff`·`pending_window`, 리서치 `W3_pending`(컨센서스·상회/하회/부합 해석)·`W4_actuals`(실제치), 역할 `release_patch.md`, `_common.md` 7절(PENDING 블록 규약), Advisor 배정 규칙, 게이트 `--allow-pending`(초안)·블록 잔존 FAIL(확정), `workflow/release_patch.js`.
- 이 구조가 interim·final 증분 모드의 기반.

## v3.0.0 — 2026-09-30 (전면 개편, 첫 회차 2026-09호)
8월호(v2.1) 감사 결과(정치 5%·메타 27%·산문 문체·장표 해설서·LLM 수집 시계열) 대응. 설계 `V3_PLAN.md`, 계약 `V3_CONTRACTS.md`.

**입력**
- BI 컬렉션 intake(`intake.py`): 1면 헤더에서 발행 시각·실제 제목·저자 파싱(Mendeley 제목·등록일 무시), 본문 정규화 sha16, 월 간 재수록·월 내 편집본 중복 판정, 조각·기간 외 판정, `references.db europe_docs`.
- 문서 카드(`cards.py`, Sonnet): 한국어 요지·핵심 수치(원문 대조 자동검증)·주장·전망·정치 행위자. 10그룹 섹션 스캐폴드.
- `session.json`: earnings SSR 계약 동형(Briefing 연동 준비).
- 결정론 데이터(`datastore/`): Eurostat(HICP `prc_hicp_minr` ECOICOP v2·속보·기여도, GDP, 실업, ESI, 산업생산, 소매, 재정)·ECB(정책금리, €STR, 대출, 환율 EUR/KRW 포함)·Bundesbank·FRED·yfinance 91시리즈, 원응답 캐시·오프라인 재빌드. LLM 시계열은 PMI·OIS만(llm_web 등급).
- 리서치 12축(`prompts.py` 재작성): 월 하드코딩 제거(`edition.json` 주입), 정치 3축(FR·DE·IT/ES/기타) + EU 제도·통상 + ECB 1차 원문 + 신용·은행·주택 신설, BI 섹션·facts를 프롬프트 맥락으로, 보충 리서치(gap) 모드.

**산출**
- 풀 리포트 + 해설본(리포트 장과 1:1 교재) 분리, 장표 텍스트 폐지.
- `chart_pack.json`(30종+, kind·축·소수·색 역할·등급·각주, 결측 null 격자) + 차트별 CSV, `table_pack.json`(9종+, 변화 열 코드 계산) + `tables.md`, `facts.md`, `validate_pack`(빈도 단일성·격자·제목 수치 대조·최신성·중복 개념).
- 3회 보고 preview·interim·final(태그 `[Preview]`·`[Interim]`·`[Final]`), final에 10장 '보고 간 판단 변화'.

**품질·오케스트레이션**
- `STYLE_BRIEF.md`(KCIF식 개조식 4단 계층), `coverage.yaml`(장별 목표 분량·필수 항목·국가 템플릿·독자 질문 18), 역할 지시서 17종을 저장소로 이전(회차 폴더 복사 폐지).
- 범용 Workflow `workflow/noir_v3.js` + 인자 생성기 `workflow/args.py`: BI 섹션∥Quant → Advisor(high) → 장별 리포트→해설본 pipeline → Polish → 8중 감사(커버리지·독자질문 신설) → 보충 리서치 → 수정(최대 2라운드) → 정합 → 게이트 수정 → 편집기록.
- `finalize.py`: 파이프라인 용어·조사 라벨·거부 문장·문체 금지어·상대 날짜·차트 참조·시점 lint 차단 게이트, 최종본 확정·스냅샷·허브 v3·session.json 단계 기록·등록.
- Opus effort: Advisor·통화정책·정치·전망·Polish high, 나머지 medium.

**예정(v3.1, 10/6 이후)**: interim·final 증분 모드(변경 장만 재집필, `BASE_DRAFT`), delta_diff v3 연동, Briefing EUROPE 탭.

## v2.1.0 — 2026-09-10 오후 (단계 태그 제목·델타 리포트)
- **제목 규약**: 모든 최종 문서 H1을 `[Preview]`/`[Spot]`/`[Review]` 태그로 시작 — Notion·Briefing 페이지 제목에 단계가 드러나도록(사용자 지시). preview 4종 소급 적용, `finalize_phase.sh`가 점검.
- **변경 비교 리포트(델타 리포트)** 신설: preview는 전월 구판 리포트·마스터클래스 예측·마지막 유럽 장표 대비, spot은 preview 대비, review는 spot 대비 독립 문서 `{date}_europe_macro_{phase}_delta.md`(요약·사실의 변화·예상 대 실제 채점·판단의 변화·유지된 서술·다음 확인 항목 + 채점표·수치 변경표·문서별 변경 절 부록). 역할 `roles/delta_report.md`, 두 워크플로 모두에 `Delta Report` 단계(집필 → 사실·문체 감사 → 수정 1회). 각 델타 리포트의 `다음 단계 반영 목록`(PD/SD/RD-xx)을 다음 단계가 항목별 처리하고 본문에 `[Phase 버전 수정 ID]` 주석을 남긴다(사용자 지시).
- 결정론 차이 추출기 `monthly_brief/delta_diff.py`: 이전 단계 `*_final.md`와 현재 회차를 절(`##`) 단위로 대조(회차·날짜 괄호는 같은 절로 취급), 변경 절은 문장 단위 unified diff, `datapack_{base}.json`·`slide_data_{base}.json` 스냅샷과 레코드·차트 증감 → `_work/delta_diff_{phase}.md`. 델타 리포트는 이 파일 밖의 변화를 서술할 수 없다.
- `finalize_phase.sh`: 6·7번째 인자(델타 회차·이전 단계), 데이터 정본 스냅샷, 제목 태그 점검, `delta_diff` 재실행, Notion 발행 명령 안내. `hub.py`: 델타 링크·등록 대상 포함, 제목 태그 선행.
- Notion 발행을 표준 절차에 편입(단계마다 별도 페이지, 장표 페이지에 `slide_data.json`·`slide_spec_{phase}.json` 첨부). preview 3종 발행 2026-09-10.
- 로드맵 v2.2로 이월: `claude -p --model opus` 무인 러너, D0/K0 CLI화, `finalize_phase.sh` Python화, review 리서치 축(N10) 정식화.

## v2.0.0 — 2026-09-10 (monthly_brief 신설, 도그푸딩 2026-08호)
구판(v1, `skills/euro_macro/` `indepth report euro-macro`, KCIF 중심 합성 리포트) 대비 변경:

**입력·데이터**
- Bloomberg Intelligence 리포트(Mendeley `EUROPE YYYYMM`) 전량 수집·텍스트화·Opus 다이제스트(D1, 클레임 JSON) — 신규 1차 인풋.
- R&I 주간 덱(`WEEKLY` `YYYYMMDD_거시경제_동향`) 전량 텍스트화 + 유럽 섹션 FTS 인덱스(`references.db weekly_europe_sections`) — 과거 유럽 장표 형식·서사 연속성·전망 채점(D2). 이후 증분 갱신.
- KCIF는 보조 소스로 격하(FTS 검색 K0).
- 웹 딥리서치를 Sonnet 축별 `claude -p` 세션 9축(N01~N09)으로 확장(구판 10토픽 120초 타임아웃 → 축별 30~40회 검색, 1차 출처·라벨·연도 규약 강제).
- 시계열: Sonnet S1~S3 + 로컬 S4(yfinance·ECB Data Portal) + 백본 시드(optionsdeck·캘린더 DB·HICP 골든 체인 참조월 매핑) → `slide_data.json` 전량 제공.
- 지표 실적·발표 일정 부록 G(N09 + ForexFactory 주간 JSON).

**팀·품질**
- 팀 Noir 파이프라인(Advisor ∥ Quant → Chief 청크 병렬 → Polish → Slide → Explainer → 문서별 3중 감사(수치·논리·문체)·수정 루프). 구판은 단일 합성 콜 + 부록 LLM.
- 모델: Opus 5 effort medium(전 분석·집필·감사), Sonnet(리서치), Fable(오케스트레이션·결정론·게이트 전용).
- 데이터 정본 파일 고정(`DATAPACK.md`/`datapack.json`, 검산·충돌·인용금지·미확인) + 임의 재계산 금지.
- 결정론 게이트: 금지어·`아니라`·상대날짜·`lint-temporal`·`lint-numeric`.

**산출·형식**
- 3단계 세트(preview → spot → review), 후속 단계는 델타 집필·감사.
- 산출 4종: 허브(Briefing 진입점) · 풀 리포트(연구보고서형 산문, 표·차트 부록) · 해설서 · 장표 텍스트(개조식, 발표자 노트·수치 대조표) + `slide_data.json`·`slide_spec_{phase}.json`.
- 문체 분리: 리포트·해설서 `STYLE_PROSE.md`(2026-09-07 피드백), 장표 `report-brief-style.md` + D2 규격.
- Briefing 앱 호환 링크 규격(절대경로만) 적용, 허브 생성기 `hub.py --register`.

**코드**
- `skills/euro_macro/monthly_brief/`: `sources.py`, `backbone.py`, `market_data.py`, `prompts.py`, `research.py`, `hub.py`, `usage_report.py`(토큰·환산비용·플랜 스냅샷), `run_stages`; CLI `indepth report euro-macro-monthly-brief --stage fetch backbone market research series`.

**알려진 한계 / v2.1 예정**
- Opus 단계(D1·D2·Advisor~Final)는 Claude Code Workflow/Agent에서 실행(무인 `claude -p` 러너 미구현). v2.2 예정: `--stage digest design write audit`를 `claude -p --model opus` 러너로 편입, D0/K0 결정론 단계 CLI화, `finalize_phase.sh`의 Python화, review 단계 리서치 축(N10 post-ECB) 정식화.
- Eurostat 벌크 API 정지 시 2026년 HICP는 골든 체인·보도자료 의존.
- 은행·자동차 섹터 지수는 ETF 프록시(EXV1/EXV5).

## v1.x — 2026-02 ~ 2026-08 (`indepth report euro-macro`)
- KCIF 시맨틱 검색 + ForexFactory/FRED/frankfurter + 10토픽 웹리서치 → Opus 단일 합성 8섹션 + 결정론 섹션 A/B/G/H + 부록 I~V, 마스터클래스 해설서. 상세는 `CLAUDE.md` "Euro Macro Pipeline".
