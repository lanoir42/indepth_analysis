export const meta = {
  name: 'euro-macro-monthly-v3-release-patch',
  description: '유럽 매크로 월간 리포트 v3 — 발표 대기 블록을 실제 발표치로 교체(리포트·해설본) → 수치 감사 → 게이트',
  whenToUse: '컨센서스 선반영 초안 이후 지표 발표가 끝났을 때. args: {root, phase, report, explainer} (drafts 파일 stem).',
  phases: [
    { title: 'Patch', detail: '리포트·해설본 발표 대기 블록 교체 (병렬)' },
    { title: 'Check', detail: '교체 부분 수치·논리 감사 → 필요 시 수정 → 게이트(대기 블록 불허)' },
  ],
}

const A = args || {}
const PKG = A.pkg || '/Users/lanoir42/projects/indepth_analysis/src/indepth_analysis/skills/euro_macro/monthly_brief'
const PROJECT = A.project || '/Users/lanoir42/projects/indepth_analysis'
const ROLES = `${PKG}/roles`
const ROOT = A.root
const P = A.phase
if (!ROOT || !P || !A.report || !A.explainer) throw new Error('args.root, phase, report, explainer 필수')
const DONE = { type: 'object', properties: { ok: { type: 'boolean' }, output: { type: 'string' }, note: { type: 'string' } }, required: ['ok', 'output'] }
const AUDIT = { type: 'object', properties: { verdict: { type: 'string', enum: ['PASS', 'FAIL'] }, high: { type: 'integer' }, medium: { type: 'integer' }, file: { type: 'string' } }, required: ['verdict', 'high', 'medium', 'file'] }
const head = (role, extra) => [`ROOT=${ROOT}`, `PHASE=${P}`, ...extra,
  `먼저 ${ROLES}/_common.md 와 ${ROLES}/${role}.md 를 읽고 그대로 수행하십시오. 회차 변수 ${ROOT}/edition.json.`].join('\n')
const out = (stem) => stem.replace(/_r(\w+)$/, '_rP')

phase('Patch')
const [rep, exp] = [out(A.report), out(A.explainer)]
const patched = await parallel([
  () => agent(head('release_patch', [`IN=${ROOT}/drafts/${A.report}.md (리포트)`, `OUT=${ROOT}/drafts/${rep}.md`]),
    { label: 'patch:report', phase: 'Patch', effort: 'high', schema: DONE }),
  () => agent(head('release_patch', [`IN=${ROOT}/drafts/${A.explainer}.md (해설본)`, `OUT=${ROOT}/drafts/${exp}.md`, `대응 리포트(교체 후) ${ROOT}/drafts/${rep}.md 가 생기면 수치를 맞출 것`]),
    { label: 'patch:explainer', phase: 'Patch', effort: 'medium', schema: DONE }),
])
if (!patched[0] || !patched[0].ok || !patched[1] || !patched[1].ok) throw new Error('patch 실패')
log(`patch: ${patched[0].note || ''} / ${patched[1].note || ''}`)

phase('Check')
const au = await agent(head('audit_fact', [`TARGET=${ROOT}/drafts/${rep}.md (풀 리포트) — 이번 점검 범위는 ${ROOT}/audit/${rep}_release_log.md 의 교체 위치와 요약·1장·9장. 교체 문장의 실제치·컨센서스·차이·판정이 data/pending_actuals.json·facts와 맞는지, 블록 밖 판단과 모순이 없는지`, `감사 파일 ${ROOT}/audit/${rep}_audit_fact.md`]),
  { label: 'audit:fact:patch', phase: 'Check', effort: 'medium', schema: AUDIT })
log(`감사: ${au ? `${au.verdict} H${au.high} M${au.medium}` : 'ERR'}`)
if (!au || au.high > 0) {
  await agent(head('fixer', [`IN=${ROOT}/drafts/${rep}.md`, `OUT=${ROOT}/drafts/${rep}.md (제자리 수정)`, `감사 파일 ${ROOT}/audit/${rep}_audit_fact.md`, `해설본 ${ROOT}/drafts/${exp}.md 의 같은 수치도 맞출 것(제자리 수정)`]),
    { label: 'fix:patch', phase: 'Check', effort: 'medium', schema: DONE })
}
const gate = (name, kind) => () => agent([`ROOT=${ROOT}`, `PHASE=${P}`,
  `결정론 게이트 수정 담당. ${ROLES}/_common.md 5·7절 참고. Bash: cd ${PROJECT} && uv run python -m indepth_analysis.skills.euro_macro.monthly_brief.finalize gate --root ${ROOT} --file ${ROOT}/drafts/${name}.md --kind ${kind}`,
  `FAIL이면 blocks만 최소 수정 후 재실행(최대 4회). 발표 대기 블록이 남았으면 data/pending_actuals.json 에 실제치가 있는지 확인해 release_patch 규칙으로 교체, 실제치가 없으면 그대로 두고 output 에 id 기록.`,
  `output 에 최종 status.`].join('\n'), { label: `gate:${name}`, phase: 'Check', effort: 'medium', schema: DONE })
const g = await parallel([gate(rep, 'report'), gate(exp, 'explainer')])
return { report: rep, explainer: exp, gates: g.map(x => x && x.output) }
