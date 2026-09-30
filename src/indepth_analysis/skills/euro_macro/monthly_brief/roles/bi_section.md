# BI 섹션 서술 — `sections/<GROUP>.md`의 `<!-- NARRATIVE -->` 대체 (Opus, medium)

그룹 하나당 에이전트 하나. 워크플로가 `GROUP=`(ECB·EA_MACRO·DE·FR·IT·ES·UK·EU_POLICY·ENERGY_EXTERNAL·GLOBAL 중 하나)을 넘긴다.

## 입력
- `_common.md`, `PKG/STYLE_BRIEF.md`
- `sections/<GROUP>.md` (결정론 스캐폴드: 문서 목록·카드 요지·핵심 수치 표, 끝에 `<!-- NARRATIVE -->`)
- 스캐폴드에 열거된 문서의 카드 JSON(`/Users/lanoir42/projects/indepth_analysis/references/mendeley_europe/cards/<sha16>.json`) — `summary_ko`·`key_numbers`·`claims`·`forecasts`·`politics`
- 필요 시 원문 텍스트(`references/mendeley_europe/<YYYYMM>/*.md`)의 해당 문서
- 대조용 실측: `data/facts.md`, 관련 리서치 축(`research/R*.md` — 그룹↔축: ECB→R01, EA_MACRO→R02·R03·R05, DE→R07·R03, FR→R06, IT·ES→R08, UK→R11, EU_POLICY→R09, ENERGY_EXTERNAL→R10, GLOBAL→R04·R10). 리서치가 아직 없으면 facts.md만으로 대조.

## 산출
- 같은 파일 `sections/<GROUP>.md`에서 `<!-- NARRATIVE -->` 한 줄을 아래 블록으로 **교체**(스캐폴드 나머지는 그대로 둔다). 자리표시자가 이미 없으면 파일 끝 `## BI 논지 종합` 절을 갱신한다.

```markdown
## BI 논지 종합

**[판단]** (이 그룹에 대해 BI가 대상 기간에 일관되게 주장한 것 1~2문장. 논지의 축은 ▲… ▲… ▲…)

- **(논지 1 라벨)** BI가 무엇을, 어떤 근거로 주장했는지 2~3문장. 문서 제목·발행일 병기.
  - 근거 수치(지표·기간·값)
- **(논지 2 …)** …
- **(시간에 따른 변화)** 월 초와 월 말 BI 시각이 달라졌다면 무엇이 바뀌었는지

### 핵심 수치
| 지표 | 값 | 기간 | 종류(실측·전망·컨센서스) | BI 문서(발행일) |
|---|---|---|---|---|

### 다른 근거와 어긋나는 지점
- **(쟁점)** BI 주장 vs 1차 실측·다른 기관 — 어느 쪽 근거가 강한지와 이유. 판단 유보면 판단을 가를 지표·날짜.
```

## 품질 기준
- 카드 요지를 옮겨 적는 목록이 아니라 **그룹 차원의 종합**(여러 문서가 같은 결론을 가리키는지, 서로 다른지).
- 불릿 4~8개, 2~3문장씩. 수치는 카드·원문에 있는 값만, 기간·문서 날짜 병기.
- 문서 sha·카드 파일명을 본문에 쓰지 않는다. 문서는 제목(한국어 요지)·발행일로 지칭.
- 조각 문서(`fragment`)·중복(`dup_of`) 문서는 근거로 이중 계산하지 않는다.
- 금지 토큰(_common 5절) 0건.

## 반환
`{"group": "<GROUP>", "claims": N, "conflicts": N, "chars": N}`
