/* Offline real-roster role foundation tests. No Oracle/OCI or account writes. */
const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const root = path.resolve(__dirname, '..');
const originalLoad = Module._load;
let appContext;
let liveSnapshot;
Module._load = function (id, parent, main) {
  if (id === 'server-only') return {};
  if (id === '@/context/StaffingAppProvider') return { useStaffingApp: () => appContext };
  if (id === '@/lib/use-live-workspace') return { useLiveWorkspace: () => ({ snapshot: liveSnapshot, error: '', refresh() {} }) };
  if (id === 'next/navigation') return { useRouter: () => ({ refresh() {} }) };
  if (id.startsWith('@/')) id = path.join(root, id.slice(2));
  return originalLoad.call(this, id, parent, main);
};
require.extensions['.tsx'] = require.extensions['.ts'] = (mod, filename) => mod._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true }, fileName: filename,
}).outputText, filename);

const { highestStaffingRole, ROLE_CODES } = require('../types/roles.ts');
const { canPerform, rolePermission, configuredRolePermission } = require('../lib/role-policy.ts');
const { canCaptainAct } = require('../lib/live-permissions.ts');
const { selectIdentityPerson, selectVisiblePeople } = require('../lib/selectors.ts');
const { manualPeopleForSlot, ManualPodEditor } = require('../components/screens/fitment/ManualPodEditor.tsx');
const { FinalPodDetails } = require('../components/screens/requests/FinalPodDetails.tsx');
const { LiveAssignments } = require('../components/screens/requests/LiveAssignments.tsx');
const { AvailabilityScreen } = require('../components/screens/availability/AvailabilityScreen.tsx');
const { RoleSelector } = require('../components/shell/RoleSelector.tsx');
const { OnboardingEntry, deliverableOptionLabel } = require('../components/entry/OnboardingEntry.tsx');
const { AccountAccess } = require('../components/screens/administration/AccountAccess.tsx');

test('first-login entry explains contracted hours without invented skills or a percentage field', () => {
  const html = render(OnboardingEntry, { initial: { status: 'DRAFT', revision: 1, full_name: 'Real Employee', daily_hours: 8, weekly_hours: 40,
    skills: [{ interest_id: 'S1', interest_name: 'Communication' }], deliverables: [
      { deliverable_id: 'D1', deliverable_name: 'Content Communication Review', project_name: 'New Service Launch' },
      { deliverable_id: 'D2', deliverable_name: 'Content Communication Review', project_name: 'Enablement' },
    ] }, sessionKey: 'safe-page-fingerprint' });
  assert.match(html, /FIRST-LOGIN SETUP|FIRST.LOGIN SETUP/);
  assert.match(html, /8 hours\/day/); assert.match(html, /40 hours\/week/);
  assert.match(html, /Search skills by name/); assert.match(html, /Search deliverables by name/);
  assert.match(html, /small preference signal/); assert.match(html, /does not change your proficiency/);
  assert.doesNotMatch(html, /<select[^>]*>.*Content Communication Review/s);
  assert.doesNotMatch(html, /name="allocation|name="activePods|Remove skill/);
  assert.match(html, /staffing-persona-session/); assert.doesNotMatch(html, /aps1\./);
});

test('first-login deliverable labels include project context and never render undefined', () => {
  assert.equal(deliverableOptionLabel({ deliverable_name: 'Content Communication Review', project_name: 'Ignored fallback',
    display_name: 'Content Communication Review — New Service Launch' }), 'Content Communication Review — New Service Launch');
  assert.equal(deliverableOptionLabel({ deliverable_name: 'Content Communication Review', project_name: 'Enablement' }),
    'Content Communication Review — Enablement');
  assert.equal(deliverableOptionLabel({ deliverable_name: 'Content Communication Review' }), 'Content Communication Review');
  assert.doesNotMatch(deliverableOptionLabel({ deliverable_name: 'Content Communication Review' }), /undefined/);
});

test('first-login source contains no Captain review hold', () => {
  const source = fs.readFileSync(path.join(root, 'components/entry/OnboardingEntry.tsx'), 'utf8');
  assert.doesNotMatch(source, /Captain review required|needs review|Check review status|hold your profile for review/);
  assert.match(source, /counts toward your capacity immediately/);
});

test('account management states history retention and exposes no password controls', () => {
  const html = render(AccountAccess);
  assert.match(html, /Existing assignments and history are retained/);
  assert.match(html, /Search accounts/); assert.doesNotMatch(html, /type="password"|password_hash|token_hash/);
});

