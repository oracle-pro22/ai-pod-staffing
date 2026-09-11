/* Offline regression tests: no wallet, Oracle connection, or database writes.
   Uses the installed TypeScript compiler and Node test runner. */
const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const root = path.resolve(__dirname, '..');
const nativeLoad = Module._load;
let execute = async () => { throw new Error('No mocked query configured'); };
let appContext;

// Stub only external infrastructure; test the actual application modules.
Module._load = function (id, parent, main) {
  if (id === 'server-only') return {};
  if (id === '@/context/StaffingAppProvider' && appContext) return { useStaffingApp: () => appContext };
  if (id === '@/lib/db/oracle') return {
    withOracleConnection: async (fn) => fn({ execute: (...args) => execute(...args) }),
    withOracleTransaction: async (fn) => fn({ execute: (...args) => execute(...args) }),
  };
  if (id.startsWith('@/')) id = path.join(root, id.slice(2));
  return nativeLoad.call(this, id, parent, main);
};
require.extensions['.tsx'] = require.extensions['.ts'] = (mod, filename) => {
  const result = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    fileName: filename,
  });
  mod._compile(result.outputText, filename);
};

const { STAFFING_ROLES, ROLE_CODES, isStaffingRole, migratePreviewRole } = require('../types/roles.ts');
const { canPerform, canAccessScreen, defaultScreen } = require('../lib/role-policy.ts');
const { buildOracleStaffingViewModel } = require('../lib/mappers/oracle-staffing-mapper.ts');
const { selectVisibleRequests, selectVisiblePeople, selectIdentityPerson, selectRoleViewModel } = require('../lib/selectors.ts');
const { staffingRequestContext } = require('../lib/auth/staffing-request-context.ts');
const { createStaffingRequest, createAvailabilityEvent } = require('../lib/repositories/staffing-mutation-repository.ts');
const { requireStaffingPermission } = require('../lib/auth/staffing-authorization.ts');
const { validateCreatePerson } = require('../lib/validation/people.ts');
const { createPerson, listActivePeopleNames } = require('../lib/repositories/people-repository.ts');
const { resolveFitmentRecommendations } = require('../lib/demo-fitment.ts');
const { readOracleStaffingSnapshot } = require('../lib/repositories/staffing-repository.ts');

