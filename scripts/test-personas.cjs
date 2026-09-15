/* Offline persona boundary and browser-helper tests. No Oracle/OCI/network calls. */
const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const root = path.resolve(__dirname, '..');
const nativeLoad = Module._load;

Module._load = function(id, parent, main) {
  if (id === 'server-only') return {};
  if (id === '@/lib/db/oracle') return { publicOracleError: () => 'Database operation failed.' };
  if (id.startsWith('@/')) id = path.join(root, id.slice(2));
  return nativeLoad.call(this, id, parent, main);
};
require.extensions['.ts'] = (mod, filename) => mod._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true }, fileName: filename,
}).outputText, filename);

const { NextRequest } = require('next/server');
const { personaModeEnabled, requirePersonaMode, personaSessionKey, PERSONA_COOKIE, PERSONA_PAGE_HEADER } = require('../backend/staffing/persona-mode.ts');
const { staffingBackend } = require('../backend/staffing/bridge.ts');
const { GET } = require('../app/api/personas/route.ts');
const { POST, DELETE } = require('../app/api/personas/session/route.ts');
const { staffingFetch, announcePersonaChange } = require('../lib/staffing-fetch.ts');
const { personaLandingScreen, canAccessScreen } = require('../lib/role-policy.ts');
const { STAFFING_ROLES, ROLE_CODES } = require('../types/roles.ts');

const savedEnv = { ...process.env };
const savedGlobals = Object.fromEntries(['fetch', 'window', 'document', 'BroadcastChannel'].map(key => [key,
  Object.getOwnPropertyDescriptor(global, key)]));
const TOKEN = 'dps1.selected-person.signed-payload.signature';
const CONTROL = 'local-backend-control-credential-for-offline-tests';
const PERSON = { person_id: 'P-009', full_name: 'Indranie Balkaran', role_code: 'POD_CAPTAIN', role_name: 'POD Captain' };
const PERSON_BODY = { person_id: PERSON.person_id, role_code: PERSON.role_code };

function enabled() {
  Object.assign(process.env, {
    NODE_ENV: 'development', STAFFING_DEMO_PERSONAS_ENABLED: 'true', STAFFING_BACKEND_AUTH_MODE: 'local',
    STAFFING_AGENTIC_ENABLED: 'true', NEXT_PUBLIC_STAFFING_AGENTIC_ENABLED: 'true',
    STAFFING_BACKEND_URL: 'http://127.0.0.1:8015', STAFFING_BACKEND_LOCAL_TOKEN: CONTROL,
  });
}
function request(method = 'GET', options = {}) {
  const origin = options.base || 'http://127.0.0.1:3001';
  const url = new URL(options.path || '/api/personas', origin);
  const headers = new Headers({ host: url.host, ...options.headers });
  if (!['GET', 'HEAD'].includes(method) && options.origin !== false && !headers.has('origin')) headers.set('origin', origin);
  if (options.body !== undefined) headers.set('content-type', 'application/json');
  return new NextRequest(url, { method, headers, body: options.body === undefined ? undefined : JSON.stringify(options.body) });
}
function selectedRequest(method = 'GET', options = {}) {
  return request(method, { ...options, headers: { cookie: `${PERSONA_COOKIE}=${TOKEN}`,
    [PERSONA_PAGE_HEADER]: personaSessionKey(TOKEN), ...options.headers } });
}
function json(body, status = 200) { return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }); }
function identity(overrides = {}) {
  return { person_id: PERSON.person_id, full_name: PERSON.full_name, roles: [PERSON.role_code],
    identity_subject: 'private-server-resolved-subject', permissions: [], ...overrides };
}
function mint(overrides = {}) { return { access_token: TOKEN, expires_in: 3600, ...PERSON_BODY, ...overrides }; }

