/* Offline UI regression tests. No browser, database or VM writes. */
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
const context = { data: { catalog: { skills: [{ id: 'SK-005', name: 'Portal SME' }] }, people: [], requests: [] },
  state: { role: 'POD Captain', activeRequestId: 'REQ-TEST' }, dispatch() {}, notify() {} };
const router = { refresh() {} };
let harness, requestRows, savedProposal, transport, calls;
const hookReact = { ...React,
  useState(initial) {
    const h = harness, i = h.index++;
    if (!(i in h.slots)) h.slots[i] = typeof initial === 'function' ? initial() : initial;
    return [h.slots[i], value => {
      const next = typeof value === 'function' ? value(h.slots[i]) : value;
      if (!Object.is(next, h.slots[i])) { h.slots[i] = next; h.dirty = true; }
    }];
  },
  useRef(initial) {
    const h = harness, i = h.index++;
    if (!(i in h.slots)) h.slots[i] = { current: initial };
    return h.slots[i];
  },
  useEffect(effect, deps) {
    const h = harness, i = h.index++;
    if (!h.slots[i] || deps.some((value, n) => value !== h.slots[i].deps[n])) {
      h.slots[i]?.cleanup?.();
      h.slots[i] = { deps };
      h.effects.push(() => { h.slots[i].cleanup = effect(); });
    }
  },
};
Module._load = function(id, parent, main) {
  if (id === 'react' && ['LiveStaffingReview.tsx', 'OnboardingEntry.tsx'].some(file => parent.filename.endsWith(file))) return hookReact;
  if (id === 'next/navigation') return { useRouter: () => router };
  if (id === '@/context/StaffingAppProvider') return { useStaffingApp: () => context };
  if (id === '@/lib/staffing-fetch') return { staffingFetch: (...args) => transport(...args) };
  if (id.startsWith('@/')) id = path.join(root, id.slice(2));
  return nativeLoad.call(this, id, parent, main);
};
for (const extension of ['.ts', '.tsx']) require.extensions[extension] = (mod, filename) => mod._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true }, fileName: filename,
}).outputText, filename);
const { capabilityText } = require('../lib/capability-text.ts');
const { CapabilityText } = require('../components/ui/CapabilityText.tsx');
const { AssignedFitmentPresentation } = require('../components/screens/fitment/AssignedFitmentReview.tsx');
const { LiveStaffingReview } = require('../components/screens/fitment/LiveStaffingReview.tsx');
const { LiveFitmentPresentation } = require('../components/screens/fitment/LiveFitmentPresentation.tsx');
const { announceStaffingChange, STAFFING_CHANGED_EVENT } = require('../lib/project-closure.ts');
const { OnboardingEntry } = require('../components/entry/OnboardingEntry.tsx');

