export const meta = {
  name: 'euro-macro-monthly-v3',
  description: '유럽 매크로 월간 리포트 v3 — BI 그룹 정리·수치표 → 골자 → 장별 리포트·해설본 → 감사·보충 리서치·수정 → 정합·게이트 → 편집기록',
  whenToUse: 'indepth_analysis 유럽 매크로 월간 리포트(v3) Opus 단계. args는 `uv run python -m indepth_analysis.skills.euro_macro.monthly_brief.workflow.args --root ROOT` 출력 JSON.',
  phases: [
    { title: 'Prepare', detail: 'BI 그룹 섹션 서술(그룹 병렬) ∥ 수치표 NUMBERS.md' },
    { title: 'Design', detail: 'Advisor 골자 (effort high)' },
    { title: 'Write', detail: '장별 리포트 → 같은 장 해설본 (pipeline)' },
    { title: 'Assemble', detail: '리포트 Polish(요약·부록) → 해설본 Polish(용어사전)' },
    { title: 'Audit', detail: '수치·논리·문체·커버리지·독자질문 감사 → 보충 리서치 → 수정 (최대 2라운드)' },
    { title: 'Harmonize', detail: '리포트↔해설본 정합 → 결정론 게이트 수정' },
    { title: 'Editorial', detail: '방법·출처·남은 공백 편집기록' },
  ],
}

// ---------- 인자 ----------
const A = args || {}
const PKG = A.pkg || '/Users/lanoir42/projects/indepth_analysis/src/indepth_analysis/skills/euro_macro/monthly_brief'
const PROJECT = A.project || '/Users/lanoir42/projects/indepth_analysis'
const ROLES = `${PKG}/roles`
const ROOT = A.root
const P = A.phase
if (!ROOT || !P) throw new Error('args.root, args.phase 필수')
const CHAPTERS = A.chapters || []   // [{key,title,effort,target_chars,role,explainer:{key,title,target_chars}|null, base_draft}]
const GROUPS = A.groups || []
const MAX_ROUNDS = A.maxRounds || 2
if (A.hasPending) log(`발표 대기 구간 ${A.pendingWindow.from}~${A.pendingWindow.to}: 컨센서스 선반영 초안 (data/pending_releases.json)`)
const START = A.startRev || null    // 재개: {report:'preview_report_r2', explainer:'preview_explainer_r2', round:2}
const MED = 'medium'
const HIGH = 'high'

const head = (roleName, extra) => [
  `ROOT=${ROOT}`,
  `PHASE=${P}`,
  ...(extra || []),
  `먼저 ${ROLES}/_common.md 와 ${ROLES}/${roleName}.md 를 읽고 그대로 수행하십시오. 회차 변수는 ${ROOT}/edition.json (데이터 기준일 ${A.asOf}, 보고일 ${A.reportDate}).`,
].join('\n')

const AUDIT_SCHEMA = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['PASS', 'FAIL'] },
    high: { type: 'integer' }, medium: { type: 'integer' }, low: { type: 'integer' },
    gap_questions: { type: 'array', items: { type: 'object', properties: {
      question: { type: 'string' }, context: { type: 'string' } }, required: ['question'] } },
    file: { type: 'string' },
  },
  required: ['verdict', 'high', 'medium', 'low', 'gap_questions', 'file'],
}
const DONE_SCHEMA = { type: 'object', properties: {
  ok: { type: 'boolean' }, output: { type: 'string' }, note: { type: 'string' } }, required: ['ok', 'output'] }
const bump = (name) => name.replace(/_r(\d+)$/, (_, n) => `_r${Number(n) + 1}`)

let repCur, expCur, round0 = 1