function permission(resourceCode, accessScope = 'full', actions = []) {
  return { resourceCode, accessScope, canView: true, canCreate: false, canUpdate: false, canApprove: false, canExport: false, canAdminister: false,
    ...Object.fromEntries(actions.map(action => [action, true])) };
}
function definition(name, permissions) { return { code: ROLE_CODES[name], name, active: true, permissions }; }
function fixture(grants = ['SYSTEM_ADMINISTRATOR', 'POD_CAPTAIN', 'POD_LEAD']) {
  const roles = [
    definition('Administrator', [permission('TEAM_SKILLS'), permission('MY_AVAILABILITY'), permission('AI_FITMENT')]),
    definition('POD Captain', [permission('REQUESTS', 'full', ['canCreate']), permission('AI_FITMENT', 'full', ['canApprove'])]),
    definition('POD Lead', [permission('MY_SKILLS', 'own', ['canCreate', 'canUpdate']), permission('MY_AVAILABILITY', 'own', ['canCreate']), permission('REQUESTS', 'scoped', ['canUpdate'])]),
    definition('POD Member', [permission('TEAM_SKILLS', 'own')]),
  ];
  const person = (id, name) => ({ id, name, initials: name[0], jobTitle: '', location: '', allocationPct: 0, activePods: 0, skills: [], availability: [] });
  return { identity: { personId: 'SELF', role: highestStaffingRole(grants), sessionMode: 'password' },
    people: [person('OTHER', 'Other employee'), person('SELF', 'Signed-in employee')], requests: [],
    authorization: { grantedRoleCodes: grants, roles: roles.filter(role => grants.includes(role.code)), roleCatalogue: roles, userRoles: [] },
    demoIdentity: { podLeadPersonId: 'WRONG', podMemberPersonId: 'WRONG' } };
}
function context(data = fixture()) {
  appContext = { data, state: { role: data.identity.role }, dispatch() {}, notify() {}, setRole() {} };
  return data;
}
function render(Component, props = {}) { return renderToStaticMarkup(React.createElement(Component, props)); }

test('highest role is deterministic and does not manufacture lower-role grants', () => {
  for (const grants of [['POD_MEMBER', 'POD_LEAD', 'POD_CAPTAIN', 'SYSTEM_ADMINISTRATOR'], ['SYSTEM_ADMINISTRATOR', 'POD_LEAD']]) {
    assert.equal(highestStaffingRole(grants), 'Administrator');
  }
  assert.equal(highestStaffingRole(['POD_LEAD', 'POD_CAPTAIN']), 'POD Captain');
  assert.equal(highestStaffingRole(['POD_MEMBER', 'POD_LEAD']), 'POD Lead');
  assert.equal(highestStaffingRole(['POD_MEMBER']), 'POD Member');
  assert.equal(highestStaffingRole(['UNKNOWN']), undefined);
});

test('signed capabilities retain Captain and self-service actions under the Administrator interface', () => {
  const { authorization } = fixture();
  assert.equal(canPerform('Administrator', 'AI_FITMENT', 'canApprove', authorization), true);
  assert.equal(canPerform('Administrator', 'REQUESTS', 'canCreate', authorization), true);
  assert.equal(canPerform('Administrator', 'MY_SKILLS', 'canUpdate', authorization), true);
  assert.equal(canPerform('Administrator', 'MY_AVAILABILITY', 'canCreate', authorization), true);
  assert.equal(rolePermission('Administrator', 'MY_AVAILABILITY', authorization).accessScope, 'full');
  assert.equal(configuredRolePermission('Administrator', 'AI_FITMENT', authorization).canApprove, false);
});

test('the Administrator configuration catalogue cannot grant Captain actions to an Administrator-only account', () => {
  const { authorization } = fixture(['SYSTEM_ADMINISTRATOR']);
  assert.equal(configuredRolePermission('POD Captain', 'AI_FITMENT', authorization).canApprove, true);
  assert.equal(canPerform('Administrator', 'AI_FITMENT', 'canApprove', authorization), false);
  assert.equal(canPerform('Administrator', 'MY_SKILLS', 'canUpdate', authorization), false);
  authorization.roles = authorization.roleCatalogue; // Even an accidentally broad catalogue is not the signed grant list.
  assert.equal(canPerform('Administrator', 'REQUESTS', 'canCreate', authorization), false);
  authorization.grantedRoleCodes = [];
  assert.equal(canPerform('Administrator', 'TEAM_SKILLS', 'canView', authorization), false);
});