test('first-login work and leave steps keep backend values, require final confirmation and never offer a POD claim', async () => {
  const previousWindow = global.window;
  const posted = [];
  const navigations = [];
  global.window = { location: { assign: url => navigations.push(url) } };
  transport = async (url, options) => {
    posted.push({ url, options });
    return new Response(JSON.stringify({ status: 'COMPLETE' }));
  };
  const h = { index: 0, slots: [], effects: [], dirty: false, tree: null };
  const render = () => {
    harness = h; h.index = 0; h.effects = [];
    h.tree = OnboardingEntry({ initial: { status: 'DRAFT', revision: 3, full_name: 'Demo person',
      daily_hours: 8, weekly_hours: 40, staffing_roles: ['POD_LEAD', 'POD_MEMBER'] }, sessionKey: 'test' });
    for (const effect of h.effects) effect();
  };
  const button = name => all(h.tree).find(node => node.type === 'button' && node.props.children === name);
  const typeFields = () => all(h.tree).filter(node => node.props?.label === 'Type');
  const input = label => all(h.tree).find(node => node.type === 'label' && node.props.children?.[0] === label).props.children[1];
  try {
    render(); button('Continue').props.onClick(); render();
    button('＋ Add work or leave').props.onClick(); render();
    assert.deepEqual(typeFields()[0].props.options, [
      { value: 'EXTERNAL', label: 'Current work' }, { value: 'LEAVE', label: 'Leave' },
    ], 'Even Lead/Member grants must not expose Existing POD work');
    assert.equal(typeFields()[0].props.value, 'EXTERNAL');
    input('Work or leave name').props.onChange({ target: { value: 'Customer support' } }); render();
    input('Total hours across these dates').props.onChange({ target: { value: '20' } }); render();
    button('＋ Add work or leave').props.onClick(); render();
    typeFields()[1].props.onChange('LEAVE'); render();
    const labels = all(h.tree).filter(node => node.type === 'label');
    labels.filter(node => node.props.children?.[0] === 'Work or leave name')[1].props.children[1].props.onChange({ target: { value: 'Planned leave' } }); render();
    all(h.tree).filter(node => node.type === 'label' && node.props.children?.[0] === 'Total hours across these dates')[1]
      .props.children[1].props.onChange({ target: { value: '8' } }); render();
    button('Continue').props.onClick(); render();
    assert.equal(posted.length, 0, 'Step navigation and typing must not save');
    assert.equal(button('Confirm and save profile').props.disabled, true);
    const reviewText = all(h.tree).filter(node => node.type === 'li').map(node => node.props.children.join('')).join(' ');
    assert.match(reviewText, /Customer support — Current work/);
    assert.match(reviewText, /Planned leave — Leave/);
    assert.doesNotMatch(reviewText, /EXTERNAL|Existing POD|POD_LEAD/);
    all(h.tree).find(node => node.type === 'input' && node.props.type === 'checkbox').props.onChange({ target: { checked: true } }); render();
    await all(h.tree).find(node => node.type === 'form').props.onSubmit({ preventDefault() {} });
    assert.equal(posted.length, 1);
    assert.equal(posted[0].url, '/api/agentic/onboarding');
    const body = JSON.parse(posted[0].options.body);
    assert.deepEqual(body.work.map(({ kind, total_hours, role_code }) => ({ kind, total_hours, role_code })), [
      { kind: 'EXTERNAL', total_hours: 20, role_code: null }, { kind: 'LEAVE', total_hours: 8, role_code: null },
    ]);
    assert.deepEqual(navigations, ['/']);
  } finally { global.window = previousWindow; }
});

test('all responsibility and recommendation descriptions use the shared skill-name display', () => {
  const surfaces = [
    'components/screens/command-center/CommandCenter.tsx',
    'components/screens/fitment/AssignedFitmentReview.tsx',
    'components/screens/fitment/LiveFitmentPresentation.tsx',
    'components/screens/fitment/AiFitmentScreen.tsx',
    'components/screens/agent-execution/AgentExecutionScreen.tsx',
    'components/screens/requests/FinalPodDetails.tsx',
    'components/screens/requests/LiveAssignments.tsx',
  ];
  for (const file of surfaces) {
    const source = fs.readFileSync(path.join(root, file), 'utf8');
    assert.match(source, /<CapabilityText>\{(?:\w+\.(?:responsibilities|rationale))\}<\/CapabilityText>/, file);
    assert.doesNotMatch(source, /<(?!CapabilityText\b)[\w.]+(?:\s[^>]*)?>\{\w+\.(?:responsibilities|rationale)\}</, file);
  }
});

test('capability labels replace exact catalogue IDs without rewriting other evidence or unknown IDs', () => {
  const source = 'Contribute for 4 planned hours. Recorded capability coverage: SK-005, SK-002. SK-005 (SK-999).';
  const skills = [{ id: 'SK-005', name: 'Portal SME' }, { id: 'SK-002', name: 'GTM SME' }];
  assert.equal(capabilityText(source, skills), 'Contribute for 4 planned hours. Recorded capability coverage: Portal SME, GTM SME. Portal SME (SK-999).');
  assert.equal(source.includes('Portal SME'), false, 'Saved evidence must remain untouched');
  assert.equal(capabilityText('SK-0050 XSK-005 SK-005-extra SK-005_extra', skills), 'SK-0050 XSK-005 SK-005-extra SK-005_extra');
  assert.equal(capabilityText('SK.1 and SKx1', [{ id: 'SK.1', name: 'Literal ID' }]), 'Literal ID and SKx1');
  assert.equal(capabilityText('SK-005', []), 'SK-005');
  assert.equal(capabilityText('', skills), '');
});

