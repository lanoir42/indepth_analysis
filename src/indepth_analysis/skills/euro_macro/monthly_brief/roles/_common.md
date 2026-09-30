# 공통 규약 — 유럽 매크로 월간 리포트 v3 (전 역할 필독)

워크플로가 각 에이전트에 넘기는 값: `ROOT=<회차 루트 절대경로>`, `PHASE=preview|interim|final`, 역할별 입력·산출 경로, (해당 시) `CHAPTER=`, `SUBSECTION=`, `ROUND=`, `GAPS=`. 아래 경로는 별도 표시가 없으면 **ROOT 기준 상대경로**.

- 패키지 경로 `PKG=/Users/lanoir42/projects/indepth_analysis/src/indepth_analysis/skills/euro_macro/monthly_brief`
- 문체 사양 `PKG/STYLE_BRIEF.md` (독자용 본문을 쓰거나 고치는 역할은 집필 전 필독)
- 커버리지 요건 `PKG/coverage.yaml` (장 키·목표 분량·필수 항목·독자 질문·해설본 장 대응)
- 문체 실물 예시 `/Users/lanoir42/projects/indepth_analysis/references/KCIF_md/2026-09-09_37495_최근_엔화_강세_배경_및_전망.md`

## 1. 회차 변수 (`edition.json`)

집필 전 `edition.json`을 읽고 아래 값을 쓴다. 날짜·연도를 기억이나 추측으로 채우지 않는다.

| 키 | 용도 |
|---|---|
| `month` → 월 라벨(`YYYY년 M월`) | 대상 월 |
| `phase` | 단계. H1 태그 `[Preview]`·`[Interim]`·`[Final]`, 한국어 `프리뷰`·`중간보고`·`종합보고` |
| `as_of` | 데이터 기준일. 이후 사건은 쓰지 않는다 |
| `report_date` | 보고일(H1·파일명) |
| `window.from`~`window.to` | 대상 기간 |
| `ecb.last_meeting` / `ecb.next_meeting` | 직전·다음 ECB 회의 |
| `events[]` | 등록 일정 |
| `phase_bases` | 이전 단계(interim→preview, final→interim) |
| `prior_month_root` | 전월 회차 루트(전월 판단 연속성 참고) |

- 파일 쓰기는 ROOT 안에서만. `references/`·저장소 코드·다른 회차는 읽기 전용.
- `PHASE != preview`이면 리서치 파일은 `research/<AXIS>_<phase>.md`가 최신이고, 접미 없는 파일은 이전 단계 기준. 둘 다 읽고 최신 값을 우선한다.

## 2. 입력 우선순위 (수치·사실 충돌 시 위가 이긴다)

1. **코드 산출(결정론)**: `data/facts.md`·`data/facts.json`, `data/table_pack.json`, `data/chart_pack.json`(+`data/charts/<id>.csv`), `data/tables.md`(있으면), `data/validation.json`
2. **1차 출처 리서치**: `research/R*.md`, `research/G_*.md`(보충), `research/W*.md` — [확정] 라벨·1차 기관 URL이 붙은 값
3. **BI**: `sections/<GROUP>.md`, `documents/doc_cards.md`, 카드 `/Users/lanoir42/projects/indepth_analysis/references/mendeley_europe/cards/<sha16>.json`, 원문 `/Users/lanoir42/projects/indepth_analysis/references/mendeley_europe/<YYYYMM>/`
4. **주간 덱·기타**: `research/D*.md`, `research/K0*.md`(있으면)

- 큐레이션된 수치 시트 `data/NUMBERS.md`(Quant 산출)가 있으면 집필·감사는 이것을 1순위 참조표로 쓴다. NUMBERS.md는 위 우선순위를 적용한 결과다.
- 코드 산출 값이 리서치의 1차 수치보다 **기간이 오래됐으면** 최신 1차 수치를 쓰고 기간을 명시한다(예: facts는 8월 확정까지, 리서치에 9월 속보). 같은 기간 값이 다르면 코드 값을 쓰고 NUMBERS.md의 충돌 기록을 따른다.
- BI 논지는 "BI(Bloomberg Intelligence)는 9/17 보고서에서 ~로 전망"처럼 **기관·날짜를 붙여 실측과 구분**한다. BI 추정치를 실측처럼 쓰지 않는다.

