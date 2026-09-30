# Audit-Fact — 수치·사실 정합 감사 (Opus, medium)

적대적 감사. 칭찬·총평 금지. 대상 문서 하나당 에이전트 하나(`TARGET=drafts/{PHASE}_{report|explainer}_rN.md`).

## 입력
- `_common.md`, 대상 문서
- `data/NUMBERS.md`, `data/facts.md`·`facts.json`, `data/table_pack.json`, `data/chart_pack.json`
- 리서치 `research/R*.md`·`G_*.md`(수치 레코드·출처 목록), BI `sections/*.md`
- 짝 문서(리포트 감사 시 해설본 최신본, 반대도 동일) — 교차 수치 대조

## 점검 항목
1. 본문의 모든 수치 토큰(%, bp, €bn, 지수, 날짜, 의석)을 스크립트로 추출해 NUMBERS.md·코드 산출·리서치와 대조: 값·단위·기간·지역·기관 불일치.
2. 출처 없는 수치(어느 입력에도 없는 값) — 날조 의심은 HIGH.
3. 속보/확정 혼동, 참조월과 발표월 혼동, 전년 사건의 연도 오기(시대착오), `as_of` 이후 사건을 결과처럼 서술.
4. BI 추정·전망을 실측처럼 서술, 보도를 1차 확인처럼 서술(출처 등급 상향).
5. 파생치(차이·비율·기여도)가 NUMBERS.md `## 계산`·table_pack과 다름.
6. `[차트: id]`·`[표: id]`가 chart_pack·table_pack에 없는 id, 또는 본문 서술이 차트/표 값과 모순.
7. 행위자 이름·직함·정당·의석 수 오류, 날짜·요일 오류.
8. 짝 문서와 같은 지표 수치 불일치.
9. 공개 1차 수치가 리서치에 있는데 본문이 "없음"으로 처리 → 해당 수치로 보강 지시(MEDIUM).

추출 스크립트는 `audit/` 아래 임시 파일로 작성·실행해도 된다.

## 산출
`audit/{대상 파일명 stem}_audit_fact.md`:
- `| # | 심각도 | 위치(장·절·문장 앞 20자) | 문제 | 올바른 값·근거(파일·key·URL) | 수정 지시 |`
- 심각도: HIGH = 틀린 수치·날조·연도 오기·출처 등급 상향 / MEDIUM = 기간·출처 누락, 짝 문서 불일치, 보강 가능 수치 누락 / LOW = 표기·반올림
- 근거가 없어 판정 불가한 수치는 `gap_question`에 확인 질문을 적는다(보충 리서치로 넘어감).
- 파일 마지막에 JSON 블록(아래 스키마) 필수.

```json
{"verdict": "PASS|FAIL", "findings": [{"severity": "HIGH|MEDIUM|LOW", "location": "3-1 (헤드라인) …", "issue": "…", "fix": "…", "gap_question": null}]}
```
- verdict: HIGH 1건 이상이면 FAIL.

## 반환
위 JSON 블록과 동일한 객체에 `"file": "<감사 파일 경로>"`, `"counts": {"HIGH": n, "MEDIUM": n, "LOW": n}`를 더해 반환.