test.beforeEach(() => {
  enabled();
  global.fetch = () => assert.fail('No unmocked network call is permitted');
});
test.afterEach(() => {
  for (const key of Object.keys(process.env)) if (!(key in savedEnv)) delete process.env[key];
  Object.assign(process.env, savedEnv);
  for (const [key, descriptor] of Object.entries(savedGlobals)) {
    if (descriptor) Object.defineProperty(global, key, descriptor); else delete global[key];
  }
});

test('persona mode is opt-in and directory is unavailable while disabled', async () => {
  delete process.env.STAFFING_DEMO_PERSONAS_ENABLED;
  assert.equal(personaModeEnabled(), false);
  const response = await GET(request());
  assert.equal(response.status, 404);
  assert.equal((await response.json()).code, 'PERSONAS_DISABLED');
});

test('production, bearer mode and mismatched integration flags cannot enable local profiles', () => {
  for (const [key, value] of [['NODE_ENV', 'production'], ['STAFFING_BACKEND_AUTH_MODE', 'bearer'],
    ['STAFFING_AGENTIC_ENABLED', 'false'], ['NEXT_PUBLIC_STAFFING_AGENTIC_ENABLED', 'false']]) {
    enabled(); process.env[key] = value;
    assert.throws(() => personaModeEnabled(), { code: 'PERSONA_CONFIGURATION' });
  }
});

test('persona requests and control credentials cannot reach non-loopback hosts', async () => {
  assert.throws(() => requirePersonaMode(request('GET', { base: 'http://10.0.0.10:3001' })), { code: 'LOCAL_AUTH_RESTRICTED' });
  process.env.STAFFING_BACKEND_URL = 'https://backend.example.test';
  await assert.rejects(staffingBackend(request(), '/v1/local-personas', 'GET', undefined, { personaManagement: true }), { code: 'LOCAL_AUTH_RESTRICTED' });
});

test('directory returns names, IDs and roles only, never backend identities or credentials', async () => {
  global.fetch = async (url, options) => {
    assert.equal(new URL(url).pathname, '/v1/local-personas');
    assert.equal(options.headers.Authorization, `Bearer ${CONTROL}`);
    return json({ personas: [{ ...PERSON, identity_subject: 'secret-subject', access_token: 'secret-token',
      email: 'private@example.test', location: 'Private location', skills: ['Hidden skill'] }] });
  };
  const response = await GET(request());
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('cache-control'), 'no-store');
  assert.deepEqual(await response.json(), { personas: [PERSON] });
});

test('malformed or unknown profile directory entries are rejected', async () => {
  for (const entry of [null, 'not-a-person', { ...PERSON, role_code: 'SUPER_ADMIN' }, { ...PERSON, role_name: 'Wrong role' },
    { ...PERSON, full_name: '' }, { ...PERSON, person_id: '../P-009' }]) {
    global.fetch = async () => json({ personas: [entry] });
    const response = await GET(request());
    assert.equal(response.status, 503);
    assert.equal((await response.json()).code, 'PERSONA_DIRECTORY_INVALID');
  }
});

test('session mint verifies fresh selected identity before setting an HttpOnly Strict cookie', async () => {
  const calls = [];
  global.fetch = async (url, options) => {
    calls.push({ path: new URL(url).pathname, options });
    if (calls.length === 1) {
      assert.equal(options.headers.Authorization, `Bearer ${CONTROL}`);
      assert.deepEqual(JSON.parse(options.body), PERSON_BODY);
      return json(mint());
    }
    assert.equal(new URL(url).pathname, '/v1/me');
    assert.equal(options.headers.Authorization, `Bearer ${TOKEN}`);
    return json(identity());
  };
  const response = await POST(request('POST', { path: '/api/personas/session', body: PERSON_BODY }));
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { ok: true });
  assert.deepEqual(calls.map(call => call.path), ['/v1/local-personas/session', '/v1/me']);
  const cookie = response.cookies.get(PERSONA_COOKIE);
  assert.equal(cookie.value, TOKEN);
  assert.equal(cookie.httpOnly, true);
  assert.equal(cookie.sameSite, 'strict');
  assert.equal(cookie.maxAge, 3600);
  assert.equal(cookie.path, '/');
  assert.equal(cookie.secure, false);
  assert.equal(response.headers.get('cache-control'), 'no-store');
});