if (!START) {
  // ---------- Prepare ----------
  phase('Prepare')
  const prep = await parallel([
    ...GROUPS.map(g => () => agent(
      head('bi_section', [`GROUP=${g}`, `대상 ${ROOT}/sections/${g}.md (제자리 갱신)`]),
      { label: `section:${g}`, phase: 'Prepare', effort: MED, schema: DONE_SCHEMA })),
    () => agent(head('quant', [`출력 ${ROOT}/data/NUMBERS.md`]),
      { label: 'quant', phase: 'Prepare', effort: MED, schema: DONE_SCHEMA }),
  ])
  const failed = prep.map((r, i) => (!r || !r.ok) ? (i < GROUPS.length ? GROUPS[i] : 'quant') : null).filter(Boolean)
  if (failed.length) log(`Prepare 미완: ${failed.join(', ')} — 골자 단계가 원자료 직접 참조`)

  // ---------- Design ----------
  phase('Design')
  const adv = await agent(head('advisor', [`출력 ${ROOT}/02_advisor_${P}.md`]),
    { label: 'advisor', phase: 'Design', effort: HIGH, schema: DONE_SCHEMA })
  if (!adv || !adv.ok) throw new Error('Advisor 실패')

  // ---------- Write ----------
  phase('Write')
  const written = await pipeline(
    CHAPTERS,
    (_, ch) => agent(head(ch.role || 'chief_chapter', [
      `CHAPTER=${ch.key}`, `장 제목 「${ch.title}」, 목표 ${ch.target_chars}자`,
      `GAPS=${ROOT}/_work/gaps/${P}_chief_${ch.key}.json`,
      ...(ch.base_draft ? [`BASE_DRAFT=${ch.base_draft}`] : []),
      `출력 ${ROOT}/drafts/${P}_report_${ch.key}_r1.md`]),
      { label: `chief:${ch.key}`, phase: 'Write', effort: ch.effort || MED, schema: DONE_SCHEMA }),
    (r, ch) => (r && r.ok && ch.explainer) ? agent(head('explainer_chapter', [
      `CHAPTER=${ch.explainer.key}`, `대응 리포트 장 ${ROOT}/drafts/${P}_report_${ch.key}_r1.md`,
      `목표 ${ch.explainer.target_chars}자`,
      `GAPS=${ROOT}/_work/gaps/${P}_explainer_${ch.explainer.key}.json`,
      `출력 ${ROOT}/drafts/${P}_explainer_${ch.explainer.key}_r1.md`]),
      { label: `explain:${ch.explainer.key}`, phase: 'Write', effort: MED, schema: DONE_SCHEMA }) : (r && r.ok ? { ok: true, output: 'no-explainer' } : null),
  )
  const missing = CHAPTERS.filter((c, i) => !written[i] || !written[i].ok).map(c => c.key)
  if (missing.length) throw new Error(`장 집필 실패: ${missing.join(', ')}`)

  // ---------- Assemble ----------
  phase('Assemble')
  const repFiles = CHAPTERS.map(c => `${ROOT}/drafts/${P}_report_${c.key}_r1.md`)
  const pol = await agent(head('polish', [
    `입력 장 초안(순서대로): ${repFiles.join(', ')}`, `출력 ${ROOT}/drafts/${P}_report_r1.md`]),
    { label: 'polish:report', phase: 'Assemble', effort: HIGH, schema: DONE_SCHEMA })
  if (!pol || !pol.ok) throw new Error('리포트 Polish 실패')
  const expFiles = CHAPTERS.filter(c => c.explainer).map(c => `${ROOT}/drafts/${P}_explainer_${c.explainer.key}_r1.md`)
  const epol = await agent(head('explainer_polish', [
    `입력 장 초안(순서대로): ${expFiles.join(', ')}`, `통합 리포트 ${ROOT}/drafts/${P}_report_r1.md`,
    `출력 ${ROOT}/drafts/${P}_explainer_r1.md`]),
    { label: 'polish:explainer', phase: 'Assemble', effort: MED, schema: DONE_SCHEMA })
  if (!epol || !epol.ok) throw new Error('해설본 Polish 실패')
  repCur = `${P}_report_r1`
  expCur = `${P}_explainer_r1`
} else {
  repCur = START.report
  expCur = START.explainer
  round0 = START.round || 1
  log(`재개: ${repCur} / ${expCur}, 라운드 ${round0}부터`)
}

// ---------- Audit → gap research → Fix ----------
phase('Audit')
const auditOne = (kind, target, docKind, round) => () => agent(head(`audit_${kind}`, [
  `TARGET=${ROOT}/drafts/${target}.md (${docKind})`, `ROUND=${round}`,
  `감사 파일 ${ROOT}/audit/${target}_audit_${kind}.md 작성 후 JSON 블록을 구조화 출력(file=감사 파일 경로, high/medium/low=건수, gap_questions=조사로 메울 공백)`]),
  { label: `audit:${kind}:${target}`, phase: 'Audit', effort: MED, schema: AUDIT_SCHEMA })
