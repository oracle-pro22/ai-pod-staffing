/* Offline phase-4 bridge and request-intent tests. No Oracle/OCI/network calls. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const root = path.resolve(__dirname, '..');
const originalLoad = Module._load;
let execute = async () => ({ rows: [] });
let committed = false;
let rawViewModel;
Module._load = function(id, parent, main) {
  if (id === 'server-only') return {};
  if (id === '@/lib/staffing-data-source') return { dataSource: { getViewModel: async () => rawViewModel } };
  if (id === '@/lib/db/oracle') return { withOracleTransaction: async fn => {
    const value = await fn({ execute: (...args) => execute(...args) }); committed = true; return value;
  }, publicOracleError: () => 'Database operation failed.' };
  if (id.startsWith('@/')) id = path.join(root, id.slice(2));
  return originalLoad.call(this, id, parent, main);
};
require.extensions['.ts'] = (mod, filename) => mod._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true }, fileName: filename,
}).outputText, filename);

const { NextRequest } = require('next/server');
const { liveStatusLabel, executionProgress, weekDays, availabilityDayHours, allocationMetric, savedFactorValue } = require('../lib/live-presentation.ts');
test('allocation labels distinguish unknown from zero and never inflate small values', () => {
  assert.equal(allocationMetric('0'), '0%');
  assert.equal(allocationMetric('0.13'), '0.13%');
  assert.equal(allocationMetric('80.00'), '80%');
  for (const value of [null, undefined, '', 'NaN', '-1']) assert.equal(allocationMetric(value), null);
});
test('v2 factor chart reflects actual planned effort while frozen legacy keeps its average', () => {
  const members = [4, 12].map((hours, i) => ({ planned_hours: hours, factors: {
    scheduling_algorithm: 'available-days-v2', factors: { skill: i ? '40' : '20' },
  } }));
  assert.equal(savedFactorValue(members, 'skill'), 35);
  assert.equal(savedFactorValue(members, 'missing'), null);
  assert.equal(savedFactorValue([], 'skill'), null);
  members.forEach(m => delete m.factors.scheduling_algorithm);
  assert.equal(savedFactorValue(members, 'skill'), 30);
});
test('restored UI presents live statuses and never completes a failed execution', () => {
  assert.equal(liveStatusLabel('READY_FOR_REVIEW'), 'Ready for review');
  assert.equal(liveStatusLabel('NEEDS_RECOMMENDATION'), 'Needs recommendation');
  assert.equal(executionProgress('FAILED', [{ stage: 'worker', status: 'RUNNING' }]), 1);
  assert.equal(executionProgress('READY_FOR_REVIEW', []), 6);
});
test('weekly calendar preserves total availability hours across weekdays', () => {
  const dates = weekDays('2026-09-14');
  assert.deepEqual(dates, ['2026-09-14', '2026-09-15', '2026-09-16', '2026-09-17', '2026-09-18']);
  const event = { startsOn: '2026-09-14', endsOn: '2026-09-20', allocatedHours: 8.01 };
  assert.deepEqual(dates.map(day => availabilityDayHours(event, day)), [1.61, 1.6, 1.6, 1.6, 1.6]);
  assert.equal(availabilityDayHours(event, '2026-09-19'), null);
  assert.equal(availabilityDayHours(event, '2026-09-21'), null);
  assert.equal(availabilityDayHours({ ...event, allocatedHours: null }, dates[0]), null);
});
const { workspaceError } = require('../backend/staffing/workspace-error.ts');
const { StaffingApiError } = require('../lib/errors/staffing-api-error.ts');
test('workspace errors offer sign-in only for bearer authentication failures', () => {
  const policy = new StaffingApiError('Stored policy details', 409, 'INVALID_POLICY');
  assert.equal(workspaceError(policy, true).showSignIn, false);
  assert.equal(workspaceError(policy, false).showSignIn, false);
  assert.equal(workspaceError(policy, true).code, 'INVALID_POLICY');
  const auth = new StaffingApiError('Token details', 401, 'SIGN_IN_REQUIRED');
  assert.equal(workspaceError(auth, false).showSignIn, true);
  assert.equal(workspaceError(auth, true).showSignIn, false);
  assert.equal(workspaceError(new Error('private database details'), true).code, 'WORKSPACE_UNAVAILABLE');
  assert.ok(!JSON.stringify(workspaceError(policy, true)).includes('Stored policy details'));
});
const { staffingBackend, verifiedCaptain, agenticEnabled } = require('../backend/staffing/bridge.ts');
const { createStaffingRequest } = require('../lib/repositories/staffing-mutation-repository.ts');
const { GET, POST } = require('../app/api/agentic/[...path]/route.ts');
const originalFetch = global.fetch;
const env = { ...process.env };
test.afterEach(() => { global.fetch = originalFetch; for (const key of Object.keys(process.env)) if (!(key in env)) delete process.env[key]; Object.assign(process.env, env); });
function enabled() {
  process.env.STAFFING_AGENTIC_ENABLED = 'true';
  process.env.NEXT_PUBLIC_STAFFING_AGENTIC_ENABLED = 'true';
  process.env.STAFFING_BACKEND_URL = 'http://127.0.0.1:8015';
  process.env.STAFFING_BACKEND_AUTH_MODE = 'bearer';
}
function request(method='GET', headers={}) {
  return new NextRequest('http://localhost:3001/api/agentic/me', { method, headers });
}

test('reports KPIs weight hours, exclude unknown capacity, and respect the current limit', () => {
  const { reportMetrics, reportExport } = require('../lib/reports-model.ts');
  const snapshot = { week_start:'2026-09-14', week_end:'2026-09-20', timezone:'Asia/Kolkata', as_of:'2026-09-15',
    maximum_allocation_pct:'85', request_scope:'Your requests', summary:{pending_review:1,approved:2,rejected:1},
    requests:[{request_id:'R1',title:'Guide',status:'STAFFED'},{request_id:'R2',title:'Video',status:'CLOSED'}], assignments:[],days:[],
    people:[{person_id:'A',full_name:'Alex',capacity_status:'CURRENT',allocation_pct:50,active_pods:2,weeks:[{available_hours:'40',committed_hours:'20'}]},
      {person_id:'B',full_name:'Brenna',capacity_status:'CURRENT',allocation_pct:100,active_pods:1,weeks:[{available_hours:'20',committed_hours:'20'}]},
      {person_id:'C',full_name:'Unknown',capacity_status:'CAPACITY_STALE',allocation_pct:0,active_pods:0,weeks:[{available_hours:'40',committed_hours:'0'}]}] };
  const m=reportMetrics(snapshot);
  assert.equal(m.available,60);assert.equal(m.committed,40);assert.equal(m.utilization,40/60*100);
  assert.equal(m.headroom,14);assert.equal(m.unknown,1);assert.equal(m.aboveLimit,1);
  assert.equal(m.staffed,1);assert.equal(m.closed,1);
  const capacity=reportExport(snapshot,'capacity');
  assert.equal(capacity.rows.length,3);assert.equal(capacity.rows[0][7],50);
  assert.equal(capacity.rows[2][7],null);assert.match(capacity.fileName,/2026-09-14.xlsx$/);
  snapshot.people=[];
  assert.equal(reportMetrics(snapshot).utilization,null);assert.equal(reportMetrics(snapshot).headroom,null);
});

test('Excel exporter produces numeric cells, frozen headers, filters, and safe literal text', async () => {
  const { buildExcelWorkbook } = require('../lib/export-xlsx.ts');
  const zip = require('jszip');
  const blob=await buildExcelWorkbook({sheetName:'Capacity',headers:['Name','Hours','Allocation (%)'],
    rows:[['=HYPERLINK("bad")',29,72.5],['A&B\u0001',0,null]]});
  const workbook=await zip.loadAsync(await blob.arrayBuffer());
  const sheet=await workbook.file('xl/worksheets/sheet1.xml').async('string');
  assert.match(sheet,/<c r="B2"><v>29<\/v><\/c>/);
  assert.match(sheet,/<c r="C2"><v>72.5<\/v><\/c>/);
  assert.match(sheet,/<c r="B3"><v>0<\/v><\/c>/);
  assert.match(sheet,/t="inlineStr"/);assert.ok(!sheet.includes('<f>'));assert.ok(!sheet.includes('\u0001'));
  assert.match(sheet,/A&amp;B/);assert.match(sheet,/state="frozen"/);assert.match(sheet,/<autoFilter ref="A1:C3"/);
});

test('report export proxy validates week and retains backend permission denial', async () => {
  enabled();
  const context={params:Promise.resolve({path:['reports','export']})};
  const req=week => new NextRequest(`http://localhost:3001/api/agentic/reports/export?week=${week}`,{headers:{Authorization:'Bearer trusted'}});
  global.fetch=async url => {
    assert.equal(String(url),'http://127.0.0.1:8015/v1/reports/export?week=2026-09-14');
    return Response.json({error:{code:'FORBIDDEN',message:'No export permission'}},{status:403});
  };
  assert.equal((await GET(req('2026-09-14'),context)).status,403);
  global.fetch=()=>assert.fail('Invalid dates must not reach Python');
  assert.equal((await GET(req('invalid'),context)).status,400);
});

test('Administrator utilization endpoint forwards authenticated GET and POST with origin protection', async () => {
  enabled();
  const context = { params: Promise.resolve({ path: ['admin', 'utilization'] }) };
  const policy = { version: 'util-current', maximum_allocation_pct: '85' };
  global.fetch = async (url, options) => {
    assert.equal(String(url), 'http://127.0.0.1:8015/v1/admin/utilization');
    assert.equal(options.headers.Authorization, 'Bearer trusted');
    if (options.method === 'POST') assert.equal(JSON.parse(options.body).expected_policy_version, 'util-current');
    return Response.json(policy);
  };
  const get = await GET(request('GET', { Authorization: 'Bearer trusted' }), context);
  assert.equal(get.status, 200);
  assert.deepEqual((await get.json()).data, policy);
  const post = origin => new NextRequest('http://localhost:3001/api/agentic/admin/utilization', {
    method: 'POST', headers: { Authorization: 'Bearer trusted', Origin: origin, 'Content-Type': 'application/json' },
    body: JSON.stringify({ maximum_allocation_pct: 85, expected_policy_version: 'util-current', reason: 'Agreed limit' }),
  });
  assert.equal((await POST(post('http://localhost:3001'), context)).status, 200);
  global.fetch = () => assert.fail('Cross-origin policy writes must not reach Python');
  assert.equal((await POST(post('https://untrusted.example'), context)).status, 403);
});

test('agentic flags must agree and default disabled', () => {
  delete process.env.STAFFING_AGENTIC_ENABLED; delete process.env.NEXT_PUBLIC_STAFFING_AGENTIC_ENABLED;
  assert.equal(agenticEnabled(), false);
  process.env.NEXT_PUBLIC_STAFFING_AGENTIC_ENABLED = 'true';
  assert.throws(agenticEnabled, { code: 'AGENTIC_CONFIGURATION' });
});
test('preview role header cannot authenticate the bridge', async () => {
  enabled(); global.fetch = () => assert.fail('Unauthenticated request must not reach backend');
  await assert.rejects(staffingBackend(request('GET', { 'x-staffing-role': 'POD Captain' }), '/v1/me'), { status: 401 });
});
test('bearer is forwarded but preview role is not', async () => {
  enabled();
  global.fetch = async (url, options) => {
    assert.equal(String(url), 'http://127.0.0.1:8015/v1/me');
    assert.equal(options.headers.Authorization, 'Bearer signed-test-token');
    assert.equal(options.headers['x-staffing-role'], undefined);
    assert.equal(options.redirect, 'error');
    return Response.json({ person_id: 'P-010' });
  };
  assert.deepEqual(await staffingBackend(request('GET', { Authorization: 'Bearer signed-test-token', 'x-staffing-role': 'Administrator' }), '/v1/me'), { person_id: 'P-010' });
});
test('development fixed identity is prohibited in production and on remote backend', async () => {
  enabled(); process.env.STAFFING_BACKEND_AUTH_MODE = 'local'; process.env.STAFFING_BACKEND_LOCAL_TOKEN = 'x'.repeat(32);
  process.env.NODE_ENV = 'production';
  await assert.rejects(staffingBackend(request(), '/v1/me'), { code: 'LOCAL_AUTH_RESTRICTED' });
  process.env.NODE_ENV = 'development'; process.env.STAFFING_BACKEND_URL = 'https://backend.example';
  await assert.rejects(staffingBackend(request(), '/v1/me'), { code: 'LOCAL_AUTH_RESTRICTED' });
  process.env.STAFFING_BACKEND_URL = 'http://127.0.0.1:8015';
  await assert.rejects(staffingBackend(new NextRequest('http://untrusted.example/api/agentic/me'), '/v1/me'), { code: 'LOCAL_AUTH_RESTRICTED' });
});
test('cross-origin create is blocked even when identity verification uses a GET', async () => {
  enabled(); global.fetch = () => assert.fail('Cross-origin write must not reach identity lookup');
  await assert.rejects(verifiedCaptain(request('POST', { Authorization: 'Bearer token', Origin: 'https://untrusted.example' })), { code: 'ORIGIN_REJECTED' });
});
test('local POST preserves exact browser Host despite NextURL loopback normalization', async () => {
  enabled(); process.env.NODE_ENV = 'development';
  process.env.STAFFING_BACKEND_AUTH_MODE = 'local';
  process.env.STAFFING_BACKEND_LOCAL_TOKEN = 'x'.repeat(32);
  for (const host of ['127.0.0.1:3001', 'localhost:3001', '[::1]:3001']) {
    let calls = 0;
    global.fetch = async () => { calls++; return Response.json({ ok: true }); };
    const req = new NextRequest(`http://${host}/api/requests`, { method: 'POST', headers: {
      Host: host, Origin: `http://${host}`, 'sec-fetch-site': 'same-origin',
    } });
    assert.deepEqual(await staffingBackend(req, '/v1/me'), { ok: true });
    assert.equal(calls, 1);
  }
});
test('real Host does not allow other origins, ports, forwarded hosts or cross-site writes', async () => {
  enabled(); global.fetch = () => assert.fail('Rejected requests must not reach backend');
  for (const headers of [
    { Origin: 'http://localhost:3001' },
    { Origin: 'http://127.0.0.1:3002' },
    { Origin: 'https://evil.example', 'x-forwarded-host': 'evil.example' },
    { Origin: 'http://127.0.0.1:3001', 'sec-fetch-site': 'cross-site' },
    { Host: '127.0.0.1:3001@evil.example', Origin: 'http://evil.example' },
  ]) {
    const req = new NextRequest('http://127.0.0.1:3001/api/requests', { method: 'POST', headers: {
      Authorization: 'Bearer token', Host: '127.0.0.1:3001', ...headers,
    } });
    await assert.rejects(staffingBackend(req, '/v1/me'), { code: 'ORIGIN_REJECTED' });
  }
});
test('normalized URL cannot enable local credentials for a remote actual Host', async () => {
  enabled(); process.env.NODE_ENV = 'development'; process.env.STAFFING_BACKEND_AUTH_MODE = 'local';
  process.env.STAFFING_BACKEND_LOCAL_TOKEN = 'x'.repeat(32);
  global.fetch = () => assert.fail('Remote Host must not receive local authentication');
  await assert.rejects(staffingBackend(new NextRequest('http://localhost:3001/api/agentic/me', {
    headers: { Host: 'untrusted.example:3001', 'x-forwarded-host': 'localhost:3001' },
  }), '/v1/me'), { code: 'LOCAL_AUTH_RESTRICTED' });
});
test('verified Captain comes from Python identity and current request permission', async () => {
  enabled(); const req = request('POST', { Authorization: 'Bearer signed-test-token', Origin: 'http://localhost:3001' });
  global.fetch = async () => Response.json({ person_id: 'P-010', identity_subject: 'actual-subject', roles: ['POD_CAPTAIN'],
    permissions: [{ role: 'POD_CAPTAIN', resource: 'REQUESTS', scope: 'OWN', actions: ['view', 'create'] }] });
  assert.equal((await verifiedCaptain(req)).identity_subject, 'actual-subject');
  global.fetch = async () => Response.json({ person_id: 'P-010', roles: ['SYSTEM_ADMINISTRATOR'], permissions: [] });
  await assert.rejects(verifiedCaptain(req), { status: 403 });
});
test('bridge cannot proxy arbitrary URLs or unsupported endpoints', async () => {
  enabled(); global.fetch = () => assert.fail('Path must fail allowlist');
  assert.equal((await GET(request(), { params: Promise.resolve({ path: ['http:', 'evil.example'] }) })).status, 404);
  assert.equal((await POST(request('POST'), { params: Promise.resolve({ path: ['assignments'] }) })).status, 404);
});
test('backend conflict is retained without replacing it with success', async () => {
  enabled(); global.fetch = async () => Response.json({ error: { code: 'STALE_PROPOSAL', message: 'Rerun fitment.' } }, { status: 409 });
  await assert.rejects(staffingBackend(request('POST', { Authorization: 'Bearer token' }), '/v1/decisions', 'POST', {}), { status: 409, code: 'STALE_PROPOSAL' });
});

const input = { projectTypeId: 'PT-001', requestSourcePersonId: 'P-OTHER', title: 'Launch', projectDescription: '',
  deliverables: [{ id: 'DEL-1', name: 'Provided name', custom: false }], requiredCapabilities: [{ id: 'SK-1', name: 'Provided skill', requiredStrength: 3, custom: false }],
  requestedPodSize: '1 lead + 2 contributors', estimatedEffort: { value: 24, unit: 'Hours' }, neededBy: '2026-09-18',
  estimatedStartDate: '2026-09-14', estimatedCompletionDate: '2026-09-18', priority: 'Medium', businessObjectives: 'Launch materials', expectedOutcomes: '' };
function mockSave({ linked = true, failIntent = false } = {}) {
  committed = false;
  const writes = [];
  execute = async (sql, binds) => {
    if (sql.includes('FROM app_roles ar')) return { rows: [{ ACCESS_SCOPE: 'FULL', CAN_VIEW: 'Y', CAN_CREATE: 'Y' }] };
    if (sql.includes('AS schema_user')) return { rows: [{ SCHEMA_USER: 'AI_POD_STAFFING', CURRENT_SCHEMA: 'AI_POD_STAFFING' }] };
    if (sql.includes('FROM app_user_roles ur')) return { rows: linked ? [{ PERSON_ID: 'P-CAPTAIN' }] : [] };
    if (sql.includes('FROM project_types')) return { rows: [{ PROJECT_TYPE_ID: 'PT-001', PROJECT_NAME: 'Launch', PROJECT_DESCRIPTION: 'Launch', SOURCE_VERSION: 'v1' }] };
    if (sql.includes('FROM people')) return { rows: [{ PERSON_ID: 'P-OTHER', FULL_NAME: 'Request source person' }] };
    if (sql.includes('FROM deliverables')) return { rows: [{ DELIVERABLE_ID: 'DEL-1', DELIVERABLE_NAME: 'Launch material', CUSTOMER_NOTE: '' }] };
    if (sql.includes('FROM interests')) return { rows: [{ INTEREST_ID: 'SK-1', INTEREST_NAME: 'GTM SME' }] };
    if (sql.includes('FROM deliverable_skills')) return { rows: [{ DELIVERABLE_ID: 'DEL-1', SKILL_ID: 'SK-1' }] };
    if (sql.includes('request_id_seq.NEXTVAL')) return { rows: [{ NEXT_VALUE: 900201 }] };
    if (/INSERT INTO|UPDATE requests/.test(sql)) writes.push({ sql, binds });
    if (failIntent && sql.includes("agent_enabled='Y'")) throw new Error('simulated intent failure');
    return { rows: [] };
  };
  return writes;
}
test('request and automatic-staffing intent commit together with verified Captain, not request source', async () => {
  const writes = mockSave();
  const result = await createStaffingRequest(input, { role: 'POD Captain', actor: 'signed-subject', responsibleCaptainId: 'P-CAPTAIN' });
  assert.equal(result.agentPending, true); assert.equal(committed, true);
  assert.equal(writes[0].binds.requestSourcePersonId, 'P-OTHER');
  assert.equal(writes.at(-1).binds.captainId, 'P-CAPTAIN');
  assert.equal(writes[0].binds.createdBy, 'signed-subject');
  assert.match(writes.at(-1).sql, /agent_enabled='Y'/);
});
test('missing identity mapping cannot save request or staffing intent', async () => {
  const writes = mockSave({ linked: false });
  await assert.rejects(createStaffingRequest(input, { role: 'POD Captain', actor: 'signed-subject', responsibleCaptainId: 'P-CAPTAIN' }), { status: 403 });
  assert.equal(committed, false); assert.equal(writes.length, 0);
});
test('failed intent update prevents the transaction commit', async () => {
  mockSave({ failIntent: true });
  await assert.rejects(createStaffingRequest(input, { role: 'POD Captain', actor: 'signed-subject', responsibleCaptainId: 'P-CAPTAIN' }));
  assert.equal(committed, false);
});
test('live request requires a complete staffing schedule', async () => {
  const writes = mockSave();
  await assert.rejects(createStaffingRequest({ ...input, estimatedStartDate: '' }, { role: 'POD Captain', actor: 'signed-subject', responsibleCaptainId: 'P-CAPTAIN' }), { status: 400 });
  assert.equal(writes.length, 0);
});

test('live request context rejects a spoofed profile and uses verified person/subject', async () => {
  enabled();
  const { staffingRequestContext } = require('../lib/auth/staffing-request-context.ts');
  global.fetch = async () => Response.json({ person_id: 'P-REAL', identity_subject: 'verified-subject', roles: ['POD_MEMBER'], permissions: [] });
  await assert.rejects(staffingRequestContext(request('GET', { Authorization: 'Bearer token', 'x-staffing-role': 'Administrator' })), { status: 403 });
  assert.deepEqual(await staffingRequestContext(request('GET', { Authorization: 'Bearer token', 'x-staffing-role': 'POD Member' })),
    { role: 'POD Member', actor: 'verified-subject', personId: 'P-REAL', authenticated: true });
});

test('server view model removes unrelated records, preview recommendations and subject mappings', async () => {
  enabled();
  const { authenticatedViewModel } = require('../backend/staffing/view-model.ts');
  const identity = { person_id: 'P-REAL', identity_subject: 'verified-subject', roles: ['POD_MEMBER'], permissions: [
    { role: 'POD_MEMBER', resource: 'REQUESTS', scope: 'SCOPED', actions: ['view'] },
    { role: 'POD_MEMBER', resource: 'TEAM_SKILLS', scope: 'SCOPED', actions: ['view'] }] };
  const snapshot = { week_start:'2026-09-14',week_end:'2026-09-20',timezone:'Asia/Kolkata', requests: [{request_id:'REQ-1',status:'CLOSED',past_planned_end:false}], assignments: [], people: [{person_id:'P-REAL',capacity_status:'CAPACITY_STALE',allocation_pct:null,active_pods:0}], summary:{pending_review:0} };
  rawViewModel = { people:[{id:'P-REAL',allocationPct:99},{id:'PRIVATE-PERSON'}], requests:[{id:'REQ-1',status:'Staffed',recommendations:[{personId:'FAKE'}]},{id:'PRIVATE-REQUEST'}],
    authorization:{roles:[{code:'POD_MEMBER',name:'POD Member',permissions:[]}],userRoles:[{identitySubject:'PRIVATE-SUBJECT'}]}, metrics:{}, catalog:{projects:[],skills:[]} };
  global.fetch = async url => Response.json(String(url).endsWith('/v1/me') ? identity : snapshot);
  const model = await authenticatedViewModel(request('GET', {Authorization:'Bearer token'}));
  assert.equal(model.people.length, 1); assert.equal(model.requests.length, 1);
  assert.deepEqual(model.requests[0].recommendations, []);
  assert.equal(model.people[0].capacityStatus, 'CAPACITY_STALE');
  assert.equal(model.requests[0].status,'Closed');
  assert.equal(model.requests[0].pastPlannedEnd,false);
  assert.deepEqual(model.allocationPeriod,{start:'2026-09-14',end:'2026-09-20',timezone:'Asia/Kolkata'});
  assert.ok(!JSON.stringify(model).includes('PRIVATE-'));
});

test('profile projection uses the independent TEAM_SKILLS allowlist, never the request roster', async () => {
  const { authenticatedViewModel } = require('../backend/staffing/view-model.ts');
  for (const [role, teamIds, expected] of [
    ['POD_MEMBER', ['SELF', 'TEAMMATE', 'HISTORICAL'], ['SELF']], // hard cap despite legacy/broad response
    ['POD_LEAD', ['SELF', 'TEAMMATE'], ['SELF', 'TEAMMATE']],
    ['POD_CAPTAIN', ['SELF', 'TEAMMATE', 'HISTORICAL'], ['SELF', 'TEAMMATE', 'HISTORICAL']],
    ['SYSTEM_ADMINISTRATOR', ['SELF', 'TEAMMATE', 'HISTORICAL'], ['SELF', 'TEAMMATE', 'HISTORICAL']],
  ]) {
    enabled();
    const identity = { person_id: 'SELF', roles: [role], permissions: [
      {role, resource:'REQUESTS', scope:'SCOPED', actions:['view']},
      {role, resource:'TEAM_SKILLS', scope:'FULL', actions:['view']},
    ] };
    const metrics = id => ({person_id:id,allocation_pct:60,capacity_status:'CURRENT',active_pods:2});
    const snapshot = {requests:[{request_id:'REQ-1'}], people:['SELF','TEAMMATE','HISTORICAL'].map(metrics),
      assignments:[{request_id:'REQ-1', person_id:'HISTORICAL', full_name:'Past teammate', role_in_pod:'POD_MEMBER', responsibilities:'Write content. Deliverable experience: mentor.'}], summary:{pending_review:0}};
    rawViewModel = {people:['SELF','TEAMMATE','HISTORICAL'].map(id => ({id, skills:[{evidence:`SECRET-${id}`}], availability:[{title:`LEAVE-${id}`}]})),
      requests:[{id:'REQ-1',status:'Staffed',recommendations:[{rationale:'PRIVATE-OLD-SCORE'}]}],
      authorization:{roles:[{code:role,permissions:[]}],userRoles:[{identitySubject:'PRIVATE-SUBJECT'}]},metrics:{},catalog:{projects:[],skills:[]}};
    const calls=[];
    global.fetch = async url => {
      const path=String(url); calls.push(path);
      if(path.endsWith('/v1/me')) return Response.json(identity);
      if(path.endsWith('resource=TEAM_SKILLS')) return Response.json({...snapshot,requests:[],assignments:[],people:teamIds.map(metrics)});
      return Response.json(snapshot);
    };
    const model=await authenticatedViewModel(request('GET',{Authorization:'Bearer token'}));
    assert.deepEqual(model.people.map(p=>p.id),expected,role);
    assert.ok(calls.some(url=>url.endsWith('resource=TEAM_SKILLS')));
    const payload=JSON.stringify(model);
    for(const id of ['SELF','TEAMMATE','HISTORICAL'].filter(id=>!expected.includes(id))) {
      assert.ok(!payload.includes(`SECRET-${id}`)); assert.ok(!payload.includes(`LEAVE-${id}`));
    }
    assert.ok(!payload.includes('PRIVATE-'));
    assert.equal(model.requests[0].recommendations[0].personName,'Past teammate');
    assert.equal(model.requests[0].recommendations[0].rationale, expected.includes('HISTORICAL')
      ? 'Write content. Deliverable experience: mentor.' : "Contribute to the request's deliverables with the POD lead.");
    if (!expected.includes('HISTORICAL')) assert.ok(!payload.includes('Deliverable experience: mentor.'));
    assert.deepEqual(model.requests[0].recommendations[0].factors,[]);
  }
});

test('closure notifies all mounted workspaces and copy distinguishes history from future release', () => {
  const {announceStaffingChange,STAFFING_CHANGED_EVENT,CLOSURE_EXPLANATION,CLOSED_EXPLANATION,OVERDUE_EXPLANATION}=require('../lib/project-closure.ts');
  const previous=global.window;
  try {
    global.window=new EventTarget(); let received=0;
    const receive=()=>received++;
    global.window.addEventListener(STAFFING_CHANGED_EVENT,receive);
    announceStaffingChange(); assert.equal(received,1);
    global.window.removeEventListener(STAFFING_CHANGED_EVENT,receive);
    announceStaffingChange(); assert.equal(received,1);
    assert.match(CLOSURE_EXPLANATION,/tomorrow/);
    assert.match(CLOSED_EXPLANATION,/through the closure day/);
    assert.match(OVERDUE_EXPLANATION,/remains open/);
    for(const file of ['FinalPodDetails.tsx','LiveAssignments.tsx']) {
      const source=fs.readFileSync(path.join(root,'components/screens/requests',file),'utf8');
      assert.match(source,/announceStaffingChange\(\); router.refresh\(\)/);
      assert.match(source,/CLOSURE_EXPLANATION/);
      assert.match(source,/reason.trim\(\)/);
    }
  } finally { if(previous===undefined) delete global.window;else global.window=previous; }
});

test('profile allowlist failure stops server projection without falling back to request people', async () => {
  enabled();
  const { authenticatedViewModel } = require('../backend/staffing/view-model.ts');
  global.fetch=async url=>{
    if(String(url).endsWith('/v1/me')) return Response.json({person_id:'SELF',roles:['POD_LEAD'],permissions:[
      {role:'POD_LEAD',resource:'REQUESTS',scope:'SCOPED',actions:['view']},
      {role:'POD_LEAD',resource:'TEAM_SKILLS',scope:'SCOPED',actions:['view']},
    ]});
    if(String(url).endsWith('resource=TEAM_SKILLS')) return Response.json({error:{code:'DATABASE_UNAVAILABLE',message:'Unavailable'}},{status:503});
    return Response.json({people:[{person_id:'PRIVATE'}],requests:[],assignments:[],summary:{pending_review:0}});
  };
  await assert.rejects(authenticatedViewModel(request('GET',{Authorization:'Bearer token'})), {status:503});
});

test('locked or other-role profile permission cannot serialize profiles from another workspace', async () => {
  const { authenticatedViewModel } = require('../backend/staffing/view-model.ts');
  for(const teamRole of ['POD_MEMBER','SYSTEM_ADMINISTRATOR']) {
    enabled();
    global.fetch=async url=>Response.json(String(url).endsWith('/v1/me') ? {
      person_id:'SELF',roles:['POD_MEMBER'],permissions:[
        {role:'POD_MEMBER',resource:'REQUESTS',scope:'SCOPED',actions:['view']},
        {role:teamRole,resource:'TEAM_SKILLS',scope:teamRole==='POD_MEMBER'?'LOCKED':'FULL',actions:['view']},
      ]
    } : {requests:[],assignments:[],people:[{person_id:'SELF'}],summary:{pending_review:0}});
    rawViewModel={people:[{id:'SELF',skills:[{evidence:'PRIVATE'}]}],requests:[],authorization:{roles:[],userRoles:[]},catalog:{projects:[],skills:[]},metrics:{}};
    const model=await authenticatedViewModel(request('GET',{Authorization:'Bearer token'}));
    assert.deepEqual(model.people,[]);
  }
});

function loginConfig() {
  enabled(); process.env.STAFFING_APP_ORIGIN='https://staffing.example.test';
  process.env.STAFFING_OIDC_CLIENT_ID='client-id'; process.env.STAFFING_LOGIN_STATE_SECRET='s'.repeat(48);
  process.env.STAFFING_OIDC_AUTHORIZATION_URL='https://identity.example.test/authorize';
  process.env.STAFFING_OIDC_TOKEN_URL='https://identity.example.test/token';
  process.env.STAFFING_BACKEND_URL='http://127.0.0.1:8015';
}

test('organization sign-in uses PKCE, fixed callback and protected state cookie', () => {
  loginConfig(); const { beginLogin } = require('../backend/staffing/login.ts');
  const response=beginLogin(), url=new URL(response.headers.get('location'));
  assert.equal(url.searchParams.get('code_challenge_method'),'S256');
  assert.equal(url.searchParams.get('redirect_uri'),'https://staffing.example.test/api/auth/callback');
  assert.equal(url.searchParams.get('code_challenge').length,43);
  assert.ok(response.headers.get('set-cookie').includes('HttpOnly'));
  assert.ok(response.headers.get('set-cookie').includes('Secure'));
});

test('tampered sign-in state cannot exchange code or issue session', async () => {
  loginConfig(); const { completeLogin } = require('../backend/staffing/login.ts');
  global.fetch=()=>assert.fail('No exchange for invalid state');
  await assert.rejects(completeLogin(new NextRequest('https://staffing.example.test/api/auth/callback?code=abc&state=x', {headers:{Cookie:'staffing_login_state=bad.bad'}})),{code:'LOGIN_STATE'});
});

test('session cookie is issued only after backend validates access token and mapping', async () => {
  loginConfig(); const { beginLogin, completeLogin } = require('../backend/staffing/login.ts');
  const start=beginLogin(), state=new URL(start.headers.get('location')).searchParams.get('state');
  let calls=0;
  global.fetch=async (url, options)=>{
    calls++;
    if(String(url).includes('/token')) { assert.ok(options.body.get('code_verifier')); return Response.json({access_token:'signed-access-token',token_type:'Bearer',expires_in:7200}); }
    assert.equal(options.headers.Authorization,'Bearer signed-access-token'); return Response.json({person_id:'P-REAL'});
  };
  const response=await completeLogin(new NextRequest(`https://staffing.example.test/api/auth/callback?code=abc&state=${state}`,{headers:{Cookie:`staffing_login_state=${start.cookies.get('staffing_login_state').value}`}}));
  assert.equal(calls,2); assert.equal(response.cookies.get('staffing_access_token').value,'signed-access-token');
  assert.ok(response.headers.get('set-cookie').includes('Max-Age=3600'));
});

test('invalid backend identity cannot receive browser session', async () => {
  loginConfig(); const { beginLogin, completeLogin } = require('../backend/staffing/login.ts');
  const start=beginLogin(), state=new URL(start.headers.get('location')).searchParams.get('state');
  global.fetch=async url=>String(url).includes('/token') ? Response.json({access_token:'token',token_type:'Bearer'}) : Response.json({error:{code:'FORBIDDEN',message:'Not linked'}},{status:403});
  await assert.rejects(completeLogin(new NextRequest(`https://staffing.example.test/api/auth/callback?code=abc&state=${state}`,{headers:{Cookie:`staffing_login_state=${start.cookies.get('staffing_login_state').value}`}})),{status:403});
});

test('sign-out requires the configured same origin', () => {
  loginConfig(); const { logout }=require('../backend/staffing/login.ts');
  assert.throws(()=>logout(new NextRequest('https://staffing.example.test/api/auth/logout',{method:'POST',headers:{Origin:'https://evil.example'}})),{status:403});
});
