# topic_update 스킬

특정 주제(지정학·매크로·테마)에 대한 mid-cycle 업데이트 리포트를 3-agent harness로 생성.

## 원칙

- **3-agent harness**: Planner / Generator / Evaluator 각각 Opus 4.7 (run-time alias `model: "opus"`)
- **5 병렬 gatherers**: wire / official / social / kcif / market — sub-agent로 구현
- **Dog-fooding**: 첫 실행(2026-04-17 Israel-Lebanon + Iran-US)이 스킬 자체의 존재 근거
- **Evaluator gate**: R2 1회 제한
- **재현성**: 모든 단계 산출물을 `reports/<topic>/<date>/artifacts/`에 보존

## 입력 스펙 (`TopicUpdateSpec`)

| 필드 | 타입 | 설명 |
|---|---|---|
| `topic` | str | 주제 (예: "Israel-Lebanon + Iran-US War") |
| `window_days` | int | 검색 기간 (기본 7) |
| `cutoff` | str ISO-8601 | 최신 cutoff (예: "2026-04-17T06:00+09:00") |
| `output_dir` | Path | 출력 디렉토리 |
| `baseline` | Path \| None | 직전 리포트 경로 (delta 기준) |
| `publish_notion` | bool | Notion 발행 여부 |
| `interactive` | bool | Planner 후 사용자 승인 게이트 |

## Gatherer 소스 매트릭스

| Gatherer | 소스 | 도구 |
|---|---|---|
| `wire` | Reuters / AP / AFP / FT / Bloomberg | WebSearch |
| `official` | State Dept / IDF / IRGC / White House / UN | WebSearch + WebFetch |
| `social` | Trump Truth Social / X mirrors / Telegram 채널 (`~/projects/telegram/`) | WebSearch + WebFetch + `tg-sum` subprocess |
| `kcif` | `references/KCIF/` 로컬 PDF (기간 필터) | Read (PDF OCR) |
| `market` | Brent / gold / VIX / DXY / CDS | WebSearch |

## 파이프라인 산출물

```
reports/<topic>/<date>/
├── planner.md             # Phase 1
├── gatherers/
│   ├── wire.md            # Phase 2
│   ├── official.md
│   ├── social.md
│   ├── kcif.md
│   └── market.md
├── generator_r1.md        # Phase 3
├── evaluator.md           # Phase 4
└── update.md              # Phase 5 (FINAL, Notion publish 대상)
```

## CLI (향후 등록)

```bash
uv run python -m indepth_analysis.cli report topic-update \
    --topic "Israel-Lebanon + Iran-US War" \
    --window 7 \
    --cutoff 2026-04-17T06:00+09:00 \
    --output-dir reports/mideast_war \
    --publish-notion
```

## 상태

- **Phase 0 (scaffolding)**: 완료 (이 디렉토리 + prompts.py + orchestrator.py stub)
- **Phase 1~6 (첫 실행, dog-fooding)**: 2026-04-17 Israel-Lebanon + Iran-US 진행 중
- **CLI 등록**: 향후 작업 (`cli.py`에 `topic-update` subcommand 추가)

## 참고

- 기존 `euro_macro` 스킬과 유사 구조이나, `euro_macro`는 월간 배치(year/month) 대상이고
  `topic_update`는 임의 주제·기간의 ad-hoc 업데이트 대상.
- Dog-fooding 결과가 만족스러우면 CLI 정식 등록 + base class 공통화 고려.
