# 조사 검토 기록

2026-09-29. 사용자 요청: OpenShell·Sentry의 깊은 기술 분석과 별도 해설서. 결과는 reports/nvidia_agent_safety_2026_09/README.md 참조. 기존 보고서 및 사용자 변경 보존.

v0.1.2 model.rs·queries.rs·prover README 및 gateway policy.rs의 입력 구성·finding_delta·자동승인 연결 함수를 정적 검토. gateway 전체 소스 감사 아님. 공개 원문과 LICENSE를 이 폴더에 보존하고 evidence/validation.json에 해시 기록. containment 하위 파일 두 경로는 HTTP 오류로 미확보; API 계약은 README 근거.

핵심 구분: Sentry 참조 설계와 전체 오픈소스 범위, 문서 배치 설명의 불일치, legacy proposal-risk와 containment, 모델의 scope 표현과 gateway의 실제 입력, 위험 delta와 절대 안전성, 모델 차단과 전체 실행 중단. SAT 외 결과 처리 관찰은 재현/도달 가능성 미검증이므로 취약점으로 판정하지 않음.

검증: 두 문서 temporal clean; numeric clean은 거시지표 검사 범위에 한정. 내부 링크·계산·분량·해시 확인. Briefing Finder 등록 및 두 문서 전문 일치 확인.

미실시: 독립 성능·침투 시험, 전체 코드 감사, Sentry 내부 구현 확인, 실기 UI, Notion 게시, 유료 CLI LLM, 제품 설치, 서버 재시작, git push.