test('HTTPS loopback session cookie is Secure and mint response body never contains its token', async () => {
  let count = 0;
  global.fetch = async () => json(++count === 1 ? mint() : identity());
  const response = await POST(request('POST', { base: 'https://localhost:3001', body: PERSON_BODY }));
  assert.equal(response.cookies.get(PERSONA_COOKIE).secure, true);
  assert.equal(await response.text(), '{"ok":true}');
});

test('session selection rejects arbitrary role, ID or extra identity fields before contacting backend', async () => {
  for (const body of [{ ...PERSON_BODY, identity_subject: 'another-person' }, { ...PERSON_BODY, role_code: 'POD_ADMIN' },
    ...['constructor', '__proto__', 'toString'].map(role_code => ({ ...PERSON_BODY, role_code })),
    { ...PERSON_BODY, person_id: '' }, [PERSON_BODY], null]) {
    const response = await POST(request('POST', { body }));
    assert.equal(response.status, 400);
    assert.equal((await response.json()).code, 'INVALID_PERSONA');
    assert.equal(response.cookies.get(PERSONA_COOKIE), undefined);
  }
});

test('changed or multi-role backend identity cannot mint the selected-person browser cookie', async () => {
  for (const returnedIdentity of [identity({ person_id: 'P-OTHER' }), identity({ roles: ['POD_LEAD'] }),
    identity({ roles: ['POD_CAPTAIN', 'SYSTEM_ADMINISTRATOR'] })]) {
    let count = 0;
    global.fetch = async () => json(++count === 1 ? mint() : returnedIdentity);
    const response = await POST(request('POST', { body: PERSON_BODY }));
    assert.equal(response.status, 409);
    assert.equal((await response.json()).code, 'PERSONA_MAPPING_CHANGED');
    assert.equal(response.cookies.get(PERSONA_COOKIE), undefined);
  }
});

test('invalid signed-session envelope is rejected before fresh-identity lookup', async () => {
  for (const session of [mint({ access_token: 'unsigned-token' }), mint({ expires_in: 0 }),
    mint({ expires_in: 28801 }), mint({ person_id: 'P-OTHER' }), mint({ role_code: 'POD_LEAD' })]) {
    let calls = 0;
    global.fetch = async () => { calls++; return json(session); };
    const response = await POST(request('POST', { body: PERSON_BODY }));
    assert.equal(response.status, 503);
    assert.equal((await response.json()).code, 'PERSONA_SESSION_INVALID');
    assert.equal(calls, 1);
    assert.equal(response.cookies.get(PERSONA_COOKIE), undefined);
  }
});

test('missing persona cookie never falls back to fixed Captain, enterprise cookie or Authorization header', async () => {
  await assert.rejects(staffingBackend(request('GET', { headers: {
    authorization: 'Bearer forged-admin', cookie: 'staffing_access_token=enterprise-cookie', 'x-staffing-role': 'POD Captain',
  } }), '/v1/me'), { code: 'PERSONA_REQUIRED', status: 401 });
});

test('selected-person cookie outranks Authorization and role headers without forwarding those overrides', async () => {
  global.fetch = async (_url, options) => {
    assert.deepEqual(options.headers, { Authorization: `Bearer ${TOKEN}`, 'Content-Type': 'application/json' });
    return json(identity());
  };
  assert.deepEqual(await staffingBackend(selectedRequest('GET', { headers: {
    authorization: 'Bearer forged-administrator', 'x-staffing-role': 'Administrator',
  } }), '/v1/me'), identity());
});

