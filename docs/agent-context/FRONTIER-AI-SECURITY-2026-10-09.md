# 2026-10-09 경영진 보고 연구 — 인수인계

계획 수립일: 2026-09-28 KST. **P01~P10·렉처2편·경영진 브리프의 중간 연구본 작성. 전체 제출본 미완료.**

## 최신 실행 상태 — 두 번째 조사 묶음, 2026-09-28

- 사용자 “네 진행해 주십시오.”에 따라 공개 1차 자료 조사와 집필을 계속함. 새 하위 에이전트·CLI LLM·외부 게시 미실행.
- [브리프](../research/2026-10-09-frontier-ai-security/working/EXECUTIVE-BRIEF.md), [통합 열람본](../research/2026-10-09-frontier-ai-security/working/READING-COPY.md), [색인](../research/2026-10-09-frontier-ai-security/working/README.md).
- P06 전문가·P07 정책·P08 기업 관계·P09 경제성/금융·P10 시나리오·렉처02 신규. P02~P04에 CyberGym-E2E/CaMeL/정렬 위장/감시/최신 Astra 카드 보강.
- 고유 본문13개·54,530자(공백/마크다운/URL 포함). 출처46개, 주장34행, 사건6행, 견해6행(검증된 변화 쌍1), 관계11행, 시나리오4행, 계산9건. 통합 사본은 분량 제외.
- 핵심: Faculty 인수 완료·평가 협력 확인. 안전 투자 계획≠계약 매출. MS–OpenAI 후속 계약 반영. Wiz/CyberArk 인수 완료≠통합 완료. Morgan Stanley33bn/60bn 범위 구분. GS24%는 과거 배수 프리미엄. CaMeL 초판67/개정77 분리. Astra 만점은 다회 시도 종합 지표.
- 검증: validate.py PASS(원장ID·날짜·계산·링크). 현재13본문의 temporal 검사 합계 HIGH0/MEDIUM2/LOW11. MEDIUM2는 P06 역사적 주장 요약/P08 장기 계약 기간, 수동 대조. [검토 기록](../research/2026-10-09-frontier-ai-security/working/evidence/review-notes.md).
- assemble.py는 로컬 읽기 사본 생성만 수행. reports/·운영 코드·CLAUDE.md에 쓰지 않음. 기존 dirty 보존.
- 남은 주요 범위: 전문가12~15명/기관 전후 원문·국가/시민사회·사건 부록·독립 고객 실측·전체 기업/지분·부분식별 매출 추정·전망 수정/가치평가·최종 렉처/Q&A/반대 검토. 현재 초안을 최종 완료로 표시하지 말 것.
- 출처별 locator에 열람 범위 기록. 일부 초록·관련 절만 읽었으며 raw_sha256는 null. 법률 통합 검토·공개 성능의 실전 일반화 미완료. 자동 일정 실행 없음.
- 재개: working/README.md와 evidence/review-notes.md의 공백 순서로 조사. 검증 `python3 .../working/validate.py`, 원문 변경 후 `python3 .../working/assemble.py`. CLI 보고서 검사 진입점은 `UV_CACHE_DIR=/private/tmp/indepth-plan-uv-cache uv run --no-sync indepth lint-temporal ... --as-of 2026-09-28 --fail-on-high`.

아래 첫 조사 묶음 기록은 이력이다. 관계·시나리오가 비었다는 표기는 당시 상태이며 위 최신 상태를 우선한다.

## 최신 실행 상태 — 2026-09-28

- 사용자: “좋습니다. 이제 계획대로 진행해 주십시오.” 본조사 승인. 외부 발행 승인으로 확대하지 않음.
- [작업 색인](../research/2026-10-09-frontier-ai-security/working/README.md), [검증·통계](../research/2026-10-09-frontier-ai-security/working/evidence/validation.json).
- P01 사건, P02 능력, P03 Safety, P04 Security for AI, P05 AI for Security, 렉처01의 6문서·23,374자(공백·표·URL·마크다운 포함). 계획·원장·인수인계는 분량에서 제외. 최종 목표 분량 달성 아님.
- 원문20개 등록. 열람 범위를 locator에 기록했으며 초록·일부 절만 확인한 자료 포함. 중요 주장15행, 사건 기록6행(독립 사건 수 아님), 기관 견해 수정1행, 계산5건. 관계·시나리오 원장은 빈 상태를 유지.
- 최초 OpenAI/Anthropic 설명, 후속 조사, HF 피해자 기록, METR/Redwood, AISI, Irregular 대조. 특히 Anthropic 네 번째 사례는 초기 Opus4.6이며 AISI 사례가 아님. 인터넷 허용·설정 오류·기술적 통제 우회를 분리.
- 수치: FrontierCyber 86/226 vs34/226; Opus5.5 평균67.6 vs53.0. 범위·분모·하네스 조건 명시, 실전 위험률로 환산 금지.
- 검증: validate.py로 JSON 참조·날짜·계산·로컬 링크 PASS. 본문6개 temporal lint 최종 HIGH0/MEDIUM0/LOW3. LOW는 과거 NIST 판본과 Google/논문 발표 시점. 최초 P05 HIGH1은 과거 자료·현재 검토 문장을 분리해 수정. git diff --check PASS.
- 미확보: AISI 기술 PDF 도구 열기 오류, Anthropic 독립 후속 조사 결과, 평가별 비용·반복 분모, 실제 피해 최종금액. 원문 스냅샷·해시 미저장(null).
- 운영 코드·CLAUDE.md 변경 없음. 새 에이전트·별도 CLI LLM·공격 실험·서버 재시작·커밋/푸시·외부 발행 없음. 기존 dirty 보존.
- 다음: P01/P02의 원 논문·시스템 카드·날짜 보강, P03~P05 독립 연구/실측 심화. 이어 P06 전문가 견해·P07 정책·P08 기업/지분/계약·P09 금융/경제성·P10 시나리오. 마지막 통합본·렉처 전체·Q&A·서식 변환. 자동 예약 실행 없음.