// Read the exact permission rows from the SQL migration the user executed.
const sql = fs.readFileSync(path.join(root, 'sql/oracle/roles_catalog.sql'), 'utf8');
const permissionRows = [...sql.matchAll(/INSERT INTO ROLE_PERMISSIONS \(([^)]+)\) VALUES \(([^)]+)\)/g)].map((match) => {
  const keys = match[1].split(',').map((key) => key.trim().toUpperCase());
  const values = [...match[2].matchAll(/'([^']*)'/g)].map((item) => item[1]);
  return Object.fromEntries(keys.map((key, index) => [key, values[index]]));
});
function fixture() {
  return buildOracleStaffingViewModel({
    database: { DATABASE_TIME: '2026-09-10T12:00:00Z' },
    projectTypes: [{ PROJECT_TYPE_ID: 'PT-011', PROJECT_NAME: 'Special Projects/ Ad Hoc', PROJECT_DESCRIPTION: 'Current description', SOURCE_VERSION: 'v260810.r2-20260910' }],
    interests: [{ INTEREST_ID: 'SK-014', INTEREST_NAME: 'Comms Team' }],
    deliverables: [
      { DELIVERABLE_ID: 'DEL-005', PROJECT_TYPE_ID: 'PT-011', DELIVERABLE_NAME: 'Retired item', ACTIVE_FLAG: 'N' },
      { DELIVERABLE_ID: 'DEL-072', PROJECT_TYPE_ID: 'PT-011', DELIVERABLE_NAME: 'Executive Communication Support', ACTIVE_FLAG: 'Y' },
      { DELIVERABLE_ID: 'DEL-BLANK', PROJECT_TYPE_ID: 'PT-011', DELIVERABLE_NAME: 'Solution Matrix Updates', ACTIVE_FLAG: 'Y', SKILLS_RAW: null },
    ],
    deliverableSkills: [{ DELIVERABLE_ID: 'DEL-072', SKILL_ID: 'SK-014' }, { DELIVERABLE_ID: 'DEL-005', SKILL_ID: 'SK-014' }],
    people: [['P-001', 'Member One'], ['P-006', 'Lead Six'], ['P-009', 'Indranie Balkaran'], ['P-010', 'Unassigned Person']]
      .map(([PERSON_ID, FULL_NAME]) => ({ PERSON_ID, FULL_NAME, ALLOCATION_PCT: 20 })),
    personInterests: [], availability: [], customerMapping: [],
    requests: ['REQ-1', 'REQ-2', 'REQ-3', 'REQ-4', 'REQ-5'].map((REQUEST_ID) => ({
      REQUEST_ID, TITLE: REQUEST_ID, PROJECT_TYPE_ID: 'PT-011', PROJECT_TYPE: 'Special Projects',
      PROJECT_DESCRIPTION: 'Original description', DELIVERABLE_ID: 'DEL-005',
      MAPPING_VERSION: 'original-version', STATUS: 'NEEDS_RECOMMENDATION', REQUESTED_LEAD_COUNT: 1, REQUESTED_CONTRIBUTOR_COUNT: 2,
    })),
    requirements: [{ REQUEST_ID: 'REQ-1', INTEREST_ID: 'SK-014', SKILL_NAME: 'Historical skill spelling', REQUIREMENT_SOURCE: 'Original source' }],
    recommendations: [
      ['REQ-1', 'P-006', 'POD Lead', 'APPROVED', 'Y'],
      ['REQ-1', 'P-001', 'Contributor', 'APPROVED', 'Y'],
      ['REQ-1', 'P-010', 'Contributor', 'PENDING_REVIEW', 'Y'],
      ['REQ-2', 'P-006', 'Pod lead', 'PENDING_REVIEW', 'Y'],
      ['REQ-3', 'P-006', 'Pod lead', 'DECLINED', 'Y'],
      ['REQ-4', 'P-006', 'Pod lead', 'APPROVED', 'N'],
      ['REQ-5', 'P-006', 'Contributor', 'APPROVED', 'Y'],
    ].map(([REQUEST_ID, PERSON_ID, ROLE_IN_POD, DECISION_STATUS, SELECTED_FLAG]) => ({ REQUEST_ID, PERSON_ID, ROLE_IN_POD, DECISION_STATUS, SELECTED_FLAG })),
    roles: [
      ...STAFFING_ROLES.map((ROLE_NAME) => ({ ROLE_NAME, ROLE_CODE: ROLE_CODES[ROLE_NAME], ACTIVE_FLAG: 'Y' })),
      { ROLE_NAME: 'Executive', ROLE_CODE: 'EXECUTIVE', ACTIVE_FLAG: 'N' },
    ],
    rolePermissions: permissionRows,
    userRoles: [{ IDENTITY_SUBJECT: 'test-subject', ROLE_CODE: 'POD_CAPTAIN', PERSON_ID: 'P-009', ACTIVE_FLAG: 'Y' }],
  });
}
test('all 48 migrated permission rows drive the four official profiles', () => {
  assert.equal(permissionRows.length, 48);
  const data = fixture();
  assert.deepEqual(data.authorization.roles.map((item) => item.name), STAFFING_ROLES);
  for (const row of permissionRows) {
    const role = STAFFING_ROLES.find((item) => ROLE_CODES[item] === row.ROLE_CODE);
    for (const [action, key] of Object.entries({ canView: 'CAN_VIEW', canCreate: 'CAN_CREATE', canUpdate: 'CAN_UPDATE', canApprove: 'CAN_APPROVE', canExport: 'CAN_EXPORT', canAdminister: 'CAN_ADMINISTER' })) {
      assert.equal(canPerform(role, row.RESOURCE_CODE, action, data.authorization),
        row.ACCESS_SCOPE !== 'LOCKED' && row.CAN_VIEW === 'Y' && row[key] === 'Y', role + '/' + row.RESOURCE_CODE + '/' + action);
    }
  }
  assert.equal(defaultScreen('Administrator', data.authorization), 'admin');
  assert.equal(canAccessScreen('Administrator', 'requests', data.authorization), false);
  assert.equal(canAccessScreen('POD Member', 'fitment', data.authorization), false);
});
test('legacy names migrate browser preview only; missing permission is never full access', () => {
  assert.equal(migratePreviewRole('Operations Lead'), 'POD Captain');
  assert.equal(migratePreviewRole('Request Lead'), 'POD Captain');
  assert.equal(migratePreviewRole('Pod Lead'), 'POD Lead');
  assert.equal(migratePreviewRole('System Administrator'), 'Administrator');
  assert.equal(isStaffingRole('Operations Lead'), false);
  assert.equal(canAccessScreen('POD Captain', 'requests'), false);
  const data = fixture();
  data.authorization.roles[0].active = false;
  assert.equal(canAccessScreen('POD Captain', 'requests', data.authorization), false);
});
test('active catalogue, new capability, blank defaults, and historical requests stay distinct', () => {
  const data = fixture();
  assert.equal(data.metrics.deliverables, 2);
  assert.equal(data.integrity.counts.deliverables, 3);
  assert.deepEqual(data.catalog.projects[0].deliverables.map((item) => item.id), ['DEL-072', 'DEL-BLANK']);
  assert.equal(data.catalog.projects[0].deliverables[0].skills[0].name, 'Comms Team');
  assert.deepEqual(data.catalog.projects[0].deliverables[1].skills, []);
  assert.equal(data.catalog.projects[0].name, 'Special Projects/ Ad Hoc');
  assert.equal(data.requests[0].deliverable.name, 'Retired item');
  assert.equal(data.requests[0].projectType.name, 'Special Projects');
  assert.equal(data.requests[0].projectType.description, 'Original description');
  assert.equal(data.requests[0].requiredSkills[0].name, 'Historical skill spelling');
  assert.equal(data.requests[0].mappingVersion, 'original-version');
});
test('assigned scopes exclude pending, declined, unselected and other-person recommendations', () => {
  const data = fixture();
  assert.equal(selectVisibleRequests(data, 'POD Captain').length, 5);
  assert.deepEqual(selectVisibleRequests(data, 'POD Lead').map((item) => item.id), ['REQ-1']);
  assert.deepEqual(selectVisibleRequests(data, 'POD Member').map((item) => item.id), ['REQ-1']);
  assert.deepEqual(selectVisibleRequests(data, 'Administrator'), []);
  for (const role of ['POD Lead', 'POD Member']) {
    assert.deepEqual(selectVisiblePeople(data, role).map((item) => item.id), ['P-001', 'P-006']);
  }
  assert.equal(selectIdentityPerson(data, 'POD Captain').id, 'P-009');
  data.people = data.people.filter((person) => person.id !== 'P-006');
  assert.equal(selectIdentityPerson(data, 'POD Lead'), null);
  assert.deepEqual(selectVisibleRequests(data, 'POD Lead'), []);
});
test('API projection removes unrelated people, recommendation candidates and identity mappings', () => {
  const data = fixture();
  const member = selectRoleViewModel(data, 'POD Member');
  assert.equal(member.requests.length, 1);
  assert.equal(member.requests[0].recommendations.length, 1);
  assert.equal(member.requests[0].recommendations[0].personId, 'P-001');
  assert.deepEqual(member.authorization.userRoles, []);
  assert.equal(member.metrics.people, 2);
  const admin = selectRoleViewModel(data, 'Administrator');
  assert.deepEqual(admin.people, []);
  assert.deepEqual(admin.requests, []);
  assert.equal(admin.metrics.requests, 0);
  assert.equal(admin.catalog.projects.length, 1);
});
test('Captain demo suggestions still work for a new request without stored recommendations', () => {
  const data = fixture();
  const result = resolveFitmentRecommendations(data.requests[0], [], data.people);
  assert.equal(result.isDemo, true);
  assert.ok(result.recommendations.length > 0);
});
test('API preview context accepts only official names and fails closed outside preview mode', () => {
  const previous = process.env.STAFFING_AUTH_MODE;
  try {
    process.env.STAFFING_AUTH_MODE = 'preview';
    for (const role of STAFFING_ROLES) assert.equal(staffingRequestContext({ headers: new Headers({ 'x-staffing-role': role }) }).role, role);
    assert.throws(() => staffingRequestContext({ headers: new Headers() }), { status: 401 });
    assert.throws(() => staffingRequestContext({ headers: new Headers({ 'x-staffing-role': 'Operations Lead' }) }), { status: 401 });
    process.env.STAFFING_AUTH_MODE = 'oci';
    assert.throws(() => staffingRequestContext({ headers: new Headers({ 'x-staffing-role': 'Administrator' }) }), { status: 503 });
  } finally {
    if (previous === undefined) delete process.env.STAFFING_AUTH_MODE; else process.env.STAFFING_AUTH_MODE = previous;
  }
});
test('repository reads current raw source and retains retired deliverables for history', async () => {
  const statements = [];
  execute = async (statement) => { statements.push(statement); return { rows: [] }; };
  await readOracleStaffingSnapshot();
  assert.match(statements.find((item) => /FROM customer_mapping/i.test(item)), /WHERE source_version IN/i);
  const deliverables = statements.find((item) => /FROM deliverables\s/i.test(item));
  assert.match(deliverables, /active_flag/i);
  assert.doesNotMatch(deliverables, /WHERE active_flag/);
});
const input = {
  title: 'New request', projectTypeId: 'PT-011', requestSourcePersonId: 'P-009',
  deliverables: [{ id: 'DEL-072', name: 'Spoofed name', custom: false }],
  requiredCapabilities: [{ id: 'SK-014', name: 'Spoofed capability', custom: false, requiredStrength: 3 }],
  estimatedEffort: { value: 2, unit: 'days' }, requestedPodSize: '1 lead + 2 contributors',
  priority: 'Medium', businessObjectives: 'Objective', neededBy: '2026-12-01',
};
function permissionQuery(binds) {
  return permissionRows.filter((row) => row.ROLE_CODE === binds.roleCode && row.RESOURCE_CODE === binds.resourceCode);
}
test('rephrase authorization uses a non-keyword bind and matching parameter keys', async () => {
  execute = async (statement, binds) => {
    assert.doesNotMatch(statement, /:resource\b/i);
    assert.match(statement, /rp\.resource_code = :resourceCode/);
    const placeholders = [...new Set([...statement.matchAll(/:([A-Za-z]\w*)/g)].map((match) => match[1]))].sort();
    assert.deepEqual(Object.keys(binds).sort(), placeholders);
    assert.equal(binds.resourceCode, 'REQUESTS');
    return { rows: permissionQuery(binds) };
  };
  await requireStaffingPermission({ role: 'POD Captain', actor: 'test' }, 'REQUESTS', 'canCreate');
});
test('request save and rephrase reject the three non-Captain profiles before any write', async () => {
  let writes = 0;
  execute = async (statement, binds) => {
    if (!/SELECT/i.test(statement)) writes += 1;
    return { rows: permissionQuery(binds) };
  };
  for (const role of ['POD Lead', 'POD Member', 'Administrator']) {
    await assert.rejects(createStaffingRequest(input, { role, actor: 'test' }), { status: 403 });
    await assert.rejects(requireStaffingPermission({ role, actor: 'test' }, 'REQUESTS', 'canCreate'), { status: 403 });
  }
  await requireStaffingPermission({ role: 'POD Captain', actor: 'test' }, 'REQUESTS', 'canCreate');
  for (const role of STAFFING_ROLES) await assert.rejects(createAvailabilityEvent({}, { role, actor: 'test' }), { status: 403 });
  assert.equal(writes, 0);
});
function mockSave(retired = false) {
  const writes = [];
  execute = async (statement, binds = {}) => {
    if (/FROM app_roles/i.test(statement)) return { rows: permissionQuery(binds) };
    if (/FROM project_types/i.test(statement)) return { rows: [{ PROJECT_NAME: 'Special Projects/ Ad Hoc', SOURCE_VERSION: 'current-version' }] };
    if (/FROM people/i.test(statement)) return { rows: [{ PERSON_ID: 'P-009', FULL_NAME: 'Indranie Balkaran' }] };
    if (/FROM deliverables\s/i.test(statement)) {
      assert.match(statement, /active_flag = 'Y'/);
      return { rows: retired ? [] : [{ DELIVERABLE_ID: 'DEL-072', DELIVERABLE_NAME: 'Executive Communication Support' }] };
    }
    if (/FROM interests/i.test(statement)) return { rows: [{ INTEREST_ID: 'SK-014', INTEREST_NAME: 'Comms Team' }] };
    if (/FROM deliverable_skills/i.test(statement)) return { rows: [{ DELIVERABLE_ID: 'DEL-072', SKILL_ID: 'SK-014' }] };
    if (/NEXTVAL/i.test(statement)) return { rows: [{ NEXT_VALUE: 2001 }] };
    writes.push({ statement, binds });
    return { rowsAffected: 1 };
  };
  return writes;
}
test('new request uses canonical DB names, current revision and mapped capability links', async () => {
  const writes = mockSave();
  const result = await createStaffingRequest(input, { role: 'POD Captain', actor: 'test' });
  assert.equal(result.requestId, 'REQ-2001');
  assert.equal(writes.length, 2);
  assert.equal(writes[0].binds.skills, 'Comms Team');
  assert.equal(writes[0].binds.deliverable, 'Executive Communication Support');
  assert.equal(writes[0].binds.requestSource, 'Indranie Balkaran');
  assert.equal(writes[0].binds.mappingVersion, 'current-version');
  assert.equal(writes[1].binds.skillName, 'Comms Team');
  assert.equal(writes[1].binds.deliverableId, 'DEL-072');
});
test('retired or wrong-project deliverable submission fails before inserting anything', async () => {
  const writes = mockSave(true);
  await assert.rejects(createStaffingRequest(input, { role: 'POD Captain', actor: 'test' }), { status: 400 });
  assert.equal(writes.length, 0);
});



