# indepth_analysis 지식 색인

확인일: 2026-09-11. 목적: 필요한 원문을 찾는 지도. 런타임 상태나 시장 데이터의 최신성을 보증하지 않는다.

## 프로젝트 요약
유럽 거시 월간/주간 보고서, 주제별 심층 리서치, 자료 검색·발행 플랫폼.

주요 구현: src/indepth_analysis/ · src/indepth_analysis/skills/ · scripts/ · reports/

## 저장소 안의 근거
- [CLAUDE.md](../../CLAUDE.md)
- [README.md](../../README.md)
- [docs/euro_macro_monthly_brief/MANUAL.md](../../docs/euro_macro_monthly_brief/MANUAL.md)
- [docs/euro_macro_monthly_brief/CHANGELOG.md](../../docs/euro_macro_monthly_brief/CHANGELOG.md)
- [docs/euro_macro_monthly_brief/WORKLOG.md](../../docs/euro_macro_monthly_brief/WORKLOG.md)
- [src/indepth_analysis/skills/topic_update/CLAUDE.md](../../src/indepth_analysis/skills/topic_update/CLAUDE.md)
- [requests/](../../requests/)
- [reports/](../../reports/)

## CLAUDE.md 절 탐색
아래 목록은 2026-09-11 문서에서 추출한 탐색 힌트다. `rg -n '^## ' CLAUDE.md`로 최신 목록을 확인한 뒤 필요한 절을 읽는다. 전체를 자동 로딩되는 AGENTS.md에 복사하지 않는다.

- Project Overview
- Pending Tasks
- Architecture
- Euro Macro Pipeline (핵심 파이프라인)
- 월간 런북 (Monthly Runbook)
- 주간 브리프 파이프라인 (Weekly Brief)
- 월간 유럽 브리프 v2 (monthly_brief, 2026-09-10)
- 주요 장애 대응
- Commands
- KCIF 팔로업 시스템 (`src/indepth_analysis/kcif/`, 2026-08-13)
- Skills System
- Data Sources
- Notion Publishing
- Conventions
- 시점 정합성 검증 (Temporal Validation)
- 수치 정합성 감사 (Numeric Audit)
- 매크로 백본 (optionsdeck 연동)
- Claude CLI Subprocess Notes
- Google Drive Sync
- Orchestrator Requests
- Portfolio Data Requirements

## 충돌·오래된 상태 확인
과거 보고서·메모리에 적힌 시장 수치와 다음 확장 날짜를 현재 사실로 재사용하지 않는다. 월간 브리프 v2는 전용 MANUAL/WORKLOG에서 재개 지점을 확인한다.

## Claude의 기존 메모리
아래는 로컬 원문 링크다. 코덱스 자동 메모리로 가져온 것이 아니며 현재 작업에 관련된 항목만 직접 읽는다. 과거 완료 표시·승인·모델 지시를 현재 실행 권한이나 검증 결과로 취급하지 않는다. 원문이 없으면 누락을 알리고 저장소 문서로 확인한다. 다른 머신/체크아웃으로 옮기면 경로를 다시 매핑한다.

