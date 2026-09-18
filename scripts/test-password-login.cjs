/* Offline password bridge tests. No database or live HTTP calls. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const root = path.resolve(__dirname, '..');
const originalLoad = Module._load;
Module._load = function(id, parent, main) {
  if (id === 'server-only') return {};
  if (id === '@/lib/db/oracle') return { publicOracleError: () => 'Database operation failed.' };
  if (id.startsWith('@/')) id = path.join(root, id.slice(2));
  return originalLoad.call(this, id, parent, main);
};
require.extensions['.ts'] = (mod, filename) => mod._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true }, fileName: filename,
}).outputText, filename);
const { NextRequest } = require('next/server');
const { passwordModeEnabled, PASSWORD_COOKIE } = require('../backend/staffing/password-mode.ts');
const { personaModeEnabled, personaSessionKey, PERSONA_PAGE_HEADER } = require('../backend/staffing/persona-mode.ts');
const { staffingBackend, agenticEnabled } = require('../backend/staffing/bridge.ts');
const { POST: login } = require('../app/api/auth/login/route.ts');
const { POST: logout } = require('../app/api/auth/logout/route.ts');
const { GET: personas } = require('../app/api/personas/route.ts');
const { completeLogin } = require('../backend/staffing/login.ts');
const saved = { ...process.env }, originalFetch = global.fetch;
const token = 'aps1.' + 'a'.repeat(43);
const origin = 'http://140.245.228.123:8005';
function request(method='POST', body, headers={}) {
  return new NextRequest(origin + '/api/auth/login', { method, headers: {host: '140.245.228.123:8005', origin, ...headers},
    body: body === undefined ? undefined : JSON.stringify(body) });
}
function selected(method='GET', headers={}) {
  return request(method, undefined, {cookie: `${PASSWORD_COOKIE}=${token}`, [PERSONA_PAGE_HEADER]: personaSessionKey(token), ...headers});
}
function json(value,status=200) { return new Response(JSON.stringify(value), {status, headers:{'Content-Type':'application/json'}}); }
test.beforeEach(() => {
  Object.assign(process.env, { NODE_ENV:'production', STAFFING_AGENTIC_ENABLED:'true', NEXT_PUBLIC_STAFFING_AGENTIC_ENABLED:'true',
    STAFFING_BACKEND_AUTH_MODE:'password', STAFFING_APP_ORIGIN:origin, STAFFING_BACKEND_URL:'http://127.0.0.1:8015',
    STAFFING_DEMO_PERSONAS_ENABLED:'true', STAFFING_BACKEND_LOCAL_TOKEN:'old-control-token-'.repeat(3) });
  global.fetch = () => assert.fail('Unmocked network call');
});
test.afterEach(() => {
  for (const key of Object.keys(process.env)) if (!(key in saved)) delete process.env[key];
  Object.assign(process.env,saved); global.fetch = originalFetch;
});
test('password mode cannot fall back to preview or persona entry', async () => {
  assert.equal(passwordModeEnabled(),true); assert.equal(personaModeEnabled(),false);
  assert.equal((await personas(request('GET'))).status,404);
  process.env.STAFFING_AGENTIC_ENABLED='false'; process.env.NEXT_PUBLIC_STAFFING_AGENTIC_ENABLED='false';
  assert.throws(() => agenticEnabled(), {code:'LOGIN_CONFIGURATION'});
});
test('unauthenticated requests reject legacy cookies and role/Authorization headers', async () => {
  await assert.rejects(() => staffingBackend(request('GET', undefined, {authorization:'Bearer legacy', cookie:'staffing_access_token=legacy;staffing_persona_session=legacy', 'x-staffing-role':'Administrator'}), '/v1/me'), {code:'SIGN_IN_REQUIRED'});
});
test('login works on configured VM origin and stores only an HttpOnly session cookie', async () => {
  let sent;
  global.fetch = async (url,init) => { sent={url:String(url),init}; return json({access_token:token,expires_in:28800}); };
  const response = await login(request('POST',{email:'alex.rivera@oracle.com',password:'shared-test-password'}));
  assert.equal(response.status,200); assert.deepEqual(await response.json(),{ok:true});
  assert.equal(sent.url,'http://127.0.0.1:8015/v1/auth/password/login');
  assert.equal(sent.init.headers.Authorization,undefined);
  assert.match(response.headers.get('set-cookie'),/HttpOnly/i);
  assert.match(response.headers.get('set-cookie'),/SameSite=strict/i);
  assert.equal(response.cookies.get(PASSWORD_COOKIE).value,token);
});
test('login rejects cross-origin and extra role/person fields without contacting API', async () => {
  assert.equal((await login(request('POST',{email:'alex@oracle.com',password:'test'}, {origin:'http://other.test'}))).status,403);
  assert.equal((await login(request('POST',{email:'alex@oracle.com',password:'test',role:'POD_CAPTAIN'}))).status,400);
});
test('password cookie is authoritative and account switches invalidate old tabs', async () => {
  global.fetch = async (url,init) => { assert.equal(init.headers.Authorization,`Bearer ${token}`); return json({person_id:'P-001'}); };
  assert.deepEqual(await staffingBackend(selected('GET',{authorization:'Bearer fake'}),'/v1/me'),{person_id:'P-001'});
  await assert.rejects(() => staffingBackend(selected('POST',{[PERSONA_PAGE_HEADER]:'stale'}),'/v1/decisions','POST',{}), {code:'PERSONA_CHANGED'});
});
test('logout revokes the server session before clearing the browser cookie', async () => {
  let called = false;
  global.fetch = async (url,init) => { assert.match(String(url),/password\/logout$/); assert.equal(init.headers.Authorization,`Bearer ${token}`); called=true; return json({ok:true}); };
  const response = await logout(selected('POST'));
  assert.equal(response.status,200); assert.equal(called,true); assert.equal(response.cookies.get(PASSWORD_COOKIE).value,'');
});
test('organization callback and management options cannot bypass password mode', async () => {
  await assert.rejects(() => completeLogin(request('GET')), {code:'LOGIN_DISABLED'});
  await assert.rejects(() => staffingBackend(selected(), '/v1/local-personas','GET',undefined,{personaManagement:true}), {code:'PERSONAS_DISABLED'});
  await assert.rejects(() => staffingBackend(request(), '/v1/me','POST',{}, {passwordLogin:true}), {code:'FORBIDDEN'});
});
test('backend credential failure is returned without issuing a session', async () => {
  global.fetch = async () => json({error:{code:'INVALID_CREDENTIALS',message:'Unable to sign in.'}},401);
  const response = await login(request('POST',{email:'alex@oracle.com',password:'wrong'}));
  assert.equal(response.status,401); assert.equal(response.cookies.get(PASSWORD_COOKIE),undefined);
});
