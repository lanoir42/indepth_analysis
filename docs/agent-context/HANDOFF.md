# indepth_analysis 현재 인수인계

## 2026-10-07 KCIF 누락 표시·공개 전환 백필

사용자 승인으로 에이전트팀이 10/6 브리프의 본문 미확보를 조사하고 공개 재확인·백필과 향후 일간 반영을 구현했다. [상세 운영·검증 기록](KCIF-PUBLIC-BACKFILL-2026-10-07.md)이 이번 작업 정본이다. **110건 재확인, 52건 신규 다운로드·본문 적재 완료**, 여전히 제한 58건과 최근 발행 대기 7건은 향후 순환 확인한다. 114테스트 통과. 기존 보고서 해시·원발행일 유지, 새 본문 52건 무결성 확인. 다음 일간 별도 섹션은 30건 상한으로 22건 이월. LLM·외부 발행·과거 보고서 전체 재생성 없음. 10/6 보고서는 상단 누락 표시만 수정했고 Executive summary 이후·주석은 그대로다. 실제 실행 백업과 남은 제한은 상세 문서의 운영 실행 절을 확인한다.

별도 리포트 전환 과제: orchestrator `docs/agent-context/REPORT-QUALITY-EVAL-2026-10-07.md`의 7종 GPT 비교는 전체 워크플로 합격이 아니다. KCIF 토픽 단일 표본의 개선 판정과 수집 성공을 혼동하지 않는다. Briefing의 earnings/SSR/Euro prun은 여전히 별도 Claude 경로다.

## 기준
- 작성일: 2026-09-11 (Asia/Seoul)
- 작성자: Codex
- 조사 체크아웃: `/Users/lanoir42/projects/indepth_analysis`
- 조사 기준 브랜치/커밋: `main` / `26506d7` (다음 세션에 다시 확인)
- 이번 목표: CLAUDE.md를 보존하며 코덱스와 모델 간 작업 연속성을 위한 문서 구성.

## 완료
- AGENTS.md 진입 안내, KNOWLEDGE.md 원문 색인, 이 인수인계 문서를 추가했다.
- 프로젝트 문서·메모리 위치와 주요 운영 제약을 조사했다. 애플리케이션의 실행 상태는 검증하지 않았다.

## 현재 작업의 범위
- 변경: `AGENTS.md`, `docs/agent-context/KNOWLEDGE.md`, `docs/agent-context/HANDOFF.md`.
- 기존 코드·CLAUDE.md·Claude 설정/메모리·데이터는 이번 변경 대상이 아니다.
- 기존 미커밋 작업은 보존한다. 과거 메모리의 TODO를 이번에 완료한 것으로 취급하지 않는다.

## 재개 전 확인
과거 보고서·메모리에 적힌 시장 수치와 다음 확장 날짜를 현재 사실로 재사용하지 않는다. 월간 브리프 v2는 전용 MANUAL/WORKLOG에서 재개 지점을 확인한다.

## 다음 행동
1. 사용자 작업 목표를 확인하고 `git status --short --branch`로 현재 변경을 대조한다.
2. KNOWLEDGE.md에서 해당 계약과 최신 메모리/작업일지를 읽는다.
3. 작업 파일·완료 기준·검증 방법을 정한 뒤 진행한다. 현재 별도의 기능 개발 과제는 배정되지 않았다.

## 검증 기록
- 이번 변경은 문서만이다. 애플리케이션 테스트·배포·서비스 재시작은 수행하지 않았다.
- 문서 경로/크기와 CLAUDE.md 보존 검사는 워크스페이스 `agent-context/SETUP.md` 참조. 이 문장만으로 애플리케이션 검증을 대신하지 않는다.

## 다음 작업 종료 시 갱신할 항목
- 목표 / 완료 / 미완료 / 막힌 이유
- 변경 경로 / 브랜치·커밋 / 기존 작업과의 관계
- 실행한 검증 명령과 결과 / 실행하지 않은 검증과 이유
- 다음 행동과 필요한 명령 / 관련 정본 문서
- 사용자 결정의 날짜·범위 / 남은 불확실성