test('Administrator migration and recovery explicitly avoid parallel DML sibling locks', () => {
  for (const filename of ['admin_people.sql', 'rollback_admin_people.sql']) {
    const script = fs.readFileSync(path.join(root, 'sql/oracle', filename), 'utf8');
    assert.match(script, /ALTER SESSION DISABLE PARALLEL DML/);
    assert.match(script, /ALTER SESSION DISABLE PARALLEL QUERY/);
    assert.match(script, /UPDATE \/\*\+ DISABLE_PARALLEL_DML NO_PARALLEL \*\//);
    assert.doesNotMatch(script, /ALTER SYSTEM|DROP TABLE|DROP SEQUENCE/i);
  }
  const script = fs.readFileSync(path.join(root, 'sql/oracle/admin_people.sql'), 'utf8');
  assert.equal([...script.matchAll(/UPDATE \/\*\+/g)].length, 1);
  assert.match(script, /can_create=CASE WHEN resource_code='TEAM_SKILLS' THEN 'Y' ELSE can_create END/);
  assert.match(script, /IF SQL%ROWCOUNT<>12/);
  assert.match(script, /EXCEPTION WHEN OTHERS THEN ROLLBACK; RAISE/);
});

function adminFixture() {
  const data = fixture();
  const admin = data.authorization.roles.find((role) => role.code === 'SYSTEM_ADMINISTRATOR');
  admin.permissions.forEach((item) => {
    item.canView = true; item.accessScope = 'full';
    if (item.resourceCode === 'TEAM_SKILLS') item.canCreate = true;
  });
  return data;
}
const personInput = { fullName: '  New  Person ', jobTitle: 'Engineer', location: 'Bengaluru', email: 'NEW@example.COM', allocationPct: 0, activePods: 0 };
test('person validation normalizes names/email but rejects invalid and missing required data', () => {
  assert.deepEqual(validateCreatePerson(personInput), { ...personInput, fullName: 'New Person', email: 'new@example.com' });
  for (const input of [null, {}, {...personInput, allocationPct: -1}, {...personInput, allocationPct: 101},
    {...personInput, allocationPct: 1.111}, {...personInput, activePods: 1.5}, {...personInput, jobTitle: ''},
    {...personInput, location: ''}, {...personInput, fullName: 'a'.repeat(251)}, {...personInput, email: 'invalid'}]) {
    assert.throws(() => validateCreatePerson(input), { status: 400 });
  }
  assert.equal(validateCreatePerson({...personInput, email: ''}).email, '');
});
test('expanded Administrator can open every screen without gaining Captain-only writes', () => {
  const data = adminFixture();
  const { NAVIGATION_ITEMS } = require('../lib/role-policy.ts');
  for (const item of NAVIGATION_ITEMS) assert.equal(canAccessScreen('Administrator', item.id, data.authorization), true, item.id);
  assert.equal(selectVisibleRequests(data, 'Administrator').length, data.requests.length);
  assert.equal(selectRoleViewModel(data, 'Administrator').requests[0].recommendations.length, 3);
  assert.equal(canPerform('Administrator', 'REQUESTS', 'canCreate', data.authorization), false);
  assert.equal(canPerform('Administrator', 'AI_FITMENT', 'canApprove', data.authorization), false);
  assert.match(renderProfile('Administrator', 'requests', data), /REQ-1/);
  assert.match(renderProfile('Administrator', 'interests', data), /Add person/);
  assert.match(renderProfile('Administrator', 'availability', data), /People availability/);
});
test('create-person rejects every non-admin and an admin without the DB permission', async () => {
  let queries = 0;
  execute = async () => { queries++; return { rows: [] }; };
  for (const role of ['POD Captain','POD Lead','POD Member']) await assert.rejects(createPerson(validateCreatePerson(personInput), { role }), { status: 403 });
  assert.equal(queries, 0);
  await assert.rejects(createPerson(validateCreatePerson(personInput), { role: 'Administrator' }), { status: 403 });
  assert.equal(queries, 1);
});
function personQueryMock({ emailExists = false, insertError, sequenceError, personNumber = '12' } = {}) {
  const inserts = [];
  execute = async (statement, binds) => {
    if (/FROM app_roles/i.test(statement)) {
      assert.equal(binds.roleCode, 'SYSTEM_ADMINISTRATOR');
      assert.equal(binds.resourceCode, 'TEAM_SKILLS');
      return { rows: [{ CAN_VIEW: 'Y', CAN_CREATE: 'Y', ACCESS_SCOPE: 'FULL' }] };
    }
    if (/LOWER\(TRIM\(email_address\)\)/i.test(statement)) return { rows: emailExists ? [{ PERSON_ID: 'P-009' }] : [] };
    if (/person_id_seq.NEXTVAL/i.test(statement)) {
      if (sequenceError) throw sequenceError;
      return { rows: [{ PERSON_NUMBER: personNumber }] };
    }
    if (/INSERT INTO people/i.test(statement)) {
      if (insertError) throw insertError;
      inserts.push({ statement, binds });
      return { rowsAffected: 1 };
    }
    throw new Error('Unexpected SQL');
  };
  return inserts;
}
test('person save inserts one active real row using numeric ID and no role/skills/assignment writes', async () => {
  const inserts = personQueryMock();
  const result = await createPerson(validateCreatePerson(personInput), { role: 'Administrator' });
  assert.deepEqual(result, { personId: 'P-012', fullName: 'New Person' });
  assert.equal(inserts.length, 1);
  assert.equal(inserts[0].binds.initials, 'NP');
  assert.equal(inserts[0].binds.email, 'new@example.com');
  assert.match(inserts[0].statement, /'Y'/);
  personQueryMock({ personNumber: '1001' });
  assert.equal((await createPerson(validateCreatePerson(personInput), { role: 'Administrator' })).personId, 'P-1001');
});
test('duplicate emails, concurrent unique violations and missing sequence fail with actionable errors', async () => {
  const inserts = personQueryMock({ emailExists: true });
  await assert.rejects(createPerson(validateCreatePerson(personInput), { role: 'Administrator' }), { status: 409 });
  assert.equal(inserts.length, 0);
  personQueryMock({ insertError: { errorNum: 1 } });
  await assert.rejects(createPerson(validateCreatePerson(personInput), { role: 'Administrator' }), { status: 409 });
  personQueryMock({ sequenceError: { errorNum: 2289 } });
  await assert.rejects(createPerson(validateCreatePerson(personInput), { role: 'Administrator' }), { status: 503, code: 'PEOPLE_SETUP_REQUIRED' });
});
test('request-source lookup queries active people and returns ID/name only', async () => {
  execute = async (statement) => {
    assert.match(statement, /active_flag = 'Y'/);
    return { rows: [{ PERSON_ID: 'P-012', FULL_NAME: 'New Person', LOCATION: 'Not exposed' }] };
  };
  assert.deepEqual(await listActivePeopleNames(), [{ id: 'P-012', name: 'New Person' }]);
});

function renderProfile(role, screen, data = fixture()) {
  appContext = {
    data,
    state: { role, activeScreen: screen, adminTab: 'roles', activeRequestId: null,
      requestFilters: { search: '', status: '', priority: '', projectTypeId: '', deliverableId: '' },
      selectedCandidatesByRequest: {}, agentRunning: false, weekOffset: 0 },
    dispatch: () => {}, setRole: () => {}, notify: () => {},
  };
  const React = require('react');
  const { renderToStaticMarkup } = require('react-dom/server');
  const { WorkspaceRouter } = require('../components/screens/WorkspaceRouter.tsx');
  return renderToStaticMarkup(React.createElement(WorkspaceRouter));
}
test('screen rendering offers Captain actions but not Lead or Member mutations', () => {
  assert.match(renderProfile('POD Captain', 'requests'), /New request/);
  assert.match(renderProfile('POD Captain', 'fitment'), /Approve pod/);
  assert.doesNotMatch(renderProfile('POD Lead', 'requests'), /New request|Export Excel/);
  assert.doesNotMatch(renderProfile('POD Lead', 'fitment'), /Approve pod|>Re-run</);
  assert.doesNotMatch(renderProfile('POD Member', 'requests'), /New request|Export Excel/);
  assert.match(renderProfile('POD Member', 'interests'), /Member One/);
  assert.match(renderProfile('POD Member', 'interests'), /Lead Six/);
  assert.doesNotMatch(renderProfile('POD Member', 'interests'), /Unassigned Person/);
});
test('Administrator lands on administration rather than operational data; revoked profile fails closed', () => {
  const html = renderProfile('Administrator', 'requests');
  assert.match(html, /Administration|Roles &amp; access/);
  assert.match(html, /POD Captain/);
  assert.doesNotMatch(html, /REQ-1|Unassigned Person|Operations Lead/);
  const data = fixture();
  data.authorization.roles = [];
  assert.match(renderProfile('POD Captain', 'requests', data), /permission|access/i);
  assert.doesNotMatch(renderProfile('POD Captain', 'requests', data), /REQ-1|New request/);
});
test('empty assignments have a usable Lead view, and new capability appears in taxonomy', () => {
  const data = fixture();
  data.requests = [];
  assert.match(renderProfile('POD Lead', 'dashboard', data), /No active projects are assigned/);
  assert.match(renderProfile('POD Lead', 'fitment', data), /No staffing request/);
  renderProfile('Administrator', 'admin');
  appContext.state.adminTab = 'taxonomy';
  const html = require('react-dom/server').renderToStaticMarkup(
    require('react').createElement(require('../components/screens/administration/AdministrationScreen.tsx').AdministrationScreen));
  assert.match(html, /Comms Team/);
  assert.match(html, /No default capabilities supplied/);
  assert.doesNotMatch(html, /Retired item/);
});

test('restored OWN availability permissions show the Add button only for Lead and Member', () => {
  const data = fixture();
  for (const role of data.authorization.roles) {
    if (['POD_LEAD', 'POD_MEMBER'].includes(role.code)) role.permissions.find((item) => item.resourceCode === 'MY_AVAILABILITY').canCreate = true;
  }
  assert.match(renderProfile('POD Lead', 'availability', data), /Add availability event/);
  assert.match(renderProfile('POD Member', 'availability', data), /Add availability event/);
  assert.doesNotMatch(renderProfile('POD Captain', 'availability', data), /Add availability event/);
  assert.doesNotMatch(renderProfile('Administrator', 'availability', adminFixture()), /Add availability event/);
  const migration = fs.readFileSync(path.join(root, 'sql/oracle/availability_access.sql'), 'utf8');
  assert.match(migration, /SESSION_USER/);
  assert.match(migration, /ALTER SESSION DISABLE PARALLEL DML/);
  assert.match(migration, /SET can_create = 'Y'/);
  assert.match(migration, /resource_code = 'MY_AVAILABILITY' AND role_code IN \('POD_LEAD', 'POD_MEMBER'\)/);
});

test('availability save inserts for the own profile and rejects another person, wrong scope, or revoked access', async () => {
  const insertions = [];
  let scope = 'OWN', allowed = 'Y';
  execute = async (statement, binds = {}) => {
    if (/FROM app_roles/.test(statement)) return { rows: [{ ACCESS_SCOPE: scope, CAN_VIEW: 'Y', CAN_CREATE: allowed }] };
    if (/FROM people/.test(statement)) return { rows: [{ PERSON_ID: binds.personId }] };
    if (/INSERT INTO availability/.test(statement)) { insertions.push({ statement, binds }); return { rowsAffected: 1 }; }
    throw new Error('Unexpected query');
  };
  const event = { personId: 'P-001', eventType: 'Leave', startsOn: '2099-12-01', endsOn: '2099-12-02', title: 'Planned leave', allocatedHours: 16 };
  for (const [role, personId] of [['POD Member', 'P-001'], ['POD Lead', 'P-006']]) {
    const context = { role, actor: `PREVIEW:${role.toUpperCase().replaceAll(' ', '_')}` };
    assert.deepEqual(await createAvailabilityEvent({ ...event, personId }, context), { ...event, personId });
    await assert.rejects(createAvailabilityEvent({ ...event, personId: 'P-010' }, context), { status: 403 });
  }
  scope = 'FULL';
  await assert.rejects(createAvailabilityEvent(event, { role: 'POD Member', actor: 'PREVIEW:POD_MEMBER' }), { status: 403 });
  scope = 'OWN'; allowed = 'N';
  await assert.rejects(createAvailabilityEvent(event, { role: 'POD Member', actor: 'PREVIEW:POD_MEMBER' }), { status: 403 });
  assert.equal(insertions.length, 2);
  assert.deepEqual(insertions.map((item) => item.binds.personId), ['P-001', 'P-006']);
});

test('availability dates reject backdating, reversed intervals, invalid types and excessive hours', () => {
  const { validateCreateAvailabilityPayload } = require('../lib/validation/staffing-mutations.ts');
  const { requestBusinessDate } = require('../lib/request-date-policy.ts');
  const today = requestBusinessDate();
  const event = { personId: 'P-001', eventType: 'OOO', startsOn: today, endsOn: today, title: '', allocatedHours: 8 };
  assert.equal(validateCreateAvailabilityPayload(event).title, 'OOO');
  for (const invalid of [{ startsOn: '2000-01-01' }, { endsOn: '2000-01-01' }, { eventType: 'Invalid' }, { allocatedHours: 25 }]) {
    assert.throws(() => validateCreateAvailabilityPayload({ ...event, ...invalid }), { status: 400 });
  }
});