test('page fingerprint is SHA256 truncated to 32 hex characters, not the bearer token', () => {
  const key = personaSessionKey(TOKEN);
  assert.equal(key, crypto.createHash('sha256').update(TOKEN).digest('hex').slice(0, 32));
  assert.match(key, /^[a-f0-9]{32}$/);
  assert.notEqual(key, TOKEN);
  assert.notEqual(key, personaSessionKey(`${TOKEN}changed`));
});

test('missing or stale page fingerprint blocks reads and writes before backend fetch', async () => {
  for (const method of ['GET', 'POST']) {
    for (const key of [undefined, 'old-page-fingerprint']) {
      const headers = { cookie: `${PERSONA_COOKIE}=${TOKEN}` };
      if (key) headers[PERSONA_PAGE_HEADER] = key;
      await assert.rejects(staffingBackend(request(method, { headers }), '/v1/requests', method), { code: 'PERSONA_CHANGED', status: 409 });
    }
  }
});

test('expired backend persona session returns 401 without retrying a control or fixed identity', async () => {
  let calls = 0;
  global.fetch = async (_url, options) => {
    calls++; assert.equal(options.headers.Authorization, `Bearer ${TOKEN}`);
    return json({ error: { code: 'UNAUTHENTICATED', message: 'Session expired.' } }, 401);
  };
  await assert.rejects(staffingBackend(selectedRequest(), '/v1/me'), { status: 401, code: 'UNAUTHENTICATED' });
  assert.equal(calls, 1);
});

test('POST and DELETE require exact same origin, including localhost versus 127.0.0.1', async () => {
  for (const method of ['POST', 'DELETE']) {
    const handler = method === 'POST' ? POST : DELETE;
    for (const options of [{ origin: false }, { headers: { origin: 'http://localhost:3001' } },
      { headers: { origin: 'http://127.0.0.1:3002' } }, { headers: { 'sec-fetch-site': 'cross-site' } }]) {
      const response = await handler(request(method, { ...options, body: method === 'POST' ? PERSON_BODY : undefined }));
      assert.equal(response.status, 403);
      assert.equal((await response.json()).code, 'ORIGIN_REJECTED');
    }
  }
});

test('persona management flag is scoped to exactly two paths/methods', async () => {
  for (const [path, method] of [['/v1/me', 'GET'], ['/v1/requests', 'POST'], ['/v1/local-personas', 'POST'],
    ['/v1/local-personas/session', 'GET'], ['https://other.example.test/v1/local-personas', 'GET']]) {
    await assert.rejects(staffingBackend(request(method), path, method, {}, { personaManagement: true }), { status: 403, code: 'FORBIDDEN' });
  }
});

test('logout clears only the persona cookie and never calls backend or touches other cookies', async () => {
  const response = DELETE(request('DELETE', { headers: { cookie: `${PERSONA_COOKIE}=${TOKEN}; staffing_access_token=other-login; preferences=keep` } }));
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { ok: true });
  const cookies = response.cookies.getAll();
  assert.equal(cookies.length, 1);
  assert.equal(cookies[0].name, PERSONA_COOKIE);
  assert.equal(cookies[0].value, '');
  assert.equal(cookies[0].maxAge, 0);
  assert.equal(cookies[0].httpOnly, true);
  assert.equal(cookies[0].sameSite, 'strict');
});

function authorization(role, resources) {
  return { roles: [{ code: ROLE_CODES[role], name: role, active: true, permissions: resources.map(resourceCode => ({
    resourceCode, canView: true, canCreate: false, canUpdate: false, canApprove: false,
    canExport: false, canAdminister: false, accessScope: 'own',
  })) }] };
}
test('profile landing destinations use actual permitted persona-specific screens', () => {
  const resources = ['DASHBOARD', 'REQUESTS', 'TEAM_SKILLS', 'ADMINISTRATION'];
  const expected = { 'POD Captain': 'dashboard', 'POD Lead': 'requests', 'POD Member': 'interests', Administrator: 'admin' };
  for (const role of STAFFING_ROLES) assert.equal(personaLandingScreen(role, authorization(role, resources)), expected[role]);
});

