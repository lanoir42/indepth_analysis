# 작업일지 — 유럽 매크로 월간 브리프 v2 (및 병행 프로젝트)

## 2026-09-10 (목)

### 배경·지시
- 07:45 사용자 지시: Europe Macro 월간 리포트 버전업. 9/14(월) 오전 8월 매크로 월간 보고. 입력을 KCIF 중심에서 Mendeley `EUROPE 202608`(Bloomberg Intelligence) + WEEKLY 덱 유럽 섹션(이번은 전량, 이후 인덱스 DB) + 웹 딥리서치로 전환. 목적물: `20260914_거시경제_현황`의 「Macroeconomic Brief: 유럽」 장표 + 풀 리포트 + 해설서 + 데이터 JSON(Claude for PowerPoint). 팀 Noir(Opus 5 medium, Sonnet 병행), Fable은 지휘. 문체: 산문 리포트, 표·차트는 부록.
- 추가 지시(순서대로): Briefing 앱에서 잘 보이도록 연관 문서 링크 포함 / 매뉴얼·버저닝·변경 목록 작성 / 토큰·달러환산·플랜 사용량 리포트 / **preview–spot–review 3단계 세트**(ECB 결정이 월간 보고일 근처에 오는 구조) / 각 단계 최신 지표 actual + 향후 1주 발표 목록 부록 / **자동 실행 대신 사용자 요청 시 착수**(추가 자료 제공 가능).

### 수행
1. 개발 계획서 `reports/euro_macro/monthly_brief/2026-08/00_dev_plan.md`(요구 7건 매핑·파이프라인·산출 규격·일정·정례화·3단계 세트).
2. 서브스킬 `skills/euro_macro/monthly_brief/` 신설: `sources.py`(Mendeley 수집·텍스트화·`weekly_europe_sections` FTS 인덱스), `backbone.py`(optionsdeck·캘린더 DB·HICP 골든 체인 참조월 매핑), `market_data.py`(yfinance·ECB Data Portal 월평균 10y·스프레드), `prompts.py`/`research.py`(Sonnet 9축 `claude -p` 러너, `--suffix`), `hub.py`(Briefing 허브·등록, 단계 인식), `usage_report.py`(토큰·정가 환산·플랜 스냅샷), `run_stages`; CLI `indepth report euro-macro-monthly-brief --stage fetch backbone market research series`.
3. 입력 확보: BI 83건, 주간 덱 19건(유럽 페이지 27건 인덱스), KCIF K0, 과거 유럽 장표 D0(7건), Opus 다이제스트 D1(클레임 409)·D2(장표 규격·서사·채점·후보 불릿), Sonnet N02~N09 + 시계열 S1~S3 + 로컬 S4, ForexFactory 주간 JSON.
4. Briefing 링크 규격 조사(Explore): 절대경로 링크만 유효, JSON 링크 무효, PDF 절대경로 가능, `(#slug)` 목차 동작 → 역할 지시서·허브 생성기 반영.
5. 팀 Noir preview Workflow: Design(Advisor∥Quant) → Chief 3청크 → Polish → Slide → Explainer → 문서별 3중 감사 r1~r3 → **세트 정합 r4**(단일 편집자) → 재감사 r5 → 최종 r6. 결정론 게이트 통과(금지어 0·시점 HIGH 0). 최종 4종 + 데이터 파일 저장, Briefing 등록(ID 1224~1227). 세트 정합 라운드를 표준 스크립트 2종에 편입.
6. 문서: `MANUAL.md`, `CHANGELOG.md`(v2.0.0), `CLAUDE.md` 런북 항목, 프로젝트 메모리.
7. 사용량: preview 회차 환산 $248.54(Opus 86%·Fable 11%·Sonnet 3%), 플랜 7일 창 41%→45%.
8. 자동 실행(23:00 N01·23:43 Workflow 크론) 해제 — 사용자 요청 시 착수로 전환.

### 교훈
- Eurostat 벌크 API 정지(2025-12) → 로컬 골든 체인으로 보강. Mendeley 폴더 목록 페이지네이션(`find_folder_by_name` None). macOS NFD 파일명 → 한글 grep 불가.
- 문서별 감사 루프는 수렴하지 않고 라운드마다 새 HIGH를 냄 → 3라운드 + 세트 정합 1회 + 최종 1회로 컷. 세트 간 판정 강도 불일치는 별도 라운드 필수.
- 유럽 장표 실측 규격은 `>e` 표기 0건·2단 표준·차트 3개(비교표 포함) — 일반 문체 사양과 다름.

### 다음
- spot: 사용자 요청 시 `research --axes N01 N09 --suffix _spot --as-of <날짜>` → 추가 자료 fetch·D1 갱신 → `noir_spot_workflow.js`(phase=spot, baseFinal=preview) → `finalize_phase.sh spot 2026-09-14 …` → `hub.py --phase spot --register`.
- review: 결정 1~2주 후 동일 절차(phase=review, baseFinal=spot). v2.1: Opus 단계 무인 러너, D0/K0 CLI화.

