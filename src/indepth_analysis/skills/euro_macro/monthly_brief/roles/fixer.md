# Fixer — 감사·보충 리서치 반영 수정본 (Opus; 리포트 ch02·ch06·ch09 대규모 재집필이 걸리면 high, 그 외 medium)

`IN=drafts/{PHASE}_{report|explainer}_rN.md` → `OUT=drafts/{PHASE}_{report|explainer}_r{N+1}.md`. 워크플로가 이번 라운드 감사 파일 목록과 보충 리서치 파일 목록을 넘긴다.

## 입력
- `_common.md`, `PKG/STYLE_BRIEF.md`, `PKG/coverage.yaml`
- `IN` 문서, 감사 파일 `audit/{IN stem}_audit_{fact,logic,style,coverage}.md`, 독자 질문 감사 `audit/{PHASE}_reader_rN_audit_reader.md`(있으면)
- 보충 리서치 `research/G_<ROUND>_*.md`(이번 라운드 gaps에 대한 답)
- `data/NUMBERS.md`, 관련 리서치, `02_advisor_{PHASE}.md`

## 절차
1. 모든 감사 JSON 블록의 findings를 모아 하나의 처리표를 만든다(중복 병합). 처리 순서: fact HIGH → logic HIGH → coverage HIGH → reader HIGH → style HIGH → MEDIUM → LOW.
2. HIGH·MEDIUM은 전건 반영. LOW는 반영 권장. 반영하지 않는 지적은 근거(파일·key·URL)와 함께 기각 사유를 fix_log에.
3. 보충 리서치 반영: `판정: 답변|부분`이면 해당 위치에 수치·사실·인용을 넣고 출처 표기. `미공개`면 본문에 공개 예정일·대체 근거·결론 영향 한 문장(거부 문장 형태 금지)으로 쓰거나, 결론에 영향이 없으면 본문에서 빼고 fix_log에 "editorial 이관"으로 기록.
4. 수치 수정은 NUMBERS.md·코드 산출·1차 리서치 값만. 새 수치가 필요하면 보충 리서치 결과에 있는 값만 쓰고, 없으면 다음 라운드 gaps 파일에 추가.
5. 커버리지 보강은 입력 근거가 있을 때 장 구조(STYLE_BRIEF 4단 계층)에 맞춰 추가. 추가로 분량이 목표를 크게 넘으면 같은 장의 중복·장식 서술을 줄인다.
6. 문체 수정은 표현만(수치·판단 보존). 수정 후 수치 토큰 전후 대조 스크립트를 돌려 의도하지 않은 수치 변경 0건 확인.
7. 저장 전 `_common.md` 5절 grep — 금지 토큰·거부 문장 0건. **수정 과정에서 금지 토큰을 새로 넣지 않는다**(예: "감사 지적에 따라" 같은 문구 금지).

## 산출
- `OUT` 문서 (첫 줄 주석은 `<!-- rev: r{N+1} | chars: N -->`로 갱신, 본문에 수정 이력 표기 금지)
- `audit/{OUT stem}_fix_log.md`: `| # | 감사 종류 | 심각도 | 위치 | 조치(반영/부분/기각/editorial 이관) | 내용·근거 |` + 수치 토큰 대조 결과 + grep 결과
- 다음 라운드 gaps(해결 못 한 질문)는 gaps 파일에(_common 4절)

## 반환
`{"out": "…", "applied": {"HIGH": n, "MEDIUM": n, "LOW": n}, "rejected": n, "editorial": n, "new_gaps": n, "banned_tokens": 0, "chars": N}`
