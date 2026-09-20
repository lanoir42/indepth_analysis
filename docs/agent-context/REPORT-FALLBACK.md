# 리포트 폴백 — 2026-09-20

## 구현 범위

기존 Claude 우선순위를 유지하고 같은 등급의 Codex CLI로 한 번 전환한다.
Haiku→Luna, Sonnet→Terra, Opus→Sol. API 키를 전달하지 않으며 CLI 구독 인증을 사용한다.

연결: KCIF JSON/텍스트, euro_macro 웹조사·합성·부록, monthly_brief research,
weekly_brief 연구/텍스트, masterclass 생성, issue_track 검색·합성·slug, dev_welfare 검색·합성.
실제 출력 모델을 합성 보고서 metadata에 기록한다. 요청/응답 원문을 ledger에 저장하지 않는다.

- 전환: 사용량 제한, 실행 실패, 시간 초과, 빈 응답, 잘못된 CLI envelope.
- KCIF required_keys JSON 검증 실패도 전환; 양쪽 실패 시 None으로 기존 watermark 보호 경로 유지.
- 요청별 공통 제한시간: Claude에 잔여시간 65%, Codex에 나머지; 각 1회.
- 명시적 quota는 900초 cooldown을 SQLite에 저장하여 다음 단계에서 Claude를 건너뛴다.
- masterclass의 기존 바깥 재시도는 이 경로에서 제거하여 두 공급자를 반복 호출하지 않는다.
- 취소 시 프로세스 그룹 회수 후 취소를 전파하며 fallback을 시작하지 않는다.
- 월간 research는 성공한 출력만 저장. temporal/numeric 게이트의 기존 차단/자문 정책 유지.
- issue slug 생성 시 사용하지 않던 중복 검색 호출 제거.

## 로컬 적용 / 롤백

이 머신의 `data/report-fallback.enabled` 파일로 다음 CLI 실행부터 적용한다.
`INDEPTH_REPORT_FALLBACK=0`을 지정하면 marker보다 우선하여 기존 경로로 복귀한다.
일정·발행·실제 리포트 생성은 실행하지 않는다. 상주 서버 재시작이 필요하지 않다.
`data/report_inference.db` attempts에는 provider/model/status/timing/tokens를 기록하며
미보고 토큰은 NULL이다. provider_state는 cooldown뿐이며 원문/계좌 데이터가 없다.
동일 프로젝트 내부 상태이고 형제 프로젝트를 런타임 import하지 않는다.

## 검증

`.venv/bin/python -m pytest -q tests/test_kcif_report_fallback.py tests/test_async_report_fallback.py tests/test_report_entrypoints.py tests/test_masterclass_orchestrator.py tests/test_research_completion.py`
→ 42 passed. 합성의 빈 자료/정상 자료, 실제 모델 표기, 비정상 envelope,
nonzero quota→fallback→cooldown, KCIF schema 실패, 중복 재시도 방지 포함.
async 취소는 로컬 Python sleep 프로세스만으로 회수 검증. 나머지 CLI는 모의 응답.
실제 유료 LLM 호출, 전체 리포트 발행, 시장 수치/문체 품질은 미검증이다.

## 남은 범위

Topic-update 등 대화형 에이전트 워크플로와 독립 scripts의 모든 호출을 자동 전환했다고 간주하지 않는다.
일부 웹조사 JSON과 장문 리포트는 기존 후처리 파서가 semantic 검증을 담당한다.
잘못된 내용의 재생성, 출처 신뢰도, 공급자 간 결과 품질 동등성은 별도 평가가 필요하다.
