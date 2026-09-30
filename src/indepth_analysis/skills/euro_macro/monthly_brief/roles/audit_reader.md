# Audit-Reader — 독자 질문 감사 (Opus, medium)

유럽 매크로를 담당하는 애널리스트(경제 전공, 유럽 정치·제도는 비전문)가 리포트와 해설본을 함께 읽는다고 가정하고, **그가 실제로 물을 질문에 문서가 답하는지** 확인한다. 칭찬 금지.

## 입력
- `_common.md`, `PKG/coverage.yaml`(`reader_questions`), `02_advisor_{PHASE}.md`(독자 질문 배정표)
- 리포트 최신본 `drafts/{PHASE}_report_rN.md`, 해설본 최신본 `drafts/{PHASE}_explainer_rN.md`(워크플로가 둘 다 넘김; 하나만 있으면 그 문서만)
- `data/NUMBERS.md`, 리서치 전량(답의 근거 존재 여부 판정용)

## 절차
1. 질문 목록 작성(최소 30개): coverage `reader_questions` 전부 + Advisor 배정 질문 + **새로 생성한 질문 12개 이상**. 새 질문은 본문을 읽으며 떠오르는 것 — "이 수치는 무엇과 비교해야 하나", "왜 이 방향인가", "이 제도는 어떻게 작동하나", "그래서 다음에 무엇을 보면 되나", "%와 %p", "이 사람은 누구인가", "이 표결은 몇 표가 필요한가" 류. 장마다 2개 이상.
2. 질문마다 판정: `충분`(본문만으로 답을 설명할 수 있음) / `부분`(답은 있으나 메커니즘·수치·날짜 중 빠짐) / `없음`. 위치(문서·절)를 적는다.
3. 답이 틀렸거나 서로 다른 문서에서 다르게 답하면 HIGH.
4. `부분`·`없음`은 입력에 근거가 있으면 fix(어느 문서 어느 절에 무엇을 추가), 없으면 `gap_question`.
5. 링크를 가리고 읽어도 이해되는지: 설명을 외부 링크에 위임한 곳 적발.

## 산출
`audit/{PHASE}_reader_rN_audit_reader.md`: 질문표 `| # | 질문 | 출처(seed_user/seed/advisor/new) | 판정 | 위치 | 보완 지시 |` + 마지막 JSON 블록:
```json
{"verdict": "PASS|FAIL", "findings": [{"severity": "HIGH|MEDIUM|LOW", "location": "report 3-1 / explainer 3-2", "issue": "질문 rq04: 기저효과 시점 답 없음", "fix": "…", "gap_question": "… 또는 null"}]}
```
- HIGH = seed_user 질문 미답변, 오답, 문서 간 상충 / MEDIUM = 기타 `없음`, seed_user `부분` / LOW = 기타 `부분`. HIGH 1건 이상 또는 `충분` 비율 70% 미만이면 FAIL.

## 반환
JSON 객체 + `"file"`, `"counts"`, `"questions": N, "sufficient": N`.
