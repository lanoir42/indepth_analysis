# TQ-06: TurboQuant 통합 — 근사 최적 양자화의 완성

> **목표**: Two-Stage 알고리즘의 전체 흐름을 이해하고, 2.7x 근사 최적성의 의미를 파악, 실험 결과 해석
> **선수 지식**: TQ-01~05 전체
> **소요 시간**: 40분

---

## 1. 논문 정보

| 항목 | 내용 |
|------|------|
| **제목** | TurboQuant: Online Vector Quantization with Near-optimal Distortion Rate |
| **저자** | Amir Zandieh (Google Research), Majid Daliri (NYU), Majid Hadian (Google DeepMind), Vahab Mirrokni (Google Research, VP & Google Fellow) |
| **학회** | ICLR 2026 |
| **arxiv** | 2504.19874 |

---

## 2. 전체 알고리즘 흐름

### Step-by-Step

```
입력: KV Cache 벡터 x ∈ ℝ^d (예: d = 128)

━━━━━━━━━━ Stage 1: PolarQuant (B-1 비트) ━━━━━━━━━━

  ① 랜덤 직교 행렬 R을 곱한다
     y = Rx
     → 좌표들이 Beta(1/2, (d-1)/2) ≈ N(0, 1/d) 분포를 따름

  ② 극좌표로 변환한다
     (r, θ₁, θ₂, ..., θ_{d-1}) = polar(y)

  ③ 반경 r을 스칼라 양자화한다 (소수 비트)

  ④ 각 각도 θᵢ를 최적 균등 양자화한다
     → 분포가 알려져 있으므로 Lloyd-Max 양자화기 적용 가능

  출력: Q_MSE(x)    총 B-1 비트/차원

━━━━━━━━━━ 잔차 계산 ━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ⑤ 잔차를 계산한다
     e = x - Q_MSE⁻¹(Q_MSE(x))

━━━━━━━━━━ Stage 2: QJL (1 비트) ━━━━━━━━━━━━━━━━

  ⑥ 잔차에 JL 변환을 적용한다
     z = R'e       (R': 또 다른 랜덤 행렬)

  ⑦ 부호만 저장한다
     s = sign(z) ∈ {+1, -1}^m

  출력: s           총 1 비트/차원

━━━━━━━━━━ 최종 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  총 비트: (B-1) + 1 = B 비트/차원
```

### 내적 추정 (추론 시)

새 Query $q$가 들어오면:

$$\langle x, q \rangle \approx \underbrace{\langle Q_{\text{MSE}}(x), Q_{\text{MSE}}(q) \rangle}_{\text{Stage 1: MSE 양자화된 내적}} + \underbrace{\text{correction}(s_x, R'q)}_{\text{Stage 2: 잔차 편향 보정}}$$

Stage 1만으로는 편향이 있지만, Stage 2의 보정항이 이를 **정확히 상쇄**합니다.

---

## 3. 왜 Two-Stage가 필수적인가?

### 실험으로 확인

3-bit 양자화에서 Llama-3 70B의 Perplexity (WikiText-2, 낮을수록 좋음):

| 방법 | Perplexity | FP16 대비 차이 |
|------|-----------|---------------|
| FP16 (기준) | 5.12 | — |
| PolarQuant **만** | 5.23 | +0.11 |
| QJL **만** | 5.35 | +0.23 |
| **TurboQuant (PolarQuant + QJL)** | **5.18** | **+0.06** |
| KIVI | 6.45 | +1.33 |

> Two-Stage 결합이 각각보다 **명확히 우월**합니다.

### 수학적 이유

**Stage 1 (PolarQuant)만**: $\langle Q(x), Q(y) \rangle$에 편향 $\beta(x,y)$ 존재

$$E[\langle Q(x), Q(y) \rangle] = \langle x, y \rangle + \beta(x,y)$$

**Stage 2 (QJL) 추가**: 잔차 $e = x - Q(x)$에 대해

$$E[\langle Q(x), Q(y) \rangle + \text{QJL correction}] = \langle x, y \rangle + \beta - \beta = \langle x, y \rangle$$

> **QJL이 PolarQuant의 편향을 정확히 상쇄합니다.**

---

## 4. 2.7x 근사 최적성 — 무엇을 의미하는가?

### 정리 (TurboQuant Main Theorem)

> $d$차원 단위 구 위의 임의의 벡터 $x$에 대해, TurboQuant의 $B$-bit 양자화기 $Q$는:
>
> $$E[\|x - Q^{-1}(Q(x))\|^2] \leq 2.7 \cdot D^*(B, d)$$
>
> 여기서 $D^*(B, d)$는 정보이론적 최소 왜곡.

### 비유로 이해하기

서울에서 부산까지의 최단 거리가 400km라면:

| 내비게이션 | 경로 | 최적 대비 |
|-----------|------|---------|
| 최적 (이론적) | 400 km | 1.0x |
| **TurboQuant** | **≤ 1,080 km** | **≤ 2.7x** |
| 기존 양자화 (KIVI 등) | ??? km | **보장 없음** |

2.7x가 크게 느껴질 수 있지만:
- 이것은 **최악의 경우**에 대한 보장
- 실제로는 대부분 **2x 이하**에서 작동
- 기존 방법은 **아무런 이론적 보장이 없음**

### 왜 1.0x가 아닌가?

최적 벡터 양자화는 **NP-hard** 문제 (격자 문제와 동치).

$$\text{NP-hard} \implies \text{다항 시간에 } 1.0x \text{는 (아마도) 불가능}$$

2.7x는 **다항 시간에 달성 가능한 최선에 가까운** 근사 인자입니다.

---

## 5. Data-Oblivious의 위력

### Data-Oblivious = 캘리브레이션 불필요

| 속성 | 기존 방법 (GPTQ, AWQ) | TurboQuant |
|------|---------------------|-----------|
| 양자화 전 준비 | 수백~수천 샘플로 캘리브레이션 | **없음** |
| 새 모델 적용 | 재캘리브레이션 필요 | **즉시 적용** |
| 온라인 스트림 | 불가 (오프라인 전처리 필수) | **가능** |
| 배포 파이프라인 | 복잡 | **단순** |

### 왜 Data-Oblivious가 가능한가?

TQ-04에서 배웠듯이:

1. 랜덤 회전 후 좌표 분포는 **데이터와 무관**하게 항상 $\text{Beta}(1/2, (d-1)/2)$
2. 이 분포에 대한 최적 양자화기는 **미리 계산** 가능
3. 따라서 데이터를 볼 필요 없이 양자화기가 결정됨

> **"어떤 LLM이든, 어떤 입력이든, 같은 양자화기를 사용합니다."**

---

## 6. 실험 결과 해석

### 6.1 Perplexity (WikiText-2)

```
비트폭     FP16    KIVI    KVQuant    TurboQuant
──────────────────────────────────────────────
4-bit     5.12    5.14    5.13       5.12  ← 완벽 보존
3.5-bit   5.12    5.31    5.21       5.13  ← 사실상 무손실
3-bit     5.12    6.45    5.67       5.18  ← 차이 매우 작음
2-bit     5.12    발산     8.92       5.89  ← 유일하게 작동
```

> **3.5-bit에서 품질 완전 보존 (Quality Neutral)**

### 6.2 Needle-in-a-Haystack (긴 문서에서 특정 정보 찾기)

```
컨텍스트 길이    FP16    KIVI(3bit)    TurboQuant(3bit)
──────────────────────────────────────────────────
  8K            100%     100%          100%
  32K           100%      98%          100%
  64K           100%      91%          100%
  104K          100%      72%          100%  ← 결정적 차이!
```

기존 방법(KIVI)은 긴 문서에서 **정보를 "잊어버리지만"**, TurboQuant는 **104K까지 완벽**.

### 6.3 속도 (NVIDIA H100)

| 설정 | Attention logit 속도 |
|------|---------------------|
| FP32 (기준) | 1.0x |
| FP16 | 2.0x |
| **4-bit TurboQuant** | **8.0x** |
| **3-bit TurboQuant** | **6.2x** |

### 6.4 메모리 절감 (Llama-3 70B, 128K)

| 설정 | KV Cache 크기 | 절감 |
|------|-------------|------|
| FP16 | 335 GB | 1x |
| 4-bit TurboQuant | 56 GB | **6.0x** |
| 3.5-bit (품질 중립) | 49 GB | **6.8x** |
| 3-bit TurboQuant | 42 GB | **8.0x** |

> **H100 1장(80GB)에 70B 모델의 128K 컨텍스트 추론이 가능해집니다.**

---

## 7. TurboQuant의 한계와 열린 문제

### 한계

| 한계 | 설명 |
|------|------|
| **KV Cache만** | 모델 가중치 양자화에는 적용되지 않음 |
| **추론만** | 훈련(training)에는 사용 불가 |
| **랜덤 행렬 오버헤드** | $R$을 저장하거나 시드를 공유해야 함 (미미하지만 존재) |
| **2.7x 갭** | 1.0x까지 줄일 수 있는가? (아마 NP-hard) |

### 열린 문제

1. **2비트 이하로 갈 수 있는가?** — TurboQuant도 2-bit에서는 성능 저하 (5.89)
2. **가중치 + KV Cache 동시 양자화?** — 현재 두 기법을 독립적으로 적용해야 함
3. **훈련 시 양자화?** — Gradient가 극좌표에서 어떻게 흐르는가?
4. **다른 도메인 (Vision, Audio)?** — Transformer가 아닌 구조에서도 작동하는가?

---

## 8. 시장과 산업 영향 (요약)

### 발표 당일 시장 반응 (3/25)

| 종목 | 변동 | 이유 |
|------|------|------|
| Micron (MU) | **-3.0%** | HBM 수요 감소 우려 |
| SanDisk (SNDK) | **-5.7%** | 메모리 수요 감소 우려 |
| NVIDIA | 소폭 하락 | GPU에는 오히려 긍정적 가능성 |

### Jevons Paradox: 수요는 줄지 않는다

> *"자원 사용 효율이 향상되면, 그 자원의 총 소비는 오히려 증가한다."*

과거 사례:
- LED 조명 → 조명의 편재화 → 전력 소비 증가
- 인터넷 대역폭 증가 → 스트리밍 폭발 → 트래픽 증가

AI에 적용:
- TurboQuant로 메모리 6x 절감 → 6x 더 긴 컨텍스트, 6x 더 큰 모델 → **HBM 수요 유지/증가**

> Morgan Stanley: *"TurboQuant는 KV Cache만 영향. 모델 가중치와 훈련에는 무관. 총 HBM 수요를 6배 줄이는 것이 아니라, 단일 GPU의 처리량을 높이는 것."*

---

## 9. 전체 강의 시리즈 복습

```
TQ-01: KV Cache가 왜 병목인가?
  └─ 긴 컨텍스트에서 KV Cache > 모델 가중치 (335 GB > 140 GB)

TQ-02: 양자화의 기초
  └─ MSE vs 내적 왜곡, 편향 문제, 양자화 상수 오버헤드

TQ-03: Shannon의 Rate-Distortion
  └─ 이론적 최소 왜곡 D*(B), 고차원에서 소수 비트로도 가능

TQ-04: JL Lemma와 랜덤 회전
  └─ 분포 균등화 + 좌표 독립화 + 정규화 불필요 → Data-Oblivious

TQ-05: PolarQuant + QJL
  └─ PolarQuant(MSE 최소) + QJL(내적 비편향) — 각각의 한계

TQ-06: TurboQuant 통합        ← 지금 여기
  └─ Two-Stage: MSE 최소 + 내적 비편향 동시 달성
  └─ 2.7x 근사 최적, Data-Oblivious, 오버헤드 제로
  └─ 6x 메모리 절감, 8x 속도 향상, 정확도 손실 제로
```

---

## 10. 핵심 공식 모음

| 공식 | 이름 | 강의 |
|------|------|------|
| $\text{Attention} = \text{softmax}(QK^T/\sqrt{d_k}) \cdot V$ | Self-Attention | TQ-01 |
| $D_{\text{MSE}} = E[\|x - Q(x)\|^2]$ | MSE 왜곡 | TQ-02 |
| $R(D) = \frac{d}{2}\log_2(\sigma^2/D)$ | 가우시안 Rate-Distortion | TQ-03 |
| $P[\|\|Ru\|^2 - 1\| > \varepsilon] \leq 2e^{-\varepsilon^2 k/8}$ | JL 집중 부등식 | TQ-04 |
| $u_i^2 \sim \text{Beta}(1/2, (d-1)/2)$ | 회전 후 좌표 분포 | TQ-04 |
| $E[\text{sign}(Rx) \cdot Ry] \propto \langle x, y \rangle$ | QJL 비편향 추정 | TQ-05 |
| $D_{\text{TQ}} \leq 2.7 \cdot D^*$ | 근사 최적성 | TQ-06 |

---

## 참고 논문

1. Zandieh et al. (2026). "TurboQuant." ICLR 2026. [arxiv:2504.19874](https://arxiv.org/abs/2504.19874)
2. Han et al. (2026). "PolarQuant." AISTATS 2026. [arxiv:2502.02617](https://arxiv.org/abs/2502.02617)
3. Zandieh et al. (2025). "QJL." AAAI 2025. [arxiv:2406.03482](https://arxiv.org/abs/2406.03482)
4. Shannon (1948). "A Mathematical Theory of Communication."
5. Johnson & Lindenstrauss (1984). "Extensions of Lipschitz mappings into a Hilbert space."
6. Zador (1963). "Development and Evaluation of Procedures for Quantizing Multivariate Distributions."

> **이 강의 시리즈를 완료하셨습니다. 논문 원본을 읽을 준비가 되었습니다.**