### 병행 프로젝트 상태
- **IAA·리워드 시장 PMI 연구(팀 Noir, `reports/iaa_pmi_2026_09/`)**: 9/7 사용자 요청으로 Write 단계 진행 중 중단·보류. Design(골자·정본) 완료, drafts 비어 있음. 재개는 `Workflow(scriptPath, resumeFromRunId: wf_19a57b9b-276)`.
- **주간 브리프 검증(2026-09-07)**: 완료·등록. 정례화 결정 대기.

## 2026-09-10 (오후) — Notion 발행·제목 태그·델타 리포트 (v2.1.0)

**지시**: (1) Notion 발행 여부 질문 → 미발행 확인 후 "큰 제목으로 프리뷰라고 하고, 스팟은 스팟이라고 해서 또 리포팅". (2) spot은 preview 대비, review는 spot 대비 **변경 비교(델타) 리포트** 추가.

**수행**
1. preview 4종 H1을 `[Preview] …`로 변경(파일·drafts final 동기). 허브 제목도 태그 선행으로 재생성·재등록.
2. Notion 발행 3건(원본 .md 첨부, 장표 페이지에 `slide_data.json`·`slide_spec_preview.json` 첨부). 시점 게이트 통과, `lint-numeric` HIGH는 정규식 오탐(OIS 70%→DFR, 실업률 구문 등) — 로그 `_work/logs/notion_publish_preview.log`.
   - 리포트 https://app.notion.com/p/Preview-2026-8-2026-09-10-3d7294e2c0788107983fe45df8ac22cc
   - 해설서 https://app.notion.com/p/Preview-2026-8-2026-09-10-3d7294e2c07881e6b8bce74c90fcadde
   - 장표 https://app.notion.com/p/Preview-Macroeconomic-Brief-2026-09-10-3d7294e2c078811f9f55d0ae4c4d87fc
3. 델타 리포트 체계: `delta_diff.py`(결정론 차이) + `roles/delta_report.md` + spot 워크플로 `Delta Report` 단계 + `finalize_phase.sh` 스냅샷·6/7번째 인자 + `hub.py` 링크·등록. preview 데이터 스냅샷 `data/datapack_preview.json`·`slide_data_preview.json` 생성(spot 비교 기준). 스모크 테스트(preview vs preview): 절·레코드·차트 전부 동일로 정상.
4. 문서: `_common.md` 제목·델타 규약, MANUAL §3-4·§6, CHANGELOG v2.1.0, `__version__ 2.1.0`.

**다음**: spot 착수 시(사용자 요청) 절차는 MANUAL §3 그대로 — Workflow가 델타 리포트까지 만들고, `finalize_phase.sh spot 2026-09-14 <report_rN> <slide_rN> <explainer_rN> <delta_rN>` → 등록 → Notion 4건(리포트·해설서·장표·델타).

## 2026-09-10 (오후 2) — preview 델타 리포트 + 다음 단계 반영 목록 (PD)

**지시**: "프리뷰에도 델타리포트는 만들 수 있지 않나요? 스팟에는 이를 반영하여 고칠 수 있는 부분이 있다면 스팟 버전이라고 고쳐서 포함, 무엇을 고쳤는지 주석과 함께."

**수행**
1. `roles/delta_report.md`에 preview 모드(기준물 = 구판 8월 리포트 8/6·마스터클래스 예측·8/10 유럽 장표·D2 §3) + 모든 단계 필수 `## 다음 단계 반영 목록`(PD/SD/RD-xx: 대상·현재 문장·문제·권고·근거·확정 시점). `roles/delta_writer.md`에 항목별 반영·보류·기각 처리 + 본문 `[Spot 버전 수정 PD-xx: …]` 주석(장표는 발표자 노트) + 변경 이력 첫 표 규칙. `noir_workflow.js`에도 Delta Report 단계 추가. 분량 기준 명시(공백 제외·1~6절).
2. preview 델타 r1(Opus, 8분) → 사실 감사(HIGH 2·MEDIUM 9·LOW 8)·문체 감사(PASS, MEDIUM 2) → r2(26/27 반영). 채점 22항목: 적중 1·부분 10·불일치 6·미판정 5. PD 12건(병합 후). 게이트: 금지어 0·아니라 1·상대날짜 0·temporal HIGH 0·numeric HIGH 1(7월 참조값 대비 8월 3.3% 오탐).
3. `2026-09-10_europe_macro_preview_delta.md` 확정, 허브 재생성(델타 링크)·Briefing 등록, Notion 발행: https://app.notion.com/p/Preview-8-8-10-Preview-2026-09-10-3d7294e2c07881af98aaf
4. 잔존: 본문 공백 포함 12,677자(공백 제외 9,990자 — 기준을 공백 제외로 확정), BI 산출값 8건 라벨 의존(Quant 등재 전까지 반복), PD-01·02/06·03·15는 spot 착수 전 처리 필요.