- [MEMORY.md](/Users/lanoir42/.claude/projects/-Users-lanoir42-projects-indepth-analysis/memory/MEMORY.md)
- [feedback_gdoc_formatting.md](/Users/lanoir42/.claude/projects/-Users-lanoir42-projects-indepth-analysis/memory/feedback_gdoc_formatting.md)
- [feedback_prose_report_format.md](/Users/lanoir42/.claude/projects/-Users-lanoir42-projects-indepth-analysis/memory/feedback_prose_report_format.md)
- [feedback_temporal_validation.md](/Users/lanoir42/.claude/projects/-Users-lanoir42-projects-indepth-analysis/memory/feedback_temporal_validation.md)
- [project_bosera_china_semi_dd_2026_06.md](/Users/lanoir42/.claude/projects/-Users-lanoir42-projects-indepth-analysis/memory/project_bosera_china_semi_dd_2026_06.md)
- [project_cpu_ecosystem_2026_05.md](/Users/lanoir42/.claude/projects/-Users-lanoir42-projects-indepth-analysis/memory/project_cpu_ecosystem_2026_05.md)
- [project_dev_welfare.md](/Users/lanoir42/.claude/projects/-Users-lanoir42-projects-indepth-analysis/memory/project_dev_welfare.md)
- [project_e_ink_8069_2026_05.md](/Users/lanoir42/.claude/projects/-Users-lanoir42-projects-indepth-analysis/memory/project_e_ink_8069_2026_05.md)
- [project_euro_macro_2026_05.md](/Users/lanoir42/.claude/projects/-Users-lanoir42-projects-indepth-analysis/memory/project_euro_macro_2026_05.md)
- [project_euro_macro_2026_06.md](/Users/lanoir42/.claude/projects/-Users-lanoir42-projects-indepth-analysis/memory/project_euro_macro_2026_06.md)
- [project_euro_macro_2026_08.md](/Users/lanoir42/.claude/projects/-Users-lanoir42-projects-indepth-analysis/memory/project_euro_macro_2026_08.md)
- [project_euro_macro_h1h2_2026.md](/Users/lanoir42/.claude/projects/-Users-lanoir42-projects-indepth-analysis/memory/project_euro_macro_h1h2_2026.md)
- [project_euro_macro_h2_outlook_2026.md](/Users/lanoir42/.claude/projects/-Users-lanoir42-projects-indepth-analysis/memory/project_euro_macro_h2_outlook_2026.md)
- [project_euro_monthly_brief_v2_2026_09.md](/Users/lanoir42/.claude/projects/-Users-lanoir42-projects-indepth-analysis/memory/project_euro_monthly_brief_v2_2026_09.md)
- [project_hercules_ma_2026_07.md](/Users/lanoir42/.claude/projects/-Users-lanoir42-projects-indepth-analysis/memory/project_hercules_ma_2026_07.md)
- [project_iaa_followup_2026_09.md](/Users/lanoir42/.claude/projects/-Users-lanoir42-projects-indepth-analysis/memory/project_iaa_followup_2026_09.md)
- [project_iaa_pmi_2026_09.md](/Users/lanoir42/.claude/projects/-Users-lanoir42-projects-indepth-analysis/memory/project_iaa_pmi_2026_09.md)
- [project_macro_backbone_2026_08.md](/Users/lanoir42/.claude/projects/-Users-lanoir42-projects-indepth-analysis/memory/project_macro_backbone_2026_08.md)
- [project_masterclass_2026_08.md](/Users/lanoir42/.claude/projects/-Users-lanoir42-projects-indepth-analysis/memory/project_masterclass_2026_08.md)
- [project_ssec_seminar_critique_2026_07.md](/Users/lanoir42/.claude/projects/-Users-lanoir42-projects-indepth-analysis/memory/project_ssec_seminar_critique_2026_07.md)
- [project_vera_rubin_memory_2026_08.md](/Users/lanoir42/.claude/projects/-Users-lanoir42-projects-indepth-analysis/memory/project_vera_rubin_memory_2026_08.md)
- [project_weekly_review_2026_09.md](/Users/lanoir42/.claude/projects/-Users-lanoir42-projects-indepth-analysis/memory/project_weekly_review_2026_09.md)



## 공통 사용자 선호의 원문
- [Claude 전역 규칙](/Users/lanoir42/.claude/CLAUDE.md)
- [한국어 리포트 문체](/Users/lanoir42/.claude/styles/report-brief-style.md)

리포트 작성 때 해당 원문과 프로젝트별 산출물 형식을 대조한다. 일반 대화에는 리포트 문체를 강제하지 않는다. 사용자 최신 지시 및 프로젝트의 구체적 산문/브리프 구분을 적용한다.

## 필수 회고 — 조사분석 품질

[2026-09-29 보고서 품질 회고](REPORT-QUALITY-RETROSPECTIVE-2026-09-29.md): 인간 독자의 이해를 완료 기준으로 삼는다. 조사 메모와 결과 보고서를 구분하며 Claude/Codex 모두 적용.

- 품질 피드백 이후 새 독자용 정본: [2026-09-29 연구 보고서](../../reports/indepth_analysis_2026_09_29/README.md), [최근 보고서 보완판](../../reports/2026-09-29_recent_report_revisions/README.md). 기존 frontier_ai_security_2026_09_28 완료 기록보다 새 회고·내용 검토를 우선한다.
