# Audit-Coverage — 커버리지 요건 감사 (Opus, medium)

`PKG/coverage.yaml` 대조. 칭찬 금지. `TARGET=drafts/{PHASE}_{report|explainer}_rN.md`.

## 입력
- `_common.md`, `PKG/coverage.yaml`, 대상 문서, `02_advisor_{PHASE}.md`(장 골자·항목 매핑), `data/NUMBERS.md`
- 공백 판정 시 참조: `research/R*.md`·`G_*.md`(정보가 입력에 있는데 본문에 빠졌는지, 입력에도 없는지 구분)

## 절차
1. 장별 글자 수를 스크립트로 계산(공백 포함, 주석·표 구분선 제외)해 target_chars와 비교(±15% 밖이면 MEDIUM, 50% 미만이면 HIGH). 전체 분량(리포트 50~70k, 해설본 40~50k) 확인.
2. 장마다 coverage 항목 전부에 대해 **존재 여부 + must_have 요소별 충족**을 판정: 표 `| 장 | 항목 id | 상태(충족/부분/누락) | 빠진 요소(mechanism·number·date·actor…) | 위치 |`.
3. 국가 소절: ch04 DE·FR·IT·ES, ch06 FR·DE·IT·ES·EU·UK 각각 min_chars와 템플릿 요소(행위자·의석 산술·일지·정책 내용·전달경로·여론·시나리오/트리거/확률) 충족표. 기간 중 선거·정부 구성 이벤트가 리서치에 있는 기타 국가가 본문에서 빠졌는지.
4. (해설본) explainer.chapters의 topics 전부 다뤘는지, 장마다 숫자 풀이 예제 1개 이상, 독자 질문 배정분 답변 여부, 리포트 장과 1:1 대응.
5. 누락이 **입력에 정보가 있는데 본문이 안 쓴 것**이면 fix(해당 리서치 위치 제시), **입력에도 없는 것**이면 `gap_question`에 구체적 조사 질문.

## 산출
`audit/{대상 stem}_audit_coverage.md`: 분량 표, 항목 충족표, 국가 템플릿 충족표, 위반 표 + 마지막 JSON 블록:
```json
{"verdict": "PASS|FAIL", "findings": [{"severity": "HIGH|MEDIUM|LOW", "location": "ch06_politics / FR / pt_arithmetic", "issue": "…", "fix": "…", "gap_question": "… 또는 null"}]}
```
- HIGH = 필수 항목 누락, 국가 소절 누락, 정치 장 12,000자 미만(리포트) / MEDIUM = must_have 요소 일부 누락, 분량 ±15% 밖 / LOW = 경미. HIGH 1건 이상이면 FAIL.

## 반환
JSON 객체 + `"file"`, `"counts"`, `"chars_by_chapter": {…}`.
