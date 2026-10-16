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
const { AssignedFitmentPresentation } = require('../components/screens/fitment/AssignedFitmentReview.tsx');
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
  requests: [{ request_id: 'REQ-1', title: 'AI service sales guide', status: 'NEEDS_RECOMMENDATION' }],
  execution: { execution_id: 'run-1', request_id: 'REQ-1', status: 'READY_FOR_REVIEW', clarification_questions: [], events: [], proposals: [] },
  proposal: { proposal_id: 'PP-1', request_id: 'REQ-1', execution_id: 'run-1', proposal_version: 1, status: 'READY_FOR_REVIEW', stale: 'N',
    starts_on: '2026-09-21', ends_on: '2026-09-25', total_hours: 24, lead_count: 1, member_count: 2, policy_version: 'staffing-utilization-v1',
    rationale: '24 person-hours across three people, with complete capability coverage.', members,
    selection_review: { revision: 0, selection_id: null, members, original_members: members, alternatives,
      rationale: '24 person-hours across three people. Selected workload includes confirmed assignments and external commitments.', notes: [], search_exhaustive: true, reserves_capacity: false } },
  loading: false, busy: false, running: false, error: '', canRun: true, canDecide: true, decision: null, reason: '',
  onRun() {}, onRefresh() {}, onSelect() {}, onReason() {}, onDecision() {}, onSaveDecision() {}, onCancelDecision() {}, onReplacement() {}, onRecalculate() {} };
function markup(extra = {}) { return renderToStaticMarkup(React.createElement(LiveFitmentPresentation, { ...props, ...extra })); }

const assignedSnapshot = {
  requests: [{ request_id: 'REQ-1', title: 'AI service sales guide', status: 'STAFFED', planned_start_on: '2026-09-21',
    planned_end_on: '2026-09-25' }],
  assignments: [{ assignment_id: 'A-1', request_id: 'REQ-1', person_id: 'P-1', full_name: 'Lead One', role_in_pod: 'POD_LEAD',
    responsibilities: 'Coordinate project delivery.', status: 'CONFIRMED', staffing_method: 'AGENT_RECOMMENDATION' },
  { assignment_id: 'A-2', request_id: 'REQ-1', person_id: 'P-2', full_name: 'Member Two', role_in_pod: 'POD_MEMBER',
    responsibilities: 'Review the deck.', status: 'CONFIRMED', assigned_hours: 8, starts_on: '2026-09-21', ends_on: '2026-09-25',
    staffing_method: 'AGENT_RECOMMENDATION' }],
};
function assignedMarkup(overrides = {}) {
  return renderToStaticMarkup(React.createElement(AssignedFitmentPresentation, {
    snapshot: assignedSnapshot, error: '', activeRequestId: 'REQ-1', personId: 'P-2', details: context.data.requests,
    onRefresh() {}, onSelect() {}, ...overrides,
  }));
}

test('assigned fitment renders the approved roster and permitted own work without action or ranking controls', () => {
  const html = assignedMarkup();
  assert.match(html, /AI fitment review/);
  assert.match(html, /Read-only review/);
  assert.match(html, /Your assigned request/);
  assert.match(html, /Lead One/);
  assert.match(html, /Member Two/);
  assert.match(html, /Your assignment/);
  assert.match(html, /8 originally planned hours/);
  assert.match(html, /Review the deck/);
  assert.match(html, /Key deliverables/);
  assert.match(html, /Agent recommendation approved by a Captain/);
  assert.doesNotMatch(html, /<button[^>]*>[^<]*(Approve|Reject|Re-run|Close project|Manual override)|Alternative Leads|AI recommendation|Fit score/);
  // No fabricated zero hours or zero score for the redacted Lead roster row.
  assert.equal((html.match(/originally planned hours/g) ?? []).length, 1);
  assert.doesNotMatch(html, /0 originally planned hours|0% allocated/);
});

test('assigned request picker cannot be expanded by stale active IDs or unrelated request metadata', () => {
  const html = assignedMarkup({ activeRequestId: 'SECRET', details: [...context.data.requests,
    { ...context.data.requests[0], id: 'SECRET', title: 'Private unrelated request', businessObjectives: 'Private objective' }] });
  assert.match(html, /AI service sales guide/);
  assert.doesNotMatch(html, /Private unrelated request|Private objective|SECRET/);
  const empty = assignedMarkup({ snapshot: { requests: [], assignments: [] } });
  assert.match(empty, /No approved PODs are assigned to you yet/);
  assert.doesNotMatch(empty, /Lead One|Member Two|AI service sales guide|Your assigned request/);
});