test('shared display component renders catalogue names as escaped text', () => {
  const html = renderToStaticMarkup(React.createElement(CapabilityText, null, 'Coverage: SK-005; <b>evidence</b>'));
  assert.equal(html, 'Coverage: Portal SME; &lt;b&gt;evidence&lt;/b&gt;');
});

test('assigned read-only fitment resolves skill names without exposing extra candidate controls', () => {
  const html = renderToStaticMarkup(React.createElement(AssignedFitmentPresentation, {
    snapshot: { requests: [{ request_id: 'REQ-TEST', title: 'Test', status: 'STAFFED' }], assignments: [
      { assignment_id: 'A-1', request_id: 'REQ-TEST', person_id: 'SELF', full_name: 'Member', role_in_pod: 'POD_MEMBER',
        status: 'CONFIRMED', responsibilities: 'Recorded capability coverage: SK-005.', assigned_hours: 4 },
    ] }, error: '', activeRequestId: 'REQ-TEST', personId: 'SELF', details: [], onRefresh() {}, onSelect() {},
  }));
  assert.match(html, /Recorded capability coverage: Portal SME/);
  assert.doesNotMatch(html, /SK-005|Approve pod|Manual override|Alternative Leads|Re-run/);
});

test('selected candidates, alternatives and agent-result descriptions all use catalogue names', () => {
  const person = { person_id: 'P-1', full_name: 'Lead', role_in_pod: 'POD_LEAD', planned_hours: 4,
    score: 50, factors: {}, responsibilities: 'Recorded capability coverage: SK-005.' };
  const proposal = { proposal_id: 'PP-1', request_id: 'REQ-TEST', execution_id: 'EX-1', status: 'READY_FOR_REVIEW', stale: 'N',
    proposal_version: 1, starts_on: '2026-12-14', ends_on: '2026-12-18', total_hours: 4, lead_count: 1,
    member_count: 0, policy_version: 'test', rationale: 'Saved explanation.', members: [person],
    selection_review: { revision: 0, selection_id: null, members: [person], original_members: [person],
      alternatives: [{ replaces: 'P-1', role: 'POD_LEAD', member: { ...person, person_id: 'P-2', full_name: 'Alternative' } }], notes: [] } };
  const saved = JSON.stringify(proposal);
  const props = { request: { request_id: 'REQ-TEST', title: 'Test', status: 'NEEDS_RECOMMENDATION' },
    requests: [], proposal, execution: { execution_id: 'EX-1', request_id: 'REQ-TEST', status: 'READY_FOR_REVIEW',
      events: [], clarification_questions: [] }, loading: false, busy: false, running: false,
    error: '', canRun: false, canDecide: false, decision: null, reason: '', onSelect() {}, onRefresh() {} };
  for (const executionView of [false, true]) {
    const html = renderToStaticMarkup(React.createElement(LiveFitmentPresentation, { ...props, executionView }));
    assert.match(html, /Recorded capability coverage: Portal SME/);
    assert.doesNotMatch(html, /SK-005/);
  }
  assert.equal(JSON.stringify(proposal), saved, 'Rendering must not mutate stored proposals');
});

