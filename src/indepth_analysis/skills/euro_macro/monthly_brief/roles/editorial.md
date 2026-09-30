# Editorial — 편집 기록 `_editorial/{PHASE}_editorial.md` (Opus, medium)

독자용 본문에서 분리된 작업 기록. 방법·출처·검증·잔존 공백을 한 곳에 모은다. 이 문서는 금지 토큰 규칙의 예외(파이프라인 용어 허용)지만 문체는 STYLE_BRIEF 개조식을 따른다.

## 입력
- `edition.json`, `02_advisor_{PHASE}.md`, `data/NUMBERS.md`, `data/validation.json`
- 리서치 로그 `_work/logs/*.err`·`*.complete.json`(성공·실패·재시도), 리서치 파일 목록
- gaps 파일 전부 `_work/gaps_*.json`, `_work/gaps/*.json`, 보충 리서치 `research/G_*.md`
- 감사 파일 `audit/{PHASE}_*_audit_*.md`, fix_log, `audit/{PHASE}_harmonize_log.md`, 결정론 게이트 결과(워크플로가 경로를 넘기면)
- 최종 리포트·해설본(워크플로가 넘긴 최종 rN)
- PHASE=final: `_work/delta_diff_*.md`, 이전 단계 editorial

## 산출 `_editorial/{PHASE}_editorial.md`
1. **회차 정보**: 월·단계·as_of·보고일·대상 기간·최종 문서 경로(절대경로)·글자 수
2. **방법**: 입력 계층(코드 산출·리서치 축·BI 문서 수·주간 덱), 역할 구성과 모델·effort, 감사 라운드 수
3. **사용 출처 요약**: 1차 기관별 인용 수, 리서치 축별 산출 상태(성공·실패·보충), BI 문서 수(카드 완료·중복·조각)
4. **데이터 품질**: validation.json 상태·WARN/FAIL 항목, NUMBERS.md 충돌 해소 목록, llm_web 등급 수치와 교차 검증 결과
5. **잔존 공백**: `| 질문 | 조사 경과(라운드·결과) | 판정(미공개/미해결) | 공개 예정일 | 결론에 미치는 영향 | 본문 처리 |` — 본문에서 뺀 항목과 대체 근거 서술 위치
6. **BI 주장 검증**: 리서치 `## BI 주장 검증` 표 통합(지지/반박/부분/미결 건수와 주요 사례)
7. **검증 요약**: 라운드별 감사 verdict·HIGH/MEDIUM/LOW 건수, 반영·기각 수, 세트 정합(수치 불일치·중복률), 게이트 결과(금지 토큰·상대 날짜·lint-temporal·lint-numeric)
8. (final) **판단 채점 통계**: 프리뷰·중간보고 판단의 유지/수정/철회 건수, 예상 대비 실제 적중 통계 — 본문 10장에는 싣지 않는 수치
9. **다음 회차 개선 메모**: 이번 회차에서 반복된 결함·프롬프트/역할 개선 제안 3~7개

## 품질 기준
- 사실만. 과장·자평 금지(예: "완벽히 검증" 금지 — 무엇을 어떤 방법으로 확인했는지를 쓴다).
- 공백의 영향은 구체적으로(어느 장·어느 판단의 신뢰도가 어떻게 달라지는지).

## 반환
`{"file": "…", "open_gaps": n, "unpublished": n, "audit_rounds": n, "final_verdicts": {…}}`
