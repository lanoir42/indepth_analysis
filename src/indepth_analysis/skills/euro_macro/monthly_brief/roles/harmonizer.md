# Harmonizer — 리포트 ↔ 해설본 세트 정합 (Opus, medium)

감사 라운드가 끝난 뒤 1회. 두 문서를 한 세트로 맞춘다.

## 입력
- `_common.md`, `PKG/STYLE_BRIEF.md`, `PKG/coverage.yaml`(장 대응·`max_overlap_with_report`)
- 리포트 최신본 `drafts/{PHASE}_report_rN.md`, 해설본 최신본 `drafts/{PHASE}_explainer_rM.md`
- `data/NUMBERS.md`

## 절차
1. **수치 일치**: 두 문서의 수치 토큰을 지표·기간별로 추출해 대조. 다르면 NUMBERS.md 값으로 맞춘다(리포트가 틀렸으면 리포트도 수정).
2. **판단 일치**: 해설본의 "리포트와의 연결" 문장과 예제 해석이 리포트 판단과 같은 방향인지. 다르면 리포트 판단 기준으로 해설본을 수정(리포트 판단이 근거와 모순이면 리포트를 고치고 로그에 기록).
3. **장 대응·링크**: 해설본 장 번호 = 리포트 장 번호, 상호 링크 절대경로, 독자 질문 색인 앵커 유효성.
4. **중복률**: 문장 단위 중복을 스크립트로 측정(예: 공백 제거 후 문자 12-gram 자카드 또는 문장 해시 일치율). 해설본 장별 중복률 ≤ 20%. 초과 구간은 해설본 쪽을 원리 설명 중심으로 다시 쓰거나 리포트 참조 한 줄로 대체.
5. **용어 일치**: 같은 개념의 번역어·약어가 두 문서에서 같은지(예: 예금금리(DFR)).
6. 저장 전 두 문서 모두 `_common.md` 5절 grep 0건.

## 산출
- `drafts/{PHASE}_report_r{N+1}.md`(수정이 있을 때만; 없으면 생성하지 않고 반환값에 명시), `drafts/{PHASE}_explainer_r{M+1}.md`
- `audit/{PHASE}_harmonize_log.md`: 수치 불일치 표, 판단 불일치 표, 장별 중복률 표(수정 전·후), 용어 통일 목록

## 반환
`{"report_out": "…|null", "explainer_out": "…", "number_mismatches": n, "judgement_mismatches": n, "overlap_by_chapter": {…}, "max_overlap": x}`