test('assigned fitment distinguishes closed history, manual staffing and lead-only teams', () => {
  const html = assignedMarkup({ personId: 'P-1', snapshot: {
    requests: [{ ...assignedSnapshot.requests[0], status: 'CLOSED' }],
    assignments: [{ ...assignedSnapshot.assignments[0], status: 'CLOSED', staffing_method: 'MANUAL_OVERRIDE' }],
  } });
  assert.match(html, /Approved POD · Project closed/);
  assert.match(html, /Captain manual override/);
  assert.match(html, /No POD Members requested/);
  assert.doesNotMatch(html, /awaiting|pending recommendation will|Approve pod|Close project/);
});

test('assigned fitment loading and errors never fall back to preview recommendations', () => {
  assert.match(assignedMarkup({ snapshot: null }), /Loading your assigned PODs/);
  const html = assignedMarkup({ snapshot: null, error: 'Access is not permitted. Refresh your session.' });
  assert.match(html, /role="alert"/);
  assert.match(html, /Refresh your session/);
  assert.doesNotMatch(html, /Lead One|Member Two|AI service sales guide/);
  const screen = fs.readFileSync(path.join(root, 'components/screens/fitment/AiFitmentScreen.tsx'), 'utf8');
  assert.match(screen, /\['POD Lead', 'POD Member'\].*return <AssignedFitmentReview/);
  assert.doesNotMatch(screen, /RequestsScreen/);
  const source = fs.readFileSync(path.join(root, 'components/screens/fitment/AssignedFitmentReview.tsx'), 'utf8');
  assert.match(source, /useLiveWorkspace\('AI_FITMENT'\)/);
  assert.doesNotMatch(source, /LiveStaffingReview|resolveFitmentRecommendations|staffingFetch|onDecision|onReplacement/);
});

test('proxy forwards read-only AI_FITMENT workspace scope and retains backend denial', async () => {
  forwarded = [];
  const originalBackend = backend;
  const { StaffingApiError } = require('../lib/errors/staffing-api-error.ts');
  try {
    backend = async (...args) => { forwarded.push(args); return assignedSnapshot; };
    const req = new NextRequest('http://127.0.0.1:3001/api/agentic/workspace?resource=AI_FITMENT');
    const ctx = { params: Promise.resolve({ path: ['workspace'] }) };
    const response = await GET(req, ctx);
    assert.equal(response.status, 200);
    assert.equal(forwarded[0][1], '/v1/workspace?resource=AI_FITMENT');
    assert.match(response.headers.get('cache-control'), /no-store/);
    backend = async () => { throw new StaffingApiError('Not permitted.', 403, 'FORBIDDEN'); };
    assert.equal((await GET(req, ctx)).status, 403);
    assert.equal((await POST(new NextRequest(req.url, { method: 'POST', body: '{}' }), ctx)).status, 404);
  } finally { backend = originalBackend; }
});
test('completed lead-only recommendation does not promise another member recommendation', () => {
  const html = markup({ proposal: { ...props.proposal, member_count: 0, members: [members[0]], selection_review: undefined } });
  assert.match(html, /No POD Members requested\./);
  assert.doesNotMatch(html, /A validated recommendation will appear after fitment completes/);
  assert.match(html, /Mara Bennett/);
});

test('manual preview error is persistent inside the editor, actionable, and replaces green readiness', () => {
  const html = renderToStaticMarkup(React.createElement(ManualPodEditor, {
    people: [{ person_id: 'P-1', full_name: 'Lead One', role_codes: ['POD_LEAD'] }], selected: [],
    slots: [{ person_id: 'P-1', role: 'POD_LEAD', manual: true }], leadCount: 1, memberCount: 0, busy: false,
    error: 'This team exceeds 100% of contracted hours. Change people, dates or effort.', onClose() {}, onPreview() {},
  }));
  assert.match(html, /role="alert"/);
  assert.match(html, /Preview could not be calculated/);
  assert.match(html, /Change people, dates or effort/);
  assert.match(html, /No assignments are created until you approve a saved preview/);
  assert.match(html, /Retry preview/);
  assert.doesNotMatch(html, /staffing-manual-readiness ready|ready for allocation preview/);
  const source = fs.readFileSync(path.join(root, 'components/screens/fitment/LiveStaffingReview.tsx'), 'utf8');
  assert.match(source, /setManualError\(message\)/);
  assert.match(source, /error=\{manualError\} onChange=\{\(\) => setManualError\(''\)\}/);
});