**spot 착수 시 추가 절차**: Delta Writer가 `drafts/preview_delta_final.md` §7 PD 목록을 항목별 처리(스팟 착수 전 4건은 Quant/정본 정정 선행) → 본문 주석 → 변경 이력 표. 미커밋 변경: roles 3종·workflow 2종·hub.py 문구·MANUAL·CHANGELOG·WORKLOG.


## 2026-09-30 (수) — v3 개편 설계·개발

**지시**: 8월호 품질 부족(정치·경제 상세 부족, 풀 리포트·해설본 분리, PPT용 raw data JSON) → 파이프라인 재검토·개발 후 9월호(`EUROPE 202609`). 후속으로 Briefing이 SSR 컬렉션처럼 EUROPE 컬렉션 처리 예정(설계 반영). 결정: 3회 보고 10/5 preview(기준 10/2)·10/12 interim(10/9)·10/19 final(10/16, 판단 변화 고찰 장), 장표 텍스트 생략, 리포트 5~7만·해설본 4~5만 자, Opus 핵심 장 high. 개발은 오늘 전량, 증분 모드만 10/6 이후.

**수행**
1. 진단(감사 에이전트 2): 정치 5%·메타 27%·거부 문장 12·산문 문체·장표 해설서(중복 45~50%); 시계열 LLM 수집·수기 전사·결측·축 혼합·표 JSON 부재. 프롬프트 8월 하드코딩, spot·review 미실행. Eurostat HICP 신규 데이터셋 `prc_hicp_minr` 발견(2026-08까지).
2. 계획 `V3_PLAN.md`, 계약 `V3_CONTRACTS.md`. 병렬 개발 3팩(에이전트) + 통합.
   - WP1 intake·cards·contract: 202609 84건 + 202608 창 내 14건 = 98건 전량 카드, 월 간 재수록 12, 월 내 편집본 중복 4, key_numbers 725 중 미검증 1.
   - WP2 datastore·chart/table pack·facts·validate: 91시리즈(api 78·market 10·local 3, 오류 0), 차트 30(PMI·OIS 3종은 웹 시계열 대기), 표 9, 검증 WARN 6·FAIL 0, 결정론 비율 100%.
   - WP3/4 prompts(12축+W1·W2+gap)·research v3·STYLE_BRIEF·coverage.yaml·roles 17종.
   - 통합: `edition.py`, `finalize.py`(게이트·promote·허브 v3·session 단계), `workflow/noir_v3.js`·`args.py`, `__init__.run_stages` v3, CLI.
3. 검증: pytest 582 통과, ruff 통과, CLI `--stage intake data workflow-args` 종단 실행, 8월 리포트에 게이트 적용 시 FAIL(정본 46·§ 22 등) 확인, 워크플로 구문 검사.
4. 문서: MANUAL v3(v2 보존), CHANGELOG v3.0.0, CLAUDE.md.

**다음 (preview)**
- 10/2(금) 오후(9월 HICP 속보 공개 후): `edition init`(as-of 10/2) → `--stage fetch intake cards data research` → `--stage data workflow-args` → Workflow `noir_v3.js` → `finalize promote --register` → 10/5 보고.
- 확인 필요: 9월 HICP 속보 공개일(로컬 캘린더 10/2, 리서치로 확정), Brent dated(FRED) 지연 WARN.
- 10/6~: v3.1 증분 모드(interim·final), delta_diff v3.

## 2026-09-30 (수, 오후) — 컨센서스 선반영 초안·소규모 시험 실행

- 사용자 제안 채택: 보고 직전 발표 지표는 컨센서스를 기준점으로 초안 → 발표 후 해당 블록만 패치(`release_patch`). 이 구조를 interim·final 증분 모드의 기반으로 삼음.
- 구현: `edition.release_cutoff`, 리서치 W3(컨센서스)·W4(실제치), `roles/_common.md` 7절·`release_patch.md`, 게이트 `--allow-pending`, `workflow/release_patch.js`.
- 리서치 실행(기준 9/30): 12축 + W1·W2·W3 전량 exit=0(440KB). 발표 대기 12건 — 9월 HICP 속보는 **10/2**(컨센서스 헤드라인 3.6%·근원 2.5%). OIS 회의별 경로는 유료 소스라 전 구간 null(추정 금지 준수) → 차트 생략.
- 데이터 재빌드: 109시리즈(llm_web 18: PMI), 차트 32·표 9, 검증 FAIL 0(OIS 회의일 빈도 오분류 수정, 전 구간 결측 차트 생략 규칙 추가).
- 소규모 시험(스크래치, 그룹 UK·장 ch08·1라운드): 22 에이전트 오류 0, 54분. KCIF 문체·실명·메커니즘·출처 품질 확인. 발견: 상대 날짜 정규식 '연내일' 오탐 → 한글 경계 추가. `lint-numeric` 참조 DB의 DFR 2.25%(실제 2.50%)가 낡음 — 자문이라 차단 없음.
