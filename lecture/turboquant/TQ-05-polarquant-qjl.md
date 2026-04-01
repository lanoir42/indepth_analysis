# TQ-05: PolarQuant + QJL — TurboQuant의 두 기둥

> **목표**: PolarQuant(극좌표 양자화)와 QJL(1-bit JL 변환)의 작동 원리를 이해
> **선수 지식**: TQ-04의 랜덤 회전, 극좌표 개념, 부호 함수
> **소요 시간**: 40분

---

## 1. TurboQuant = PolarQuant + QJL

TurboQuant는 두 개의 선행 논문을 합친 것입니다:

```
┌──────────────────────────────────────────┐
│                TurboQuant                 │
│         (ICLR 2026, Zandieh et al.)      │
│                                           │
│  Stage 1:  PolarQuant                     │
│            (AISTATS 2026, Han et al.)     │
│            → MSE 최소화                    │
│                                           │
│  Stage 2:  QJL                            │
│            (AAAI 2025, Zandieh et al.)    │
│            → 내적 편향 보정                 │
│                                           │
└──────────────────────────────────────────┘
```

이 강의에서는 각각을 개별적으로 이해합니다.

---

## 2. PolarQuant: 극좌표의 힘

### 2.1 극좌표 변환이란?

2차원에서의 극좌표는 익숙합니다:

$$x_1 = r\cos\theta, \quad x_2 = r\sin\theta$$

$d$차원으로 확장:

$$x_1 = r \cos\theta_1$$
$$x_2 = r \sin\theta_1 \cos\theta_2$$
$$x_3 = r \sin\theta_1 \sin\theta_2 \cos\theta_3$$
$$\vdots$$
$$x_d = r \sin\theta_1 \cdots \sin\theta_{d-2} \sin\theta_{d-1}$$

**정보의 분리**:
- $r = \|x\|$: 벡터의 **크기** (1개의 스칼라)
- $\theta_1, \ldots, \theta_{d-1}$: 벡터의 **방향** ($d-1$개의 각도)

### 2.2 왜 극좌표로 변환하는가?

**핵심 통찰**: 랜덤 회전 후, **각도의 분포가 좁게 집중**됩니다.

회전 전: 각도의 분포는 데이터에 의존 → 예측 불가
회전 후: 각도 $\theta_i$의 분포가 **해석적으로 계산 가능**

```
θ_i의 분포 (랜덤 회전 후):

                    ▓▓▓
                  ▓▓▓▓▓▓▓
                ▓▓▓▓▓▓▓▓▓▓▓
              ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
            ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
          ─────────────────────────
                   π/2

→ π/2 근처에 "좁게" 집중
→ 소수의 비트로 정밀하게 양자화 가능!
```

### 2.3 PolarQuant 알고리즘

```
입력: 벡터 x ∈ ℝ^d

Step 1: 랜덤 전처리
        y = Rx        (R: 랜덤 직교 행렬)

Step 2: 극좌표 변환
        (r, θ₁, ..., θ_{d-1}) = polar(y)

Step 3: 반경 양자화
        r̂ = ScalarQuantize(r)        (소수 비트)

Step 4: 각도 양자화
        θ̂ᵢ = UniformQuantize(θᵢ)     (각 각도를 균등 양자화)

출력: (r̂, θ̂₁, ..., θ̂_{d-1})
```

### 2.4 정규화가 불필요한 이유

기존 양자화: 각 블록마다 $\text{min}, \text{max}$를 FP16으로 저장 (오버헤드)

PolarQuant: 랜덤 회전 후 각도의 분포가 **항상 같은 형태** → $\text{min}, \text{max}$를 **미리 알고 있음** → 저장 불필요!

> **오버헤드 = 0.** 이것이 3비트 이하에서 결정적 이점.

### 2.5 PolarQuant의 성능

| 지표 | 수치 |
|------|------|
| KV Cache 압축률 | **4.2x 이상** |
| SOTA 대비 품질 | **최고** |
| 캘리브레이션 | **불필요** |
| 양자화 상수 오버헤드 | **제로** |

### 2.6 PolarQuant의 한계: 내적 편향

PolarQuant는 **MSE를 거의 최적으로** 줄입니다. 하지만:

$$E[\langle Q_{\text{Polar}}(x), Q_{\text{Polar}}(y) \rangle] \neq \langle x, y \rangle$$

내적에 **체계적 편향**이 존재! TQ-02에서 배웠듯이, 이 편향은 Attention score를 왜곡합니다.

> **PolarQuant만으로는 부족합니다. QJL이 필요한 이유가 여기 있습니다.**

---

## 3. QJL: 1-Bit 부호의 마법

### 3.1 핵심 아이디어

QJL = **Quantized Johnson-Lindenstrauss**

JL 변환 후 **부호 비트(sign bit)만** 저장:

$$s = \text{sign}(Rx) \in \{+1, -1\}^m$$