test('calculating a valid manual choice does not show green ready status', () => {
  const html = renderToStaticMarkup(React.createElement(ManualPodEditor, {
    people: [{ person_id: 'P-1', full_name: 'Lead One', role_codes: ['POD_LEAD'] }], selected: [],
    slots: [{ person_id: 'P-1', role: 'POD_LEAD', manual: true }], leadCount: 1, memberCount: 0, busy: true,
    onClose() {}, onPreview() {},
  }));
  assert.match(html, /Checking the selected team/);
  assert.doesNotMatch(html, /staffing-manual-readiness ready|ready for allocation preview/);
});

test('Ask AI Pod is not mounted in the application shell, but its implementation is retained', () => {
  const shell = fs.readFileSync(path.join(root, 'components/shell/AppShell.tsx'), 'utf8');
  assert.doesNotMatch(shell, /AskAiPod|staffing-ask-btn/);
  assert.ok(fs.existsSync(path.join(root, 'components/chat/AskAiPod.tsx')));
});
test('a failed rerun fences the earlier ready recommendation and labels it as history', () => {
  const { agentProposalIsCurrent } = require('../lib/live-presentation.ts');
  const original = { ...props.proposal, execution_id: 'run-1' };
  assert.equal(agentProposalIsCurrent(original, { execution_id: 'run-1', status: 'READY_FOR_REVIEW' }), true);
  for (const status of ['NO_FEASIBLE_POD', 'FAILED', 'RUNNING', 'READY_FOR_REVIEW']) {
    assert.equal(agentProposalIsCurrent(original, { execution_id: 'run-2', status }), false);
  }
  assert.equal(agentProposalIsCurrent({ ...original, status: 'APPROVED' }, null), true);
  assert.equal(agentProposalIsCurrent({ ...original, origin: 'MANUAL_DRAFT' }, null), true);
  const html = markup({ canDecide: false, proposal: { ...original, stale: 'Y', stale_reason: 'Latest execution found no feasible POD.' } });
  assert.match(html, /Previous recommendation — historical only/);
  assert.match(html, /Latest execution found no feasible POD/);
  assert.doesNotMatch(html, />Approve pod</);
  assert.doesNotMatch(markup({ executionView: true, execution: { ...props.execution, execution_id: 'run-2', status: 'NO_FEASIBLE_POD' }, proposal: { ...original, stale: 'Y' } }), /Ready for review/);
});

