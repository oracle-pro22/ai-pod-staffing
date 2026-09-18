/* Offline SSR and Next proxy tests. --preview serves only this synthetic fixture. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const root = path.resolve(__dirname, '..');
const nativeLoad = Module._load;
let forwarded = [];
let backend = async (...args) => { forwarded.push(args); return { revision: 1 }; };
const context = { data: { requests: [{ id: 'REQ-1', title: 'AI service sales guide', projectType: { name: 'New Service Launch' },
  priority: 'Medium', neededBy: '2026-09-25', deliverables: [{ name: 'Sales Guide (deck)' }], requiredSkills: [{ id: 'GTM', name: 'GTM SME' }],
  businessObjectives: 'Help sales explain the service accurately.', expectedOutcomes: 'A reviewed customer-ready sales deck.',
  estimatedHours: 24 }], people: [] }, dispatch() {} };
Module._load = function(id, parent, main) {
  if (id === 'server-only') return {};
  if (id === '@/context/StaffingAppProvider') return { useStaffingApp: () => context };
  if (id === '@/backend/staffing/bridge') return { staffingBackend: (...args) => backend(...args) };
  if (id.startsWith('@/')) id = path.join(root, id.slice(2));
  return nativeLoad.call(this, id, parent, main);
};
for (const extension of ['.ts', '.tsx']) require.extensions[extension] = (mod, filename) => mod._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true }, fileName: filename,
}).outputText, filename);
const { LiveFitmentPresentation } = require('../components/screens/fitment/LiveFitmentPresentation.tsx');
const { ManualPodEditor, manualPeopleForSlot } = require('../components/screens/fitment/ManualPodEditor.tsx');
const { POST, GET } = require('../app/api/agentic/[...path]/route.ts');
const { NextRequest } = require('next/server');
function member(id, name, role = 'POD_MEMBER', source = 'RECOMMENDED') {
  return { person_id: id, full_name: name, role_in_pod: role, planned_hours: 8, score: 86.5, source,
    active_pods: 1, active_pods_as_of: '2026-09-17', responsibilities: 'Contribute to Sales Guide (deck); 8 planned hours. Recorded capability coverage: GTM SME.',
    factors: { scheduling_algorithm: 'available-days-v2', current_window_allocation_pct: '50', window_allocation_pct: '70',
      projected_allocation_pct: '70', peak_week_start: '2026-09-21', factors: { skill: '40', deliverable: '30', capacity: '11.5', interest: '5' } } };
}
const members = [member('P-1', 'Mara Bennett', 'POD_LEAD'), member('P-4', 'Alex Rivera'), member('P-5', 'Carlos Reed')];
const alternatives = [
  ...['Elena Garcia', 'Priya Nair'].map((name, i) => ({ replaces: 'P-1', role: 'POD_LEAD', member: member(`P-${i+2}`, name, 'POD_LEAD', 'ALTERNATIVE') })),
  ...['Ava Morgan', 'Noah Foster'].flatMap((name, i) => ['P-4', 'P-5'].map(replaces => ({ replaces, role: 'POD_MEMBER', member: member(`P-${i+6}`, name, 'POD_MEMBER', 'ALTERNATIVE') }))),
];
const props = { executionView: false, request: { request_id: 'REQ-1', title: 'AI service sales guide', status: 'NEEDS_RECOMMENDATION', responsible_captain_id: 'P-10' },
  requests: [{ request_id: 'REQ-1', title: 'AI service sales guide', status: 'NEEDS_RECOMMENDATION' }], execution: null,
  proposal: { proposal_id: 'PP-1', request_id: 'REQ-1', proposal_version: 1, status: 'READY_FOR_REVIEW', stale: 'N',
    starts_on: '2026-09-21', ends_on: '2026-09-25', total_hours: 24, lead_count: 1, member_count: 2, policy_version: 'staffing-utilization-v1',
    rationale: '24 person-hours across three people, with complete capability coverage.', members,
    selection_review: { revision: 0, selection_id: null, members, original_members: members, alternatives,
      rationale: '24 person-hours across three people. Selected workload includes confirmed assignments and external commitments.', notes: [], search_exhaustive: true, reserves_capacity: false } },
  loading: false, busy: false, running: false, error: '', canRun: true, canDecide: true, decision: null, reason: '',
  onRun() {}, onRefresh() {}, onSelect() {}, onReason() {}, onDecision() {}, onSaveDecision() {}, onCancelDecision() {}, onReplacement() {}, onRecalculate() {} };
function markup(extra = {}) { return renderToStaticMarkup(React.createElement(LiveFitmentPresentation, { ...props, ...extra })); }
const manualMember = { ...member('P-1', 'Mara Bennett', 'POD_LEAD', 'MANUAL'), score: null, planned_hours: 16,
  responsibilities: 'Captain-assigned work. Skills and experience overridden.',
  factors: { scheduling_algorithm: 'available-days-v2', allocation_basis: 'POD_ONLY_CONTRACTED',
    current_window_allocation_pct: '60', window_allocation_pct: '100', projected_allocation_pct: '100',
    ignored_leave_hours: '8', ignored_external_hours: '8', reported_workload: { window_allocation_pct: '150', projected_allocation_pct: '150' } } };
const manualProps = { proposal: { ...props.proposal, proposal_id: 'MD-1', origin: 'MANUAL_DRAFT', selection_review: undefined,
  members: [manualMember, ...members.slice(1).map(m => ({ ...m, planned_hours: 4,
    responsibilities: 'Contribute to Sales Guide (deck); 4 planned hours.',
    factors: { ...m.factors, window_allocation_pct: '60', projected_allocation_pct: '60' } }))],
  rationale: 'Captain-selected POD; 24 hours across three people. No assignments until approval.' }, canManual: true, canRun: false,
  onManual() {}, onDiscardManual() {} };

test('fitment keeps theme, selected recommendations and two distinct alternatives per group', () => {
  const html = markup();
  assert.match(html, /staffing-fit-layout/);
  assert.match(html, /staffing-fit-results/);
  assert.match(html, /staffing-selection-summary-head/);
  assert.equal((html.match(/AI recommendation/g) ?? []).length, 3);
  assert.equal((html.match(/staffing-candidate selected recommended/g) ?? []).length, 3);
  for (const name of ['Elena Garcia', 'Priya Nair', 'Ava Morgan', 'Noah Foster']) {
    assert.equal((html.match(new RegExp(`aria-label="Select ${name}"`, 'g')) ?? []).length, 1);
  }
  assert.equal((html.match(/>Select<\/button>/g) ?? []).length, 4);
  assert.doesNotMatch(html, /Person replaced by/);
  assert.match(html, /Original recommendation/);
  assert.match(html, /No capacity is reserved until approval/);
  assert.doesNotMatch(html, /Manual override/);
});
test('Captain changes use the saved team in final confirmation without hiding the original', () => {
  const selected = [alternatives[0].member, ...members.slice(1)];
  const proposal = { ...props.proposal, selection_review: { ...props.proposal.selection_review, revision: 1, selection_id: 'SD-1', members: selected } };
  const html = markup({ proposal, decision: 'APPROVED' });
  assert.match(html, /Captain-selected alternative/);
  assert.match(html, /Saved selection 1/);
  const modal = html.slice(html.indexOf('role="dialog"'));
  assert.match(modal, /Elena Garcia — 8 hours/);
  assert.doesNotMatch(modal, /Mara Bennett —/);
  assert.match(modal, /70% peak week/);
});
test('read-only viewer and busy saves disable all replacement controls', () => {
  for (const extra of [{ canDecide: false }, { busy: true }]) {
    const html = markup(extra);
    for (const button of html.matchAll(/<button[^>]*aria-label="Select [^"]+"[^>]*>Select<\/button>/g)) assert.match(button[0], /disabled=""/);
  }
});
test('short pools show the saved shortage message without fabricated choices', () => {
  const proposal = { ...props.proposal, selection_review: { ...props.proposal.selection_review, alternatives: [], notes: ['No additional Lead fits this team.'] } };
  const html = markup({ proposal });
  assert.match(html, /No additional Lead fits this team/);
  assert.doesNotMatch(html, /aria-label="Select Elena Garcia"/);
});
test('execution screen identifies Supervisor and both specialist responsibilities', () => {
  const html = markup({ executionView: true });
  assert.match(html, /Supervisor/);
  assert.match(html, /Request \/ Evidence Analyst/);
  assert.match(html, /POD Planner and rules/);
});
test('Next proxy permits only the scoped selection POST and preserves payload', async () => {
  forwarded = [];
  const body = { revision: 0, person_id: 'P-2', replaces: 'P-1', role: 'POD_LEAD', idempotency_key: 'choice-0000000001' };
  const response = await POST(new NextRequest('http://127.0.0.1:3001/api/agentic/proposals/PP-1/selection', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }), { params: Promise.resolve({ path: ['proposals', 'PP-1', 'selection'] }) });
  assert.equal(response.status, 200);
  assert.deepEqual(forwarded[0].slice(1), ['/v1/proposals/PP-1/selection', 'POST', body]);
  assert.match(response.headers.get('cache-control'), /no-store/);
  const read = await GET(new NextRequest('http://127.0.0.1:3001/api/agentic/proposals/PP-1/selection'), { params: Promise.resolve({ path: ['proposals', 'PP-1', 'selection'] }) });
  assert.equal(read.status, 404);
});
test('selection conflict is not converted to a success by the Next server', async () => {
  const { StaffingApiError } = require('../lib/errors/staffing-api-error.ts');
  const original = backend;
  backend = async () => { throw new StaffingApiError('Refresh the selection.', 409, 'STALE_SELECTION'); };
  try {
    const response = await POST(new NextRequest('http://127.0.0.1:3001/api/agentic/proposals/PP-1/selection', {
      method: 'POST', body: JSON.stringify({ revision: 0, idempotency_key: 'choice-0000000001' }),
    }), { params: Promise.resolve({ path: ['proposals', 'PP-1', 'selection'] }) });
    assert.equal(response.status, 409);
    assert.equal((await response.json()).code, 'STALE_SELECTION');
  } finally { backend = original; }
});

test('manual preview labels the 100% POD-only basis and uncapped reported workload separately', () => {
  const html = markup(manualProps);
  assert.match(html, /Captain manual preview/);
  assert.match(html, /Captain manual override/);
  assert.match(html, /100% POD-only, max 100%/);
  assert.match(html, /150% in the request period/);
  assert.match(html, /8 leave hours and 8 external-work hours/);
  assert.match(html, /Not AI-ranked/);
  assert.doesNotMatch(html, /Fit score null|Average score contribution|Effort-weighted score contribution/);
  assert.match(html, /Discard manual draft/);
  assert.doesNotMatch(html, /Awaiting execution|>View execution<|>▶ Run fitment</);
  assert.equal(manualProps.proposal.members.reduce((sum, m) => sum + m.planned_hours, 0), manualProps.proposal.total_hours);
});
test('manual final assignments are not presented as an agent result', () => {
  const html = markup({ ...manualProps, executionView: true, canDecide: false,
    proposal: { ...manualProps.proposal, status: 'APPROVED', origin: 'MANUAL' } });
  assert.match(html, /Captain-selected staffing result/);
  assert.doesNotMatch(html, />Agent result</);
});
test('manual approval confirmation includes the exact people and ignored workload warning', () => {
  const html = markup({ ...manualProps, decision: 'APPROVED' });
  const modal = html.slice(html.indexOf('role="dialog"'));
  assert.match(modal, /Mara Bennett — 16 hours/);
  assert.match(modal, /100% POD-only utilization/);
  assert.match(modal, /150% in the request period/);
  assert.match(modal, /No Lead or Member acceptance/);
});
test('full leave is displayed honestly, not as zero overall allocation', () => {
  const m = { ...manualMember, factors: { ...manualMember.factors, reported_workload: { window_allocation_pct: null, projected_allocation_pct: null } } };
  const html = markup({ ...manualProps, proposal: { ...manualProps.proposal, members: [m] } });
  assert.match(html, /No available capacity in the request period/);
  assert.doesNotMatch(html, /including those records: 0%/);
});
test('manual picker preserves role-sized slots and requires explicit preview', () => {
  const people = [{ person_id: 'P-1', full_name: 'Lead One', role_code: 'POD_LEAD' }, { person_id: 'P-4', full_name: 'Member One', role_code: 'POD_MEMBER' }];
  const html = renderToStaticMarkup(React.createElement(ManualPodEditor, {
    people,
    selected: [], leadCount: 1, memberCount: 2, busy: false, onClose() {}, onPreview() {},
  }));
  assert.equal((html.match(/aria-label="Manual POD_LEAD/g) ?? []).length, 1);
  assert.equal((html.match(/aria-label="Manual POD_MEMBER/g) ?? []).length, 2);
  assert.match(html, /Calculate preview/);
  assert.doesNotMatch(html, /Confirm final assignment|override reason/i);
  assert.equal((html.match(/role="combobox"/g) ?? []).length, 3);
  assert.equal((html.match(/placeholder="Search by name or ID"/g) ?? []).length, 3);
  assert.equal((html.match(/staffing-manual-slot"/g) ?? []).length, 3);
  assert.match(html, /Manual limit: 100% POD allocation/);
  assert.match(html, /Choose a person for every POD role/);
  const eligibleLeadNames = manualPeopleForSlot(people, [
    { person_id: '', role: 'POD_LEAD', manual: true },
    { person_id: '', role: 'POD_MEMBER', manual: true },
  ], 0).map(person => person.full_name);
  assert.deepEqual(eligibleLeadNames, ['Lead One']);
});
test('manual controls are absent for an unauthorized reader', () => {
  const html = markup({ ...manualProps, canManual: false, canDecide: false });
  assert.doesNotMatch(html, />Manual override<|>Discard manual draft<|>Approve pod</);
});
test('manual proxy preserves scoped paths, no-store, and refuses arbitrary role endpoints', async () => {
  for (const endpoint of ['manual-preview', 'manual-decision']) {
    forwarded = [];
    const body = { draft_id: 'MD-1', action: 'DISCARDED', idempotency_key: 'manual-request-0001' };
    const res = await POST(new NextRequest(`http://127.0.0.1:3001/api/agentic/requests/REQ-1/${endpoint}`, { method: 'POST', body: JSON.stringify(body) }),
      { params: Promise.resolve({ path: ['requests', 'REQ-1', endpoint] }) });
    assert.equal(res.status, 200); assert.deepEqual(forwarded[0].slice(1), [`/v1/requests/REQ-1/${endpoint}`, 'POST', body]);
    assert.match(res.headers.get('cache-control'), /no-store/);
  }
  for (const endpoint of ['manual', 'proposal']) {
    const res = await GET(new NextRequest(`http://127.0.0.1:3001/api/agentic/requests/REQ-1/${endpoint}`), { params: Promise.resolve({ path: ['requests', 'REQ-1', endpoint] }) });
    assert.equal(res.status, 200);
  }
  const res = await POST(new NextRequest('http://127.0.0.1:3001/api/agentic/manual/admin', { method: 'POST', body: '{}' }), { params: Promise.resolve({ path: ['manual', 'admin'] }) });
  assert.equal(res.status, 404);
});

if (process.argv.includes('--preview') || process.argv.includes('--manual-preview')) {
  require('node:http').createServer((_req, res) => {
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' });
    res.end(`<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"><style>body{margin:0}${fs.readFileSync(path.join(root, 'styles/react-foundation.css'), 'utf8')}</style></head><body><div class="staffing-shell"><div style="padding:28px;max-width:1500px;margin:auto">${markup(process.argv.includes('--manual-preview') ? manualProps : {})}</div></div></body></html>`);
  }).listen(3028, '127.0.0.1', () => console.log('Synthetic UI review at http://127.0.0.1:3028 (no database/auth/OCI)'));
}