영속 규칙은 정본 문서에 반영하고, 이 파일에는 최신 상태와 근거 링크를 남긴다. 이전 인수인계의 유효한 미완료 항목은 보존한다. 여러 작업이 동시에 진행되면 작업별 별도 인수인계를 쓰고 이 파일에서 연결한다.

## Inference migration / 2026-09-11

User decision: app inference uses GPT (Codex CLI) -> Claude CLI -> Ollama gemma4:26b; local-first features use Gemma -> GPT -> Claude. User confirmed on 2026-09-11: explicit no-cloud features remain local-only, with no GPT or Claude fallback even on local failure. Cost/speed-only local-first features retain Gemma -> GPT -> Claude.

Rollout order: reading -> Briefing -> GB -> NC dev only after GB stability is demonstrated. Personal app code, DBs and backends live on the current personal Mac. NC dev backend and DB live on the work Mac. The user identifies the current cross-boundary connection as TWS on the personal Mac, over Tailscale. Do not expand that boundary into shared personal app databases or an inference server.

[Research and next steps](../../../agent-context/INFERENCE-MIGRATION-2026-09-11.md). Static investigation and CLI version/ChatGPT login checks are complete. No inference calls, application implementation, deployment, performance tests or firewall inspection have been performed. Read this update before the earlier setup-only next steps.

## Deputy operations / 2026-09-11

The user requests Codex to act as deputy when Claude is absent: NC Dashboard backup & Sync, TJAM dated daily journal, earnings and indepth analysis operations on request. Read [deputy runbook](../../../agent-context/DEPUTY-OPERATIONS.md). Preparation only; no daily operation has been executed. The runbook records stale TJAM instructions and NC backup-failure behavior.

## 2026-09-11 KCIF 토픽 설정 연결

이 절이 위 setup-only 상태보다 최신이다. Briefing 설정 화면을 위한
`src/indepth_analysis/kcif/settings.py`와 `cli_kcif.py`의 `kcif settings [--write]`를 구현했다.
사용자는 전체 개인 리포트 목록 + 연결 가능한 항목부터 편집, 다음 정기 실행부터 적용을 선택했다.
KCIF 원본 설정의 revision 충돌·같은 daily lock·입력 검증·활성 제한·이력 보존을 유지한다.
`tests/test_kcif_settings.py` 5개 통과. Briefing에서 실제 CLI 조회로 기존 7개 활성 토픽 연결 확인.
실제 설정 저장/생성/발행/일정 변경은 실행하지 않았다. 추적 lanoir42/orchestrator#46.
기존 배치의 추론 공급자 전환은 이번 변경에 포함하지 않는다.

## 2026-09-20 리포트 폴백 구현

이 절이 앞선 환경 구성 전용 상태보다 최신입니다. [구현·롤백·미검증 사항](REPORT-FALLBACK.md)을 확인합니다. 기존 CLAUDE.md와 사용자 작업은 보존했습니다.

## 2026-09-23 KCIF 일간 리포트 — 당일 하이라이트 우선 · 주말/휴일 쉼

작성: Claude. 사용자 요청으로 `kcif/report.py` 레이아웃을 `## 오늘의 KCIF`(발행처 요약 문단 LLM 0 인용 + 반영 토픽 + md 경로) → `## Executive summary` → 실행 상태 → 별첨으로 바꾸고, 토·일과 평일 휴일(크롤 성공·신규 0건)에는 리포트를 쉬며 `reports/kcif/.skipped/{date}.json` 표지를 남긴다(`indepth kcif daily --force`로 강제). launchd plist를 `Weekday 1~5` 18:00으로 재설치(`indepth kcif schedule install`). 검증: `uv run pytest tests/test_kcif_daily_layout.py tests/test_kcif_settings.py tests/test_kcif_report_fallback.py tests/test_kcif_client.py` 통과, 실제 `kcif daily`는 실행하지 않았고 2026-09-22 미리보기는 DB 읽기 전용으로만 렌더했다. orchestrator 쪽 예정 리포트 카드(`expectations.py` `kcif-daily` 평일 전용 + 표지 시 제외)는 같은 날 별도 커밋. 첫 실운영 확인 지점: 2026-09-23(수) 18:00 산출물의 `## 오늘의 KCIF` 섹션.