test('failed and infeasible runs never present historical teams as current recommendations', () => {
  for (const executionView of [false, true]) {
    for (const status of ['NO_FEASIBLE_POD', 'FAILED', 'NEEDS_INFORMATION', 'SUPERSEDED']) {
      const html = markup({ executionView, canDecide: true, decision: 'APPROVED',
        execution: { ...props.execution, execution_id: 'run-2', status, last_error_code: status, last_error_summary: 'Latest run outcome.' } });
      assert.match(html, /Previous recommendation — historical only/);
      assert.match(html, /<details><summary>/); // History is collapsed by default.
      assert.doesNotMatch(html, /<details open/);
      assert.match(html, /Mara Bennett · POD Lead · 8 hours in the saved plan/);
      assert.doesNotMatch(html, /AI recommendation|staffing-candidate selected|Recommended Lead and eligible alternatives|How the recommendation was formed|Alternative Leads|Fit score|aria-label="Select |Approve pod|Confirm final assignment/);
      if (status === 'NO_FEASIBLE_POD') assert.match(html, /No feasible POD found in the latest run/);
      if (status === 'FAILED') assert.match(html, /The latest staffing run failed/);
    }
  }
});

test('explicit API history, refreshed results and saved manual previews stay separate', () => {
  const { staffingProposalState } = require('../lib/live-presentation.ts');
  const old = { ...props.proposal, stale: 'Y' };
  const partition = staffingProposalState(old, props.execution);
  assert.equal(partition.currentProposal, null);
  assert.equal(partition.previousProposal, old);
  const html = markup({ proposal: null, previousProposal: old, execution: { ...props.execution, status: 'NO_FEASIBLE_POD' } });
  assert.match(html, /No feasible POD found in the latest run/);
  assert.match(html, /Previous recommendation — historical only/);
  assert.doesNotMatch(html, /AI recommendation|Approve pod/);
  const current = markup({ previousProposal: null });
  assert.match(current, /AI recommendation/);
  assert.match(current, /Approve pod/);
  assert.doesNotMatch(current, /historical only|No feasible POD/);
  const manual = markup({ ...manualProps, execution: { ...props.execution, execution_id: 'run-2', status: 'NO_FEASIBLE_POD' } });
  assert.match(manual, /Captain manual preview/);
  assert.match(manual, /Approve pod/);
  assert.doesNotMatch(manual, /No feasible POD found in the latest run/);
});

test('approval and closure keep older execution history without requesting another run', () => {
  const { staffingReviewState } = require('../lib/live-presentation.ts');
  const execution = { request_id: 'REQ-1', request_revision: 3, status: 'READY_FOR_REVIEW',
    events: [], clarification_questions: [], proposals: [] };
  for (const status of ['STAFFED', 'CLOSED']) {
    const request = { ...props.request, status, request_revision: 4 };
    const state = staffingReviewState(request, execution);
    assert.equal(state.needsNewExecution, false);
    assert.equal(state.showExecution, true);
    for (const run of [execution, null]) {
      const html = markup({ request, execution: run, canDecide: false,
        proposal: { ...props.proposal, status: 'APPROVED', selection_review: undefined } });
      assert.match(html, status === 'STAFFED' ? /Staffed · Assignments approved/ : /Project closed · Staffing history retained/);
      assert.doesNotMatch(html, /Awaiting execution|Waiting for AI staffing to start/);
      assert.equal(html.includes('View execution history'), Boolean(run));
      const history = markup({ request, execution: run, executionView: true, canDecide: false });
      assert.match(history, /no new staffing run is required/);
    }
  }
  for (const status of ['NEEDS_RECOMMENDATION', 'IN_REVIEW']) {
    assert.equal(staffingReviewState({ ...props.request, status, request_revision: 4 }, execution).needsNewExecution, true);
    assert.equal(staffingReviewState({ ...props.request, status, request_revision: 4 }, execution).showExecution, false);
  }
  assert.equal(staffingReviewState({ ...props.request, request_revision: 3 }, execution).showExecution, true);
  assert.equal(staffingReviewState(props.request, { ...execution, request_id: 'OTHER' }).showExecution, false);
  assert.equal(staffingReviewState(undefined, null).needsNewExecution, false);
});
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

test('Why this POD is structured and uses saved facts instead of the raw rationale', () => {
  const html = markup({ proposal: { ...props.proposal, rationale: 'RAW LONG RATIONALE WITH 999% ALLOCATION',
    selection_review: { ...props.proposal.selection_review, rationale: 'RAW LONG RATIONALE WITH 999% ALLOCATION' } } });
  assert.match(html, /Why this POD/);
  assert.match(html, /Mara Bennett will lead the work, supported by Alex Rivera and Carlos Reed/);
  assert.match(html, /24h of planned work is split equally/);
  assert.match(html, /aria-label="Planned team contributions"/);
  assert.match(html, /Sep 21, 2026 – Sep 25, 2026/);
  assert.match(html, /Total planned effort/);
  assert.match(html, /Capacity is reserved only after approval/);
  assert.doesNotMatch(html, /RAW LONG RATIONALE|999%/);
});

test('polished wording and changed selections cannot replace authoritative figures', () => {
  const selected = [alternatives[0].member, ...members.slice(1)];
  const html = markup({ proposal: { ...props.proposal,
    explanation_copy: { opening: 'team_first', effort: 'total_first', source: 'fallback' },
    selection_review: { ...props.proposal.selection_review, members: selected,
      explanation_copy: { version: 1, opening: 'work_first', effort: 'people_first', source: 'llm' } } } });
  const why = html.slice(html.indexOf('staffing-pod-explanation"'));
  assert.match(why, /The work will be led by Elena Garcia/);
  assert.match(why, /3-person team is scheduled for 24h/);
  assert.match(why, />8h</);
  assert.match(why, />70%</);
  assert.doesNotMatch(why, /Mara Bennett/);
});

test('Why this POD distinguishes unequal contributions, unknown allocation and manual exceptions', () => {
  const { WhyThisPod } = require('../components/screens/fitment/WhyThisPod.tsx');
  const changed = [ { ...members[0], planned_hours: 12 }, { ...members[1], planned_hours: 8 },
    { ...members[2], planned_hours: 4, factors: {} } ];
  const html = renderToStaticMarkup(React.createElement(WhyThisPod, { proposal: { ...props.proposal, members: changed } }));
  assert.match(html, /plan assigns 24h across 3 people/);
  assert.match(html, /Not recorded/);
  assert.doesNotMatch(html, /split equally|>0%</);
  const manual = renderToStaticMarkup(React.createElement(WhyThisPod, manualProps));
  assert.match(manual, /POD-only utilization/);
  assert.match(manual, /Manual choices bypass skill matching/);
  assert.doesNotMatch(manual, /accounting for recorded skills, leave and existing commitments/);
  const approved = renderToStaticMarkup(React.createElement(WhyThisPod, { proposal: { ...props.proposal, status: 'APPROVED' } }));
  assert.match(approved, /These assignments are approved/);
  assert.doesNotMatch(approved, /Capacity is reserved only after approval/);
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
test('fitment shows automatic waiting feedback until the queued recommendation arrives', () => {
  const execution = { execution_id: 'EX-1', request_id: 'REQ-1', status: 'RUNNING', clarification_questions: [], events: [], proposals: [] };
  const html = markup({ proposal: null, execution, running: true, canDecide: false });
  assert.match(html, /staffing-fitment-waiting/);
  assert.match(html, /Building the staffing recommendation/);
  assert.match(html, /This page refreshes automatically/);
  assert.match(html, /aria-busy="true"/);
});
test('successful request creation selects the new request and opens AI Fitment', () => {
  const source = fs.readFileSync(path.join(root, 'components/overlays/CreateRequestModal.tsx'), 'utf8');
  const success = source.slice(source.indexOf('formElement.reset()'), source.indexOf('} catch {'));
  assert.match(success, /set-active-request[^\n]+result\.data\.requestId/);
  assert.match(success, /set-screen[^\n]+screen: 'fitment'/);
  assert.doesNotMatch(success, /screen: 'agent'/);
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
  const people = [{ person_id: 'P-1', full_name: 'Lead One', role_codes: ['POD_LEAD'] }, { person_id: 'P-4', full_name: 'Member One', role_codes: ['POD_MEMBER'] }];
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

test('roster endpoints remain explicitly allowlisted with no recovery/reset web endpoint', async () => {
  backend = async (...args) => { forwarded.push(args); return { status: 'COMPLETE' }; };
  for (const path of [['onboarding'], ['admin', 'accounts', 'ACC-1', 'access']]) {
    forwarded = [];
    const body = { reason: 'Operator review' };
    const response = await POST(new NextRequest(`http://127.0.0.1:3001/api/agentic/${path.join('/')}`, { method: 'POST', body: JSON.stringify(body) }), { params: Promise.resolve({ path }) });
    assert.equal(response.status, 200);
    assert.deepEqual(forwarded[0].slice(1), [`/v1/${path.join('/')}`, 'POST', body]);
    assert.match(response.headers.get('cache-control'), /no-store/);
  }
  forwarded = [];
  const retired = await POST(new NextRequest('http://127.0.0.1:3001/api/agentic/baseline-pods/RC1/review', { method: 'POST', body: '{}' }),
    { params: Promise.resolve({ path: ['baseline-pods', 'RC1', 'review'] }) });
  assert.equal(retired.status, 404); assert.equal(forwarded.length, 0);
  for (const path of [['admin', 'reset'], ['roster', 'archive'], ['admin', 'accounts', 'ACC-1', 'password']]) {
    const response = await POST(new NextRequest('http://127.0.0.1:3001/api/agentic/unknown', { method: 'POST', body: '{}' }), { params: Promise.resolve({ path }) });
    assert.equal(response.status, 404);
  }
});

if (process.argv.includes('--preview') || process.argv.includes('--manual-preview')) {
  require('node:http').createServer((_req, res) => {
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' });
    res.end(`<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"><style>body{margin:0}${fs.readFileSync(path.join(root, 'styles/react-foundation.css'), 'utf8')}</style></head><body><div class="staffing-shell"><div style="padding:28px;max-width:1500px;margin:auto">${markup(process.argv.includes('--manual-preview') ? manualProps : {})}</div></div></body></html>`);
  }).listen(3028, '127.0.0.1', () => console.log('Synthetic UI review at http://127.0.0.1:3028 (no database/auth/OCI)'));
}