test('shared Captain approval permits another owner and self-approval but requires a current Captain permission', () => {
  const identity = { person_id: 'SELF', roles: ['SYSTEM_ADMINISTRATOR', 'POD_CAPTAIN'], permissions: [
    { role: 'POD_CAPTAIN', resource: 'AI_FITMENT', scope: 'FULL', actions: ['view', 'approve'] },
  ] };
  assert.equal(canCaptainAct(identity, 'AI_FITMENT', 'approve', 'OTHER'), true);
  assert.equal(canCaptainAct(identity, 'AI_FITMENT', 'approve', 'SELF'), true);
  assert.equal(canCaptainAct({ ...identity, roles: ['SYSTEM_ADMINISTRATOR'] }, 'AI_FITMENT', 'approve', 'SELF'), false);
  assert.equal(canCaptainAct({ ...identity, permissions: [] }, 'AI_FITMENT', 'approve', 'SELF'), false);
  identity.permissions[0].scope = 'LOCKED';
  assert.equal(canCaptainAct(identity, 'AI_FITMENT', 'approve', 'OTHER'), false);
  identity.permissions[0].scope = 'OWN';
  assert.equal(canCaptainAct(identity, 'AI_FITMENT', 'approve', 'OTHER'), false);
  assert.equal(canCaptainAct(identity, 'AI_FITMENT', 'approve', 'SELF'), true);
});

test('manual selection uses explicit role grants, deduplicates people and excludes other selected slots', () => {
  const people = [
    { person_id: 'AMY', full_name: 'Amy', role_codes: ['POD_CAPTAIN', 'POD_LEAD'] },
    { person_id: 'BOTH', full_name: 'Both', role_codes: ['POD_LEAD', 'POD_MEMBER'] },
    { person_id: 'BOTH', full_name: 'Both', role_codes: ['POD_LEAD', 'POD_MEMBER'] },
    { person_id: 'MEMBER', full_name: 'Member', role_codes: ['POD_MEMBER'] },
  ];
  const slots = [{ person_id: 'BOTH', role: 'POD_LEAD', manual: false }, { person_id: '', role: 'POD_MEMBER', manual: true }];
  assert.deepEqual(manualPeopleForSlot(people, slots, 0).map(p => p.person_id), ['AMY', 'BOTH']);
  assert.deepEqual(manualPeopleForSlot(people, slots, 1).map(p => p.person_id), ['MEMBER']);
  slots[1].person_id = 'AMY';
  const html = render(ManualPodEditor, { people, slots, selected: [], leadCount: 1, memberCount: 1, busy: false, onClose() {}, onPreview() {} });
  assert.match(html, /Choose people with an active grant/);
  assert.match(html, /disabled="">Calculate preview/);
});

test('Administrator self availability uses the signed-in person, never the first directory row', () => {
  const data = context();
  assert.equal(selectIdentityPerson(data, 'Administrator').id, 'SELF');
  assert.equal(selectVisiblePeople(data, 'Administrator').length, 2);
  const html = render(AvailabilityScreen);
  assert.match(html, /My availability/);
  assert.match(html, /Signed-in employee/);
  assert.match(html, /Add availability event/);
  assert.doesNotMatch(html, /Other employee — capacity/);
});

test('authenticated roles are a single badge, not a persona selector', () => {
  context();
  const html = render(RoleSelector);
  assert.match(html, /Current profile: Administrator/);
  assert.doesNotMatch(html, /<select|<option/);
});

test('closure controls use server-assigned Lead capability regardless of the highest display role', () => {
  for (const grant of ['POD_LEAD', 'POD_CAPTAIN', 'SYSTEM_ADMINISTRATOR']) {
    context(fixture([grant]));
    liveSnapshot = { requests: [{ request_id: 'REQ', title: 'Request', status: 'STAFFED', can_close: true }], assignments: [], summary: {}, people: [] };
    for (const [Component, props] of [[FinalPodDetails, { requestId: 'REQ' }], [LiveAssignments, {}]]) {
      assert.match(render(Component, props), /Close project/);
      liveSnapshot.requests[0].can_close = false;
      assert.doesNotMatch(render(Component, props), /Close project/);
      delete liveSnapshot.requests[0].can_close;
      assert.doesNotMatch(render(Component, props), /Close project/);
      liveSnapshot.requests[0].can_close = true;
    }
  }
});