const readerOne = (rep, exp, round) => () => agent(head('audit_reader', [
  `리포트 ${ROOT}/drafts/${rep}.md`, `해설본 ${ROOT}/drafts/${exp}.md`, `ROUND=${round}`,
  `감사 파일 ${ROOT}/audit/${P}_reader_r${round}_audit_reader.md 작성 후 JSON 구조화 출력`]),
  { label: `audit:reader:r${round}`, phase: 'Audit', effort: MED, schema: AUDIT_SCHEMA })

const LABELS = ['R:fact', 'R:logic', 'R:style', 'R:coverage', 'E:fact', 'E:style', 'E:coverage', 'reader']
for (let round = round0; round <= MAX_ROUNDS; round++) {
  const res = await parallel([
    auditOne('fact', repCur, '풀 리포트', round), auditOne('logic', repCur, '풀 리포트', round),
    auditOne('style', repCur, '풀 리포트', round), auditOne('coverage', repCur, '풀 리포트', round),
    auditOne('fact', expCur, '해설본', round), auditOne('style', expCur, '해설본', round),
    auditOne('coverage', expCur, '해설본', round), readerOne(repCur, expCur, round),
  ])
  log(`라운드 ${round} 감사: ` + res.map((r, i) => `${LABELS[i]}=${r ? `${r.verdict}/H${r.high}M${r.medium}` : 'ERR'}`).join(' '))
  const highs = res.reduce((s, r) => s + (r ? r.high : 1), 0)
  const fails = res.filter(r => !r || r.verdict === 'FAIL').length
  if (round > 1 && highs === 0 && fails === 0) { log('감사 통과 — 수정 생략'); break }

  // 보충 리서치: 감사 gap + 집필 단계 gap 파일 병합 (라운드 1만; 라운드 2 공백은 편집기록으로)
  let gapNote = ''
  const gaps = res.filter(Boolean).flatMap(r => r.gap_questions || [])
  if (round === 1) {
    const g = await agent([
      `ROOT=${ROOT}`, `PHASE=${P}`,
      `보충 리서치 담당. (1) ${ROOT}/_work/gaps/*.json (집필 단계 공백)과 아래 감사 공백 질문 ${gaps.length}건을 합쳐 중복을 병합하고, 본문 판단에 영향이 큰 순으로 최대 30건을 ${ROOT}/_work/gaps_r${round}.json 에 [{"id","question","context"}] 형식으로 저장.`,
      `(2) Bash로 실행: cd ${PROJECT} && uv run python -m indepth_analysis.skills.euro_macro.monthly_brief.research --root ${ROOT} --gaps ${ROOT}/_work/gaps_r${round}.json — Sonnet 웹리서치 세션(질문 6건당 1세션, 병렬, 최대 30분). Bash timeout 600000ms로 실행하고, 끝나지 않으면 같은 명령을 재실행(완료분은 영수증으로 건너뜀)해 모두 끝날 때까지 반복.`,
      `(3) 산출 ${ROOT}/research/G_r${round}_*.md 목록과 실패 세션을 output 에 기록. 질문이 0건이면 실행하지 말고 ok=true.`,
      `감사 공백 질문:\n${JSON.stringify(gaps).slice(0, 15000)}`,
    ].join('\n'), { label: `gap-research:r${round}`, phase: 'Audit', effort: MED, schema: DONE_SCHEMA })
    log(`보충 리서치: ${g && g.ok ? g.output : '실패'}`)
    if (g && g.ok) gapNote = `보충 리서치 ${ROOT}/research/G_r${round}_*.md`
  }
  const nextRep = bump(repCur)
  const nextExp = bump(expCur)
  const readerFile = `${ROOT}/audit/${P}_reader_r${round}_audit_reader.md`
  const fixed = await parallel([
    () => agent(head('fixer', [
      `IN=${ROOT}/drafts/${repCur}.md`, `OUT=${ROOT}/drafts/${nextRep}.md`, `ROUND=${round}`,
      `감사 파일: ${['fact', 'logic', 'style', 'coverage'].map(k => `${ROOT}/audit/${repCur}_audit_${k}.md`).join(', ')}, ${readerFile}`,
      ...(gapNote ? [gapNote] : []), `GAPS=${ROOT}/_work/gaps/${P}_fixer_r${round}_report.json`,
      `로그 ${ROOT}/audit/${nextRep}_fix_log.md`]),
      { label: `fix:${nextRep}`, phase: 'Audit', effort: round === 1 ? HIGH : MED, schema: DONE_SCHEMA }),
    () => agent(head('fixer', [
      `IN=${ROOT}/drafts/${expCur}.md (해설본)`, `OUT=${ROOT}/drafts/${nextExp}.md`, `ROUND=${round}`,
      `대응 리포트(수정 전) ${ROOT}/drafts/${repCur}.md`,
      `감사 파일: ${['fact', 'style', 'coverage'].map(k => `${ROOT}/audit/${expCur}_audit_${k}.md`).join(', ')}, ${readerFile}`,
      ...(gapNote ? [gapNote] : []), `GAPS=${ROOT}/_work/gaps/${P}_fixer_r${round}_explainer.json`,
      `로그 ${ROOT}/audit/${nextExp}_fix_log.md`]),
      { label: `fix:${nextExp}`, phase: 'Audit', effort: MED, schema: DONE_SCHEMA }),
  ])
  if (!fixed[0] || !fixed[0].ok || !fixed[1] || !fixed[1].ok) throw new Error(`수정 실패 라운드 ${round}`)
  repCur = nextRep
  expCur = nextExp
}

