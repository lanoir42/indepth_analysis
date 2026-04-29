"""Synthesis prompts for Issue Track skill."""

SYNTHESIS_SYSTEM_PROMPT = """\
당신은 전문 투자 리서치 어시스턴트입니다. 수집된 증거들을 바탕으로 \
이슈 트래킹 보고서를 작성합니다.

보고서 원칙:
1. 사실만 기록 — 추측·전망은 "추정" 명시
2. 모든 주장에 [n] 인용 번호 부여
3. 1차 자료(tier 1) 우선, 소셜(tier 3) 인용 시 신뢰도 표기
4. 한국어로 작성, 고유명사·수치는 영어 혼용 허용
5. 우려·이견·반박을 공정하게 모두 제시
"""

SYNTHESIS_USER_PROMPT = """\
아래는 "{topic}" 이슈에 대해 수집된 증거입니다.

수집 기간: {since} 이후
실행: Run #{run_no} (누적 evidence: {total_evidence}건, 이번 신규: {new_evidence}건)

---
{evidence_context}
---

위 증거를 바탕으로 다음 구조로 보고서를 작성하세요:

## 1. 한 줄 요약
(이슈의 핵심을 1~2문장으로)

## 2. 타임라인
(시간순으로 중요 사건을 개조식 목록으로)

## 3. 1차 자료 분석
(공식 발표, SEC 공시, IR 내용 분석)

## 4. 주요 매체 보도 분석
(tier 2 언론 보도 종합, 핵심 인용 포함)

## 5. 소셜·블로그 반응
(신뢰도 2.5 이상만 인용. 신뢰도 표기 필수: "swyx [3.8/5]")

## 6. 우려의 골자
(concern stance evidence 종합)

## 7. 내부 이견
(dissent stance evidence 종합)

## 8. 반박
(rebuttal stance evidence 종합)

## 9. 분석가 노트
(evidence 기반 종합 판단 — 증거가 가리키는 방향)

## 10. 모니터링 포인트
(다음 run에서 확인해야 할 사항 3~5개)

각 주장에 [n] 형태로 인용 번호를 부여하고, 마지막에 ## 출처 섹션에서
[n]: <URL> 형태로 모든 URL을 나열하세요.
"""

SLUG_EXTRACT_PROMPT = """\
아래 이슈 설명에서 간결한 slug(URL 안전 식별자)를 추출하세요.
규칙: 소문자, 하이픈으로 연결, 3~5 단어, 회사명-핵심이슈-연도 형태 권장

이슈: {topic}

slug만 출력하세요. 예시: openai-revenue-concerns-2026
"""

KEYWORDS_EXTRACT_PROMPT = """\
아래 이슈에 대한 웹 검색에 사용할 핵심 키워드 5~8개를 추출하세요.
영어와 한국어 모두 포함하세요.

이슈: {topic}

JSON 배열로만 출력하세요. 예: ["OpenAI revenue", "OpenAI 실적", "OpenAI financial results"]
"""
