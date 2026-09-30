# Polish — 리포트 통합·요약·부록 (Opus, medium)

## 입력
- `_common.md`, `PKG/STYLE_BRIEF.md`, `PKG/coverage.yaml`
- `02_advisor_{PHASE}.md`(요약 판단·장 순서), `data/NUMBERS.md`
- 장 초안 전부 `drafts/{PHASE}_report_*_r1.md` (SUBSECTION 파일은 장 안에 국가 순서 FR·DE·IT·ES·EU·UK·기타로 병합)
- PHASE=final: `drafts/final_report_ch10_changes_r1.md`(change_review 산출)
- 부록 원천: `data/tables.md`(있으면) 또는 `data/table_pack.json`의 지표 실적·향후 일정 표, 부족분은 `research/R12_calendar_consensus*.md`
- 참고문헌 원천: 리서치 파일의 `## 출처 목록`, BI 문서 목록(`documents/doc_cards.md` — 제목·발행일·PDF 경로)

## 산출 `drafts/{PHASE}_report_r1.md`

```
# {phase_tag} {월 라벨} 유럽 거시경제 월간 리포트 ({report_date})

기준일 {as_of} · 대상 기간 {window.from}~{window.to} · 보고일 {report_date} · [해설본](<해설본 절대경로>)

## 목차
- [요약](#요약) … (장·부록 앵커 링크)

## 요약
## 1. 이달의 판단
… (장 2~9, final이면 10)
## 부록 A. 지표 실적 (최근 4주)
## 부록 B. 향후 일정 (다음 30일)
## 부록 C. 참고문헌
```

- 해설본 절대경로: `/Users/lanoir42/projects/indepth_analysis/<ROOT 상대 저장소 경로>/{report_date}_europe_macro_{PHASE}_explainer.md` (edition의 `doc_name` 규칙). 파일이 아직 없어도 이 경로로 쓴다.
- **요약**: `**[판단]**` 2문장 + `▲` 판단 불릿 5~7개(불릿당 2~3문장, 수치 2~3개 이하, 각 불릿 끝에 연결 장 번호 `(→ 3장)`). 인식과 실측의 괴리 1개 이상, 관전 일정 3~5개(날짜).
- **장 통합**: 장 번호·절 번호 정리, 장 간 중복 서술 제거(한 사실은 주 장에서 자세히, 다른 장은 한 줄 참조), 같은 지표 수치가 장마다 같은지 대조, 용어 첫 등장 주석은 첫 장에만.
- **부록 A**: 지표 실적 표(발표일·국가·지표(참조기간)·실제·예상·이전·판정 >e/<e/=e·출처) + 표 앞 2~3문장(무엇이 예상을 상회·하회했는지).
- **부록 B**: 향후 30일 일정(날짜·시간 CET/KST·국가·이벤트·컨센서스·중요도) — 경제지표·ECB·정치·등급 평가 포함.
- **부록 C 참고문헌**: `| # | 제목 | 기관 | 날짜 | URL 또는 경로 |`. BI 문서는 PDF 절대경로. 본문에 인용된 1차 출처는 빠짐없이.

## 품질 기준
- 장 본문의 수치·판단을 바꾸지 않는다(표현·중복·순서만). 장 간 모순을 발견하면 NUMBERS.md 기준으로 맞추고 반환값에 기록.
- 본문 분량(요약~마지막 장, 부록 제외) 50,000~70,000자. 초과 시 중복 삭제, 미달 시 반환값에 부족 장 명시(새 내용 창작 금지).
- 메타 블록·서론에 방법·팀·입력 소스·검증 설명을 쓰지 않는다(→ editorial).
- 금지 토큰 0(_common 5절 grep, 부록 C 표는 예외).

## 반환
목차(장·절), 본문 글자 수(장별), 부록 행 수, 장 간 모순과 처리, 금지 토큰 grep 결과.
