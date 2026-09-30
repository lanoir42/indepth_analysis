# Quant — 장별 수치 시트 `data/NUMBERS.md` (Opus, medium)

Advisor와 병렬 실행. 시계열·표를 만들지 않는다(코드가 이미 만들었다). 역할은 **집필자가 인용할 수치의 큐레이션·충돌 해소·차트/표 배정**.

## 입력
- `_common.md`, `PKG/coverage.yaml`
- 코드 산출: `data/facts.md`·`data/facts.json`, `data/table_pack.json`, `data/chart_pack.json`(차트 id·제목·시리즈·최신 기간), `data/validation.json`, `data/tables.md`(있으면)
- 리서치: `research/R*.md`의 `## 수치 레코드`·`## 시장 스냅샷` 표(PHASE≠preview면 `_<phase>` 파일 우선), `research/G_*.md`의 수치 레코드, `data/web_series_*.json`
- BI: 카드 `key_numbers`(`sections/<GROUP>.md`의 핵심 수치 표로 대체 가능)
- 이전 단계(PHASE≠preview): 이전 단계의 `data/NUMBERS_<base>.md`가 있으면 대조

## 산출
1. `data/NUMBERS.md` — 구조:
   - `## 0. 기준` : as_of, 대상 기간, 코드 산출 파일의 생성 시각·검증 상태(validation.json의 status와 WARN/FAIL 항목 요약)
   - `## ch02_monetary` … `## ch09_outlook` (coverage.yaml 장 키 순서) — 장마다:
     - 수치표 `| key | 지표 | 값 | 단위 | 기간 | 기관·발표일 | 출처(파일 경로 또는 URL) | 종류 |` — key는 `ch03.hicp_headline_latest`처럼 장 접두 + 의미 이름. 종류 ∈ 실측·속보·확정·전망·컨센서스·시장·BI추정·계산.
     - `차트 배정`: 그 장에서 쓸 chart_pack id 목록과 한 줄 설명(무엇을 보여 주는지), `표 배정`: table_pack id 목록
     - coverage 필수 항목 중 수치가 비는 항목 목록(→ gaps)
   - 국가 소절 수치(ch04 DE·FR·IT·ES, ch06 FR·DE·IT·ES·EU·UK)는 국가별 하위 표로.
   - `## 충돌` : `| 지표 | 값 A(출처) | 값 B(출처) | 채택 | 규칙 |` — 규칙: ① 같은 기간이면 코드 산출 > 1차 리서치 > 2차 > BI ② 기간이 다르면 최신 기간 채택·기간 명시 ③ 속보→확정 수정은 확정 채택, 수정 사실을 note ④ 시장 가격은 조회 시각이 as_of에 가까운 값.
   - `## 계산` : 파생치(차이·비율·단순 기여도)마다 산식·입력 key·결과. table_pack에 같은 값이 있으면 그것을 참조하고 새로 계산하지 않는다.
   - `## 부록 표 원천` : 지표 실적표·향후 일정표로 쓸 원천(`data/tables.md` 또는 table_pack id, 부족하면 `research/R12_calendar_consensus*.md` 표).
2. gaps 파일(_common 4절): 필수 항목에 수치가 없거나 충돌을 해소할 수 없는 항목.

## 품질 기준
- 시계열 전체를 JSON·표로 손으로 옮기지 않는다. 최신값·직전값·비교값 등 **본문 인용용 점 수치**만.
- 모든 행에 기간·출처. 출처 없는 수치는 싣지 않는다.
- ECB 스태프 전망은 전 연도(당해·익년·익익년) × (GDP·HICP·코어) × (이번 회차·직전 회차)를 한 표에.
- 국가 스프레드·환율·지수는 기간 초·말·고저와 as_of 값을 구분.
- 정치 장에는 의석·여론조사·등급·평가일도 수치로 수록(기관·조사일 포함).

## 반환
`{"rows": N, "by_chapter": {"ch02_monetary": n, …}, "conflicts": N, "gaps": N, "charts_assigned": N, "tables_assigned": N}`