// ---------- Harmonize + 결정론 게이트 ----------
phase('Harmonize')
const hRep = bump(repCur)
const hExp = bump(expCur)
const harm = await agent(head('harmonizer', [
  `리포트 IN=${ROOT}/drafts/${repCur}.md → OUT=${ROOT}/drafts/${hRep}.md`,
  `해설본 IN=${ROOT}/drafts/${expCur}.md → OUT=${ROOT}/drafts/${hExp}.md`,
  `최신 감사 파일 ${ROOT}/audit/ 참조, 결정 목록 ${ROOT}/audit/${P}_harmonize_log.md`]),
  { label: 'harmonizer', phase: 'Harmonize', effort: MED, schema: DONE_SCHEMA })
if (!harm || !harm.ok) throw new Error('Harmonizer 실패')
const gateFix = (name, kind) => () => agent([
  `ROOT=${ROOT}`, `PHASE=${P}`,
  `결정론 게이트 수정 담당. ${ROLES}/_common.md 5절(금지 토큰)과 ${PKG}/STYLE_BRIEF.md 를 먼저 읽으십시오.`,
  `Bash로 실행: cd ${PROJECT} && uv run python -m indepth_analysis.skills.euro_macro.monthly_brief.finalize gate --root ${ROOT} --file ${ROOT}/drafts/${name}.md --kind ${kind}${A.hasPending ? ' --allow-pending' : ''}`,
  `status 가 FAIL 이면 blocks 항목만 최소 수정(의미 보존: 금지 토큰은 독자용 표현으로 대체, 조사 라벨·파이프라인 용어 삭제, 상대 날짜는 절대 날짜로, 없는 차트·표 참조는 삭제)해 같은 파일을 제자리 수정하고 재실행 — PASS/WARN 이 될 때까지 최대 4회. 분량 WARN은 부족이 15%를 넘을 때만 기존 근거로 보강.`,
  `output 에 최종 status·잔존 WARN 기록.`,
].join('\n'), { label: `gate:${name}`, phase: 'Harmonize', effort: MED, schema: DONE_SCHEMA })
const gates = await parallel([gateFix(hRep, 'report'), gateFix(hExp, 'explainer')])
log(`게이트: 리포트 ${gates[0] ? gates[0].output : 'ERR'} / 해설본 ${gates[1] ? gates[1].output : 'ERR'}`)

// ---------- Editorial ----------
phase('Editorial')
await agent(head('editorial', [
  `최종 후보 ${ROOT}/drafts/${hRep}.md · ${ROOT}/drafts/${hExp}.md`,
  `출력 ${ROOT}/_editorial/${P}_editorial.md`]),
  { label: 'editorial', phase: 'Editorial', effort: MED, schema: DONE_SCHEMA })

return { report: hRep, explainer: hExp, gates }