test('landing falls back to first permitted screen rather than granting preferred access', () => {
  const allowed = authorization('Administrator', ['TEAM_SKILLS']);
  assert.equal(personaLandingScreen('Administrator', allowed), 'interests');
  assert.equal(canAccessScreen('Administrator', 'admin', allowed), false);
  assert.equal(personaLandingScreen('POD Captain', authorization('POD Captain', ['REQUESTS'])), 'requests');
  assert.equal(canAccessScreen('POD Member', 'admin', undefined), false);
});

function browser(key = personaSessionKey(TOKEN)) {
  const navigated = [];
  global.document = { querySelector: (selector) => {
    assert.equal(selector, 'meta[name="staffing-persona-session"]');
    return key ? { content: key } : null;
  } };
  global.window = { location: { origin: 'http://127.0.0.1:3001', assign: url => navigated.push(url) } };
  return navigated;
}

test('staffingFetch binds only same-origin API operations to the rendered page fingerprint', async () => {
  browser();
  const calls = [];
  global.fetch = async (input, options) => { calls.push({ input, headers: new Headers(options.headers) }); return json({ ok: true }); };
  await staffingFetch('/api/requests', { method: 'POST', headers: { [PERSONA_PAGE_HEADER]: 'forged-page', 'x-test': 'keep' } });
  await staffingFetch('http://127.0.0.1:3001/api/people');
  await staffingFetch('https://outside.example.test/api/requests');
  await staffingFetch('/static/resource');
  assert.equal(calls[0].headers.get(PERSONA_PAGE_HEADER), personaSessionKey(TOKEN));
  assert.equal(calls[0].headers.get('x-test'), 'keep');
  assert.equal(calls[1].headers.get(PERSONA_PAGE_HEADER), personaSessionKey(TOKEN));
  assert.equal(calls[2].headers.has(PERSONA_PAGE_HEADER), false);
  assert.equal(calls[3].headers.has(PERSONA_PAGE_HEADER), false);
  assert.equal(calls.some(call => [...call.headers.values()].some(value => value.includes(TOKEN))), false);
});

test('staffingFetch redirects stale or expired persona pages while preserving the response body', async () => {
  const navigated = browser();
  for (const payload of [{ code: 'PERSONA_CHANGED' }, { error: { code: 'UNAUTHENTICATED' } }, { code: 'PERSONA_REQUIRED' }]) {
    global.fetch = async () => json(payload, 409);
    const response = await staffingFetch('/api/requests');
    assert.deepEqual(await response.json(), payload);
  }
  assert.deepEqual(navigated, ['/', '/', '/']);
});

test('staffingFetch does not redirect ordinary permission failures or non-persona pages', async () => {
  const navigated = browser();
  global.fetch = async () => json({ code: 'FORBIDDEN' }, 403);
  await staffingFetch('/api/admin');
  assert.deepEqual(navigated, []);
  const noPersonaNavigation = browser(null);
  global.fetch = async (_input, options) => {
    assert.equal(new Headers(options.headers).has(PERSONA_PAGE_HEADER), false);
    return json({ code: 'PERSONA_REQUIRED' }, 401);
  };
  await staffingFetch('/api/requests');
  assert.deepEqual(noPersonaNavigation, []);
});

test('persona-change broadcasts contain no person data or session material', () => {
  const calls = [];
  global.BroadcastChannel = class {
    constructor(name) { calls.push(['channel', name]); }
    postMessage(message) { calls.push(['message', message]); }
    close() { calls.push(['close']); }
  };
  announcePersonaChange();
  assert.deepEqual(calls, [['channel', 'staffing-persona'], ['message', 'changed'], ['close']]);
});
