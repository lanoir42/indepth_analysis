# Change Review — 10장 '보고 간 판단 변화' 집필 (종합보고 전용, Opus, medium)

`PHASE=final`에서만 실행. 프리뷰·중간보고의 판단이 종합보고 시점에 어떻게 유지·수정·철회됐는지, **무엇이 판단을 바꿨는지**를 독자용으로 서술한다.

## 입력
- `_common.md`, `PKG/STYLE_BRIEF.md`, `PKG/coverage.yaml`의 `ch10_changes`
- 결정론 차이 파일 `_work/delta_diff_interim.md`(프리뷰→중간보고), `_work/delta_diff_final.md`(중간보고→종합보고) — 판단 변화의 근거 목록
- 이전 단계 최종본: 프리뷰·중간보고 리포트(ROOT에서 `*_europe_macro_preview_report.md`·`*_europe_macro_interim_report.md` glob — 보고일이 단계마다 달라 파일명 앞 날짜가 다름; 워크플로가 경로를 넘기면 그것 우선), `02_advisor_preview.md`·`02_advisor_interim.md`
- 종합보고 `02_advisor_final.md`, `data/NUMBERS.md`, 최신 리서치(`research/*_final.md`, `*_interim.md`)

## 산출
- `drafts/final_report_ch10_changes_r1.md`, 첫 줄 `<!-- chapter: ch10_changes | chars: N -->`

## 형식
```
## 10. 보고 간 판단 변화

**[판단]** 세 차례 보고를 거치며 유지된 판단과 바뀐 판단의 요지 2~3문장. 변화는 ▲… ▲…에서 비롯

### 10-1. 유지된 판단
- **(판단 요지)** 프리뷰(보고일)의 판단 → 이후 확인된 지표·사건(수치·날짜) → 판단이 유지된 이유
### 10-2. 수정·철회된 판단
- **(판단 요지)** 당시 판단과 근거 → 바뀐 지표·사건(수치·날짜) → 새 판단과 그 논리. 당시 근거가 틀렸는지, 새 정보가 추가됐는지 구분
### 10-3. 예상과 실제
- **(지표·이벤트)** 당시 예상 범위 vs 실제 발표(수치·날짜) → 차이의 원인
### 10-4. 다음 달 판단에 남기는 신호
```

## 품질 기준
- 독자용 서술만. 적중률·건수·점수 같은 **채점 통계, 단계명(preview/interim 영문), 수정 ID, 파이프라인 용어 금지** — 통계는 editorial 몫. 보고 지칭은 `10/5 프리뷰 보고`, `10/12 중간보고`처럼 한국어+날짜로.
- 판단마다 "무엇이 판단을 바꿨는가"가 수치·날짜로 드러나야 한다.
- delta_diff 파일에 없는 변화를 만들어내지 않는다. 반대로 delta_diff의 중요한 변화(요약 판단·시나리오 확률·핵심 수치)는 빠짐없이 다룬다.
- 목표 4,000자 ±15%. 금지 토큰 0(저장 전 grep).

## 반환
`{"chars": N, "held": n, "revised": n, "withdrawn": n, "expected_vs_actual": n}`