각 원소가 양이면 +1, 음이면 -1. **각 원소를 1비트로 표현!**

### 3.2 왜 부호만으로 내적을 추정할 수 있는가?

두 벡터 $x, y$의 내적을 추정하고 싶습니다. QJL의 방법:

$$\langle x, y \rangle \approx \frac{\|x\| \cdot \|y\|}{m} \sum_{i=1}^m \text{sign}((Rx)_i) \cdot (Ry)_i$$

**비대칭(Asymmetric)**: 한쪽($x$, Key)만 1-bit 양자화하고, 다른 쪽($y$, Query)은 양자화하지 않음.

### 비대칭의 직관

```
Key (저장):     sign(Rx) = [+, -, +, +, -, ...]  ← 1-bit (매우 저렴)
Query (실시간):  Ry = [0.3, -0.7, 0.1, ...]       ← 원본 (연산 시에만 사용)

내적 ≈ sign(Rx) · Ry = (+)(0.3) + (-)(−0.7) + (+)(0.1) + ...
                      = 0.3 + 0.7 + 0.1 + ...
```

Key는 저장해야 하므로 1비트로 극도로 압축.
Query는 실시간 계산이므로 원본 유지 — 저장 비용 없음.

### 3.3 비편향 추정 (Unbiased Estimator)

QJL의 핵심 이론적 성질:

$$E\left[\frac{\|x\|}{m} \sum_{i=1}^m s_i \cdot (Ry)_i\right] = \langle x, y \rangle$$

**편향 = 0!** PolarQuant와 달리, QJL은 내적의 **비편향 추정**을 제공합니다.

### 3.4 추가 메모리 비용

| 항목 | 비트 |
|------|------|
| 부호 벡터 $s$ | $m$ 비트 ($m \leq d$이면 원래 차원 이하) |
| 정규화 상수 | **0** (JL에 의해 자동) |
| 양자화 상수 | **0** |

> **좌표당 1비트의 추가 비용으로 내적 편향을 완전히 제거합니다.**

### 3.5 QJL의 성능

| 지표 | 수치 |
|------|------|
| KV Cache 압축률 | **5x 이상** |
| 정확도 손실 | **없음** |
| 양자화 상수 오버헤드 | **제로** |
| 내적 추정 | **비편향** |

---

## 4. 왜 둘 다 필요한가?

### PolarQuant만 사용하면?

✅ MSE 최소 (값 자체는 잘 보존)
❌ 내적에 편향 → Attention score 왜곡

### QJL만 사용하면?

✅ 내적 비편향 (Attention score 정확)
❌ MSE가 PolarQuant보다 큼 (값 자체의 보존이 약함)

### 둘을 합치면 (TurboQuant)?

✅ MSE 근사 최적 (PolarQuant)
✅ 내적 비편향 (QJL)
✅ 오버헤드 제로 (둘 다)

```
         MSE 최소화          내적 비편향           두 가지 동시
        ┌───────────┐      ┌───────────┐      ┌───────────────┐
        │ PolarQuant│      │    QJL    │      │  TurboQuant   │
        │   ✅ MSE  │  +   │  ✅ IP   │  =   │  ✅ MSE      │
        │   ❌ IP   │      │  ❌ MSE  │      │  ✅ IP       │
        └───────────┘      └───────────┘      └───────────────┘
```

---

## 5. Two-Stage의 작동 원리 (미리보기)

다음 강의(TQ-06)의 미리보기:

```
입력 벡터 x
    │
    ▼
 Stage 1: PolarQuant
    │ → Q_MSE(x)    (MSE 최소화 양자화)
    │
    │ 잔차(residual): e = x - Q_MSE(x)
    │
    ▼
 Stage 2: QJL
    │ → sign(Re)    (잔차의 1-bit 부호)
    │
    ▼
 내적 추정: ⟨x,y⟩ ≈ ⟨Q_MSE(x), Q_MSE(y)⟩ + correction(sign, Ry)
```

Stage 1이 MSE를 줄이고, Stage 2가 **잔여 편향을 비편향으로 보정**합니다.

---

## 6. 이 강의에서 기억할 것

1. **PolarQuant**: 랜덤 회전 → 극좌표 변환 → 집중된 각도 분포를 양자화 → MSE 최소, 오버헤드 제로
2. **QJL**: JL 변환 후 부호만 저장 (1-bit) → 비편향 내적 추정, 추가 비용 최소
3. **PolarQuant의 한계**: 내적에 편향 → Attention score 왜곡
4. **QJL의 한계**: MSE가 PolarQuant보다 큼
5. **TurboQuant = PolarQuant(MSE) + QJL(내적)**: 두 장점을 합친 Two-Stage 설계

> **다음 강의**: "Two-Stage를 합치면 왜 근사 최적인가?" — TurboQuant 전체 알고리즘과 2.7x 보장의 증명