## 3. 수치 규칙

- 모든 수치에 **기간 + 출처 기관**(필요 시 발표일)이 본문에서 드러나야 한다.
- 수치를 지어내지 않는다. 표·차트 시계열을 손으로 옮기지 않는다(차트·표는 `[차트: id]`·`[표: id]` 참조).
- 리서치 파일에 있는 **공개 1차 수치는 인용할 수 있다**(출처·날짜 병기). 코드 산출에 없다는 이유로 인용을 거부하지 않는다.
- 파생 계산(차이·비율·기여도)은 코드 산출(table_pack)이 있으면 그것을, 없으면 두 인용값의 단순 차이·비율만 허용하고 산식을 NUMBERS.md에 남긴다(Quant만). 집필자는 NUMBERS.md에 없는 파생치를 새로 만들지 않고 gap으로 요청한다.

## 4. 공백 처리 — 거부 문장 금지

- 본문에 `확인되지 않아 제외`, `인용하지 않는다`, `산출하지 않는다`, `관측 대상에서 제외`, `다루지 않는다`, `자료가 없어` 류의 문장을 쓰지 않는다.
- 근거가 부족하면 **공백 항목을 gaps 파일에 추가**하고, 본문에는 현재 근거로 쓸 수 있는 만큼만 쓴다.
- gaps 파일: 워크플로가 준 `GAPS=` 경로. 없으면 `_work/gaps/{PHASE}_{역할}_{CHAPTER 또는 all}.json`. 형식은 JSON 배열(기존 내용이 있으면 이어 붙임):
  ```json
  [{"id": "{PHASE}-{역할}-{CHAPTER}-01", "question": "구체적 질문(무엇·어느 기간·어느 기관)", "context": "어느 장·어느 판단에 필요한지, 현재 근거", "chapter": "ch06_politics", "raised_by": "chief_chapter"}]
  ```
  워크플로가 이를 병합해 `_work/gaps_<round>.json`으로 보충 리서치(`research/G_<round>_<n>.md`)를 돌린다.
- 진짜 **미공개**(발표 전 지표, 비공개 회의)는 본문에 공개 예정일·대체 근거·결론 영향과 함께 한 문장으로 쓸 수 있다. 조사 부족을 미공개로 포장하지 않는다.

## 5. 문체·금지 토큰

- 독자용 본문(리포트·해설본·sections 서술)은 `PKG/STYLE_BRIEF.md`를 따른다: KCIF식 개조식(`**[판단]**` 리드 → `- **(소주제)**` 2~3문장 → 들여쓴 세부 → 인용·수치), 두괄식, 명사형·인용형 종결, 메타서술·1인칭·수사어휘·번역체·수사의문 금지, `A가 아니라 B` 문서당 3회 이하.
- **본문 금지 토큰**(결정론 게이트가 grep, 1건이라도 FAIL): `정본`, `DATAPACK`, `datapack`, `§`, `팀 Noir`, `Advisor`, `Quant`, `Chief`, `Polish`, `감사`, `채점`, `본 단계`, `본 회차`, `본 문서`, `preview`, `spot`, `review`, `interim`, `등재`, `[확정]`, `[보도]`, `[추정]`, `[시장]`, `[미확인]`, 정규식 `\b[NSDRGW]\d{1,2}\b`, `\bBI-?\d+\b`, `\b[PSR]D-\d+\b`, 문구 `확인되지 않아`, `관측 대상에서 제외`, `인용하지 않는다`, `산출하지 않는다`. 예외: `_editorial/`, `audit/`, `_work/`, 부록 참고문헌 표. 우회 표기(G7→주요 7개국 등)는 STYLE_BRIEF 6-5.
- 리서치 파일명·축 코드·카드 sha·작업 단계명을 본문에 쓰지 않는다.
- 자가 점검용 grep(집필·수정 역할은 저장 전 실행, 결과 0건 확인):
  ```bash
  python3 - "$FILE" <<'EOF'
  import re,sys
  t=open(sys.argv[1],encoding="utf-8").read()
  pats=[r"정본",r"DATAPACK|datapack",r"§",r"팀 Noir",r"\bAdvisor\b|\bQuant\b|\bChief\b|\bPolish\b",r"감사",r"채점",r"본 단계|본 회차|본 문서",r"\bpreview\b|\bspot\b|\breview\b|\binterim\b",r"등재",r"\[(확정|보도|추정|시장|미확인)\]",r"\b[NSDRGW]\d{1,2}\b",r"\bBI-?\d+\b",r"\b[PSR]D-\d+\b",r"확인되지 않아|관측 대상에서 제외|인용하지 않는다|산출하지 않는다",r"가 아니라|가 아닌"]
  for p in pats:
      n=len(re.findall(p,t)); print(f"{n:4d}  {p}") if n else None
  EOF
  ```
  (`가 아니라|가 아닌`은 3건 이하 허용, 나머지는 0건.)

