# TQ101: TurboQuant — LLM 추론 최적화의 수학

> **대상**: 공학 석·박사급 (선형대수, 확률론 기초 수준)
> **목표**: TurboQuant 논문(ICLR 2026)을 root-to-leaf로 이해
> **소요 시간**: 총 6강 × 40분 = 4시간
> **논문**: Zandieh et al. "TurboQuant: Online Vector Quantization with Near-optimal Distortion Rate" (arxiv:2504.19874)

---

## 강의 구성

| # | 파일 | 제목 | 핵심 질문 | 시간 |
|---|------|------|----------|------|
| 1 | `TQ-01-why-kv-cache.md` | KV Cache: 왜 이것이 병목인가? | "LLM이 긴 텍스트를 읽을 때 메모리가 왜 폭발하는가?" | 40분 |
| 2 | `TQ-02-quantization-basics.md` | 양자화 기초: 비트를 줄이면 무엇을 잃는가? | "16비트를 3비트로 줄이면 정보는 어떻게 되는가?" | 40분 |
| 3 | `TQ-03-shannon-rate-distortion.md` | Shannon의 한계: 얼마나 줄일 수 있는가? | "이론적으로 최선의 양자화는 무엇인가?" | 40분 |
| 4 | `TQ-04-jl-lemma-random-rotation.md` | JL Lemma와 랜덤 회전의 마법 | "랜덤하게 돌리면 왜 좋아지는가?" | 40분 |
| 5 | `TQ-05-polarquant-qjl.md` | PolarQuant + QJL: TurboQuant의 두 기둥 | "극좌표와 1-bit 부호가 어떻게 KV Cache를 압축하는가?" | 40분 |
| 6 | `TQ-06-turboquant-full.md` | TurboQuant 통합: 근사 최적 양자화 | "Two-Stage 설계가 왜 필수적이며, 2.7x 인자는 어디서 오는가?" | 40분 |

## 선수 지식

- 선형대수: 벡터, 행렬, 내적, 노름
- 확률론: 기대값, 분산, 정규분포, 큰 수의 법칙
- 기초 정보이론: 엔트로피 개념 (없어도 강의 내에서 설명)

## 읽는 순서

`TQ-01` → `TQ-02` → `TQ-03` → `TQ-04` → `TQ-05` → `TQ-06`

각 강의는 독립적으로 읽을 수 있지만, 순서대로 읽으면 논문의 **동기 → 이론 → 알고리즘 → 성능** 흐름이 자연스럽게 이어집니다.