const response = data => new Response(JSON.stringify({ data }));
function setup() {
  const listeners = new EventTarget();
  global.window = listeners;
  calls = [];
  requestRows = [{ request_id: 'REQ-TEST', title: 'Test request', status: 'STAFFED', request_revision: 1, responsible_captain_id: 'SELF' }];
  savedProposal = { proposal_id: 'PP-TEST', request_id: 'REQ-TEST', proposal_version: 1, status: 'APPROVED', stale: 'N', members: [],
    starts_on: '2026-12-14', ends_on: '2026-12-18', total_hours: 4, lead_count: 1, member_count: 0,
    rationale: 'Historical team.', policy_version: 'staffing-utilization-v1' };
  transport = async (url, options) => {
    calls.push({ url, options });
    if (url === '/api/agentic/requests') return response(structuredClone(requestRows));
    if (url === '/api/agentic/me') return response({ person_id: 'SELF', roles: [], permissions: [] });
    if (url.endsWith('/execution')) return response({ execution_id: 'EX-TEST', request_id: 'REQ-TEST', request_revision: 1,
      status: 'READY_FOR_REVIEW', events: [], clarification_questions: [], proposals: [] });
    if (url.endsWith('/proposal')) return response({ current_proposal: structuredClone(savedProposal), previous_proposal: null });
    throw new Error(`Unexpected test request: ${url}`);
  };
  const h = { index: 0, slots: [], effects: [], tree: null, dirty: true };
  h.render = () => {
    harness = h; h.index = 0; h.effects = []; h.dirty = false;
    h.tree = LiveStaffingReview({});
    for (const effect of h.effects) effect();
  };
  h.settle = async () => {
    for (let i = 0; i < 15; i++) {
      if (h.dirty) h.render();
      await new Promise(resolve => setImmediate(resolve));
    }
    if (h.dirty) h.render();
  };
  h.presentation = () => all(h.tree).find(node => node.type === LiveFitmentPresentation).props;
  h.unmount = () => { for (const slot of h.slots) slot?.cleanup?.(); };
  return h;
}
function all(tree) {
  if (!tree || typeof tree !== 'object') return [];
  if (Array.isArray(tree)) return tree.flatMap(all);
  return [tree, ...all(tree.props?.children)];
}

test('closure event refreshes the mounted Fitment request, selector and history without manual refresh', async () => {
  const h = setup();
  try {
    await h.settle();
    assert.equal(h.presentation().request.status, 'STAFFED');
    requestRows[0] = { ...requestRows[0], status: 'CLOSED', request_revision: 2 };
    const reads = calls.filter(c => c.url === '/api/agentic/requests').length;
    announceStaffingChange();
    await h.settle();
    const p = h.presentation();
    assert.equal(p.request.status, 'CLOSED');
    assert.equal(p.requests[0].status, 'CLOSED');
    assert.equal(p.execution.execution_id, 'EX-TEST', 'Closure retains execution history');
    assert.equal(p.proposal.status, 'APPROVED', 'Closure retains the approved team');
    assert.equal(p.canDecide, false);
    assert.ok(calls.filter(c => c.url === '/api/agentic/requests').length > reads);
    const html = renderToStaticMarkup(React.createElement(LiveFitmentPresentation, p));
    assert.match(html, /Project closed · Staffing history retained|>Closed</);
    assert.doesNotMatch(html, /Awaiting execution|Approve pod|>Staffed</);
    assert.ok(calls.every(c => c.options.method === 'GET'), 'Refresh must not invoke mutations');
  } finally { h.unmount(); }
  const readsAfterUnmount = calls.length;
  window.dispatchEvent(new Event(STAFFING_CHANGED_EVENT));
  assert.equal(calls.length, readsAfterUnmount, 'Unmount removes the listener');
});

test('an older in-flight proposal cannot restore pre-closure review state', async () => {
  const h = setup();
  const normalTransport = transport;
  let resolveOld;
  let deferFirst = true;
  transport = async (url, options) => {
    if (url.endsWith('/proposal') && deferFirst) {
      deferFirst = false;
      return new Promise(resolve => { resolveOld = resolve; });
    }
    return normalTransport(url, options);
  };
  try {
    await h.settle();
    assert.equal(typeof resolveOld, 'function');
    requestRows[0] = { ...requestRows[0], status: 'CLOSED', request_revision: 2 };
    savedProposal = { ...savedProposal, proposal_version: 2 };
    announceStaffingChange();
    await h.settle();
    assert.equal(h.presentation().request.status, 'CLOSED');
    resolveOld(response({ current_proposal: { ...savedProposal, proposal_version: 1, status: 'READY_FOR_REVIEW' }, previous_proposal: null }));
    await h.settle();
    assert.equal(h.presentation().request.status, 'CLOSED');
    assert.equal(h.presentation().proposal.status, 'APPROVED');
    assert.equal(h.presentation().proposal.proposal_version, 2);
    assert.equal(h.presentation().decision, null);
  } finally { h.unmount(); }
});