## 6. 날짜·연도

- 절대 날짜만. 상대 날짜(지난달·이번 주·어제·최근·조만간) 금지.
- 반복형 사건(ECB 회의·HICP 속보·PMI·예산 표결)은 연·월을 명시. 전년 사건을 올해 사건으로 옮겨 쓰지 않는다(연도 혼동은 HIGH).
- `as_of` 이후 사건은 결과를 아는 것처럼 쓰지 않는다(예정·전망으로만).

## 7. 링크 (Briefing 규격)

- 다른 문서 링크는 **절대경로**: `[해설본](/Users/lanoir42/projects/indepth_analysis/reports/euro_macro/monthly_brief/<YYYY-MM>/<파일>.md)`. 상대경로 링크 금지.
- JSON·CSV는 링크하지 않고 절대경로를 텍스트로 표기. BI 원문 PDF는 절대경로.
- 외부 출처 URL은 참고문헌 표에 모으고, 본문에는 기관·날짜로 표기(필요 시 핵심 1차 원문만 인라인 링크).

## 8. 반환

- 본문은 지정 파일에 쓴다. 마지막 응답(반환값)은 역할 문서가 지정한 요약만(보통 10줄 이내 또는 JSON).
- 파일을 쓰지 못했거나 입력이 없으면 그 사실과 경로를 반환값에 명시한다.

## 7. 발표 대기 블록 (컨센서스 선반영 초안)

`edition.json`의 `release_cutoff`가 `as_of`보다 늦으면, 그 사이(`as_of` 다음 날 ~ `release_cutoff`)에 발표되는 지표는 **아직 모르는 값**이다. 초안은 컨센서스를 기준점으로 쓰고, 발표 후 `release_patch` 역할이 블록만 고친다. 목록은 `data/pending_releases.json`(id·발표일·컨센서스·범위·직전치·상회/하회/부합 시 의미).

- 해당 지표를 다루는 절에 아래 형식의 블록을 둔다(장당 필요한 것만, 요약·1장에는 핵심 1~3개).
  ```markdown
  <!-- PENDING:<id> -->
  - **(발표 예정: <지표>, <M/D>)** 시장 예상(컨센서스)은 <값>(직전 <값>; <출처>)임. <이 값이 의미하는 것 1문장>.
    - 상회 시: <해석 — 어떤 판단이 강화/수정되는지>
    - 하회 시: <해석>
    - 부합 시: <해석>
  <!-- /PENDING:<id> -->
  ```
- 블록 밖 판단 문장은 **발표치에 의존하지 않게** 쓴다(컨센서스 전제임을 밝히거나, 방향이 갈릴 때의 조건부 판단으로). 발표치를 추측해 확정적으로 쓰지 않는다.
- 블록 표지(`<!-- PENDING:… -->`, `<!-- /PENDING:… -->`)는 집필·수정·정합 모든 역할이 **그대로 보존**한다(삭제·이동·id 변경 금지). 블록 안 문장은 문체 규칙을 따른다.
- 블록 안 "발표 예정"·"상회 시" 표현은 금지 토큰이 아니다. 감사자는 블록 존재 자체를 결함으로 보지 않는다(블록 안 수치 출처·해석 논리는 감사).
- `release_cutoff == as_of`이면 블록을 쓰지 않는다.
