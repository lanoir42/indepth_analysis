# Explainer Polish — 해설본 통합·용어사전 (Opus, medium)

## 입력
- `_common.md`, `PKG/STYLE_BRIEF.md`(7절), `PKG/coverage.yaml`(`explainer`, `reader_questions`)
- 해설본 장 초안 전부 `drafts/{PHASE}_explainer_ex*_r1.md`
- 최신 리포트 통합본 `drafts/{PHASE}_report_rN.md`(장 번호·앵커 대응용), `data/NUMBERS.md`
- `02_advisor_{PHASE}.md` 독자 질문 배정표

## 산출 `drafts/{PHASE}_explainer_r1.md`

```
# {phase_tag} {월 라벨} 유럽 거시경제 월간 해설 ({report_date})

기준일 {as_of} · 대상 기간 {window.from}~{window.to} · [리포트](<리포트 절대경로>)

## 목차
## 이 해설의 구성
## 1. … (ex01~ex09, final이면 ex10 — 리포트 장 번호와 동일 번호)
## 독자 질문 색인
## 용어사전
```

- 리포트 절대경로: `/Users/lanoir42/projects/indepth_analysis/<ROOT 저장소 경로>/{report_date}_europe_macro_{PHASE}_report.md`.
- **이 해설의 구성**: 3~5불릿. 리포트 각 장과 해설 장의 대응, 읽는 순서 제안. 작성 방법·팀·검증은 쓰지 않는다.
- **독자 질문 색인**: `| 질문 | 답이 있는 해설 절(앵커 링크) | 관련 리포트 장 |` — 배정된 질문 전부(15개 이상).
- **용어사전**: 40~70개. `| 용어 | 뜻(2~3문장) | 이번 호 관련 수치 |`. 본문에서 처음 주석한 용어는 전부 포함. 가나다순 또는 분야별.
- 장 간 중복 설명 제거(한 개념은 한 곳에서 자세히, 다른 곳은 앵커 참조), 번호·앵커 정리, 수치 일관성 대조(NUMBERS.md).

## 품질 기준
- 본문(목차·색인·용어사전 제외) 40,000~50,000자.
- 장 초안의 설명·수치를 임의로 바꾸지 않는다. 모순은 NUMBERS.md 기준으로 맞추고 반환값에 기록.
- 금지 토큰 0(_common 5절 grep).

## 반환
목차, 장별 글자 수, 용어 수, 독자 질문 수, 모순 처리 내역.
