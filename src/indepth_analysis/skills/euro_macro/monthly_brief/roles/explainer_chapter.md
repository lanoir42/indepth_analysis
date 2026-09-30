# Explainer — 해설본 장 집필 (Opus, medium)

해설본은 리포트와 장이 1:1로 대응하는 **교재**. 리포트가 "무엇이 일어났고 어떻게 판단하는가"라면 해설본은 "그 판단을 이해하려면 무엇을 알아야 하는가". 장 하나당 에이전트 하나, 워크플로가 `CHAPTER=<explainer 장 키>`(ex01_judgement … ex10_changes, glossary는 explainer_polish 몫)를 넘긴다.

## 입력
- `_common.md`, `PKG/STYLE_BRIEF.md`(특히 7절 해설본 변형 규칙), `PKG/coverage.yaml`의 `explainer.chapters`(해당 장의 `topics`·`maps_to`)와 `reader_questions`(이 장에 배정된 질문)
- `02_advisor_{PHASE}.md` — 해설본 설계(8절)·독자 질문 배정표(6절)
- 대응 리포트 장 초안(최신 rN): `drafts/{PHASE}_report_{maps_to}_r*.md` 또는 통합본 `drafts/{PHASE}_report_rN.md`의 해당 장 — **겹치지 않게 하기 위해** 읽는다
- `data/NUMBERS.md`, `data/facts.md`, 대응 리서치 축(chief_chapter.md의 장↔축 표)
- 제도·역사 설명에 필요하면 리서치의 1차 출처 URL(헌법 조문·ECB 규정·EU 규칙)을 WebFetch로 확인해도 된다(수치는 NUMBERS.md 우선).

## 산출
- `drafts/{PHASE}_explainer_{CHAPTER}_r1.md`, 첫 줄 `<!-- explainer: {CHAPTER} | maps_to: {maps_to} | chars: N -->`
- gaps 파일(_common 4절)

## 절 구성 (topics마다 하나의 절, 순서 권장)
1. `**[핵심]**` 리드: 이 절에서 배울 결론 1~2문장
2. 배경: 왜 지금 이 주제가 중요한가(이번 달 사건과 연결 1~2문장)
3. 작동 원리: 제도·메커니즘을 연결된 문단(4~8문장)으로. 조문·요건·숫자를 구체적으로(예: 프랑스 헌법 49조 3항 → 정부가 법안에 책임을 걸면 표결 없이 채택 → 24시간 내 불신임 동의 제출 가능 → 재적 과반(289표) 찬성 시 정부 사퇴)
4. **숫자 풀이 예제**: 이번 달 실제 수치(NUMBERS.md key)로 계산 과정을 단계별로(기여도, 스프레드, OIS 확률, 교차환율 분해, 기저효과, 의석 산술 등)
5. 경과: 전년~올해 주요 사건·수치(연도 명시 표 또는 불릿)
6. `- **(독자 질문: …)**` 배정 질문에 대한 답 2~5문장
7. `- **(리포트와의 연결)**` 이 원리가 리포트 몇 장의 어떤 판단을 뒷받침하는지 한 줄

## 품질 기준
- 목표 분량(coverage target_chars) ±15%.
- 리포트 문장·판단 문구를 복사하지 않는다. 같은 수치를 쓰더라도 해설본에서는 원리 설명의 재료로만(리포트와 문장 중복 20% 이하).
- 용어를 다른 전문용어로만 풀지 않는다. 처음 보는 독자가 따라올 수 있도록 단계를 건너뛰지 않는다.
- 비유는 절당 1개 이하, 비유 뒤에 실제 메커니즘.
- 정치 제도 장(ex06)은 FR 예산 절차·49.3·불신임·해산권, DE 연정·연방참사원·부채제동·특별기금, IT 예산·EDP, ES 소수정부·예산 연장, EU MFF·SAFE·재정규칙, UK 예산·OBR·재정 규칙을 모두 다룬다.
- 수치는 NUMBERS.md·리서치에서만, 기간·출처 병기. 거부 문장 0, 금지 토큰 0(저장 전 grep).

## 반환
`{"chapter": "...", "chars": N, "sections": [...], "worked_examples": N, "reader_questions_answered": ["rq04", …], "gaps": N}`