아래는 최초 계획 수립 시점의 기록이다. “미실행”은 당시 상태이며 위 실행 기록이 최신 정본이다.

## 목표와 정본
IT 기업 최상위 경영진에게 보고할 싱크탱크의 기술·산업·투자 연구. AI Safety / Security for AI / AI for Security, Anthropic/OpenAI 사건, 전문가 견해 변화, 국가·산업·시민사회 대응, 금융기관 전망, 기업·인물·지분·계약 관계 및 렉처노트·조건부 투자 대응. 기한 2026-10-09. 이번 요청은 우선 계획 수립.

[연구계획](../research/2026-10-09-frontier-ai-security/RESEARCH-PLAN.md): 11개 절, P01~P10 심층 분석, 일정·산출물·근거 원장·검증 기준. 16,401자. 산출물 수·분량은 계획값이며 완료 실적이 아니다.

## 완료
- 프로젝트 규칙·기존 cyber v1/v2/v3/technical 연구 확인. 기존 본문·숫자를 새 기준일의 검증 완료로 승계하지 않음.
- 계획용 웹 검색과 OpenAI/Anthropic/AISI 원문5개 열람. 실제 탈출·인터넷 허용/설정 오류·승인 범위 위반 구분. 추가 조사 후보 포함 출처 링크12개.
- `UV_CACHE_DIR=/private/tmp/indepth-plan-uv-cache uv run --no-sync indepth lint-temporal docs/research/2026-10-09-frontier-ai-security/RESEARCH-PLAN.md --as-of 2026-09-28 --fail-on-high`: HIGH0/MEDIUM0/LOW2. LOW는 과거 기준선·2025년 출처 URL로 수동 확인.
- P01~P10·기한·계획 단계 표기 확인, git diff --check 통과. 운영 코드 변경 없음.

## 미실행과 재개
본조사·최종 전망/종목 판단·실포지션 조회·별도 CLI 추론·하위 에이전트·예약 실행·외부 발행·Git push 미실행. 기술 공격 재현/외부 시험도 없음.

본조사 요청 시 P01/P02부터: 공통 사건ID·출처 원장, 최초 공개와 후속 정정, 모델/도구/권한/보호설정·실제 영향 비교. 첫 사실 기반 검토는9/30, 정보 동결10/7, 본문 확정10/8, 보고10/9 제안. 자동 실행 약속이 아니다.

기존 dirty CLAUDE.md/HANDOFF.md와 과거 보고서 보존. 이전 보고서 게시 승인을 이번 연구의 외부 게시 권한으로 확대하지 않는다.


## 2026-09-28 최종 Markdown·Notion 발행 후속

사용자가 최종 .md와 Notion 게시를 명시 승인. `reports/frontier_ai_security_2026_09_28/README.md`에 기준일 발행본 v1.0 작성: 고유 본문16개 82,900자·출처62개·핵심 주장44행, 각론10/렉처3/브리프/24문답/29용어. 보고서·보조자료 MD21개, 다운로드 ZIP35파일. 기존 working 초안과 최초 계획은 보존. 당초14~22만자 및 전문가/금융기관/기업 전수조사 목표 달성을 주장하지 않으며 비공개·미확보 범위는 VALIDATION.md에 명시. 10/9 보고 시점 최신성 갱신은 예약되지 않음.

Notion 안내+6분권 게시 및 read-back 완료: https://app.notion.com/p/20260928-AI-v1-0-3e9294e2c0788136b5c5c063c05b2c61 . 본문/첨부1000블록·표39개 일치. MD7개·전체ZIP1개 첨부. `docs/research/2026-10-09-frontier-ai-security/publication/RECEIPT.md`와 최종 evidence/publication-manifest.json 참조. 원장·계산·링크·표·ZIP 검사 통과; 최종 통합 temporal HIGH0/MEDIUM4/LOW23(역사적 시점/계약 만기 검토). 외부 원문 전체 스냅샷·독립 공격 재현·고객 실측·현재 목표가 미실시. 새로운 하위 에이전트/별도 CLI 추론/운영 재시작/git push 없음. 발행 경로는 reports/이므로 기존 Briefing 스캐너 대상이지만 운영 앱 조회는 이 요청에서 별도 검증하지 않음.
