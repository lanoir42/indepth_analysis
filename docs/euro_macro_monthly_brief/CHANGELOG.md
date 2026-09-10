# CHANGELOG — 유럽 매크로 월간 리포트

## v2.1.0 — 2026-09-10 오후 (단계 태그 제목·델타 리포트)
- **제목 규약**: 모든 최종 문서 H1을 `[Preview]`/`[Spot]`/`[Review]` 태그로 시작 — Notion·Briefing 페이지 제목에 단계가 드러나도록(사용자 지시). preview 4종 소급 적용, `finalize_phase.sh`가 점검.
- **변경 비교 리포트(델타 리포트)** 신설: spot은 preview 대비, review는 spot 대비 독립 문서 `{date}_europe_macro_{phase}_delta.md`(요약·사실의 변화·예상 대 실제 채점·판단의 변화·유지된 서술·다음 확인 항목 + 채점표·수치 변경표·문서별 변경 절 부록). 역할 `roles/delta_report.md`, `noir_spot_workflow.js`에 `Delta Report` 단계(집필 → 사실·문체 감사 → 수정 1회).
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
