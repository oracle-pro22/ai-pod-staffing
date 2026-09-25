/* Offline routing tests. Never contacts Oracle or the VM. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const root = path.resolve(__dirname, '..');
const original = Module._load;
let backend, legacyCalls = 0;
Module._load = function(id, parent, main) {
  if (id === 'server-only') return {};
  if (id === '@/backend/staffing/bridge') return { agenticEnabled: () => true, staffingBackend: (...args) => backend(...args) };
  if (id === '@/lib/auth/staffing-request-context') return { staffingRequestContext: async () => ({ authenticated: true, personId: 'P-TEST' }) };
  if (id === '@/lib/repositories/staffing-mutation-repository') return { createAvailabilityEvent: async () => { legacyCalls++; throw new Error('Unsafe legacy write'); } };
  if (id.startsWith('@/')) id = path.join(root, id.slice(2));
  return original.call(this, id, parent, main);
};
require.extensions['.ts'] = (m, file) => m._compile(ts.transpileModule(fs.readFileSync(file, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
}).outputText, file);
const { NextRequest } = require('next/server');
const { StaffingApiError } = require('../lib/errors/staffing-api-error.ts');
const { POST } = require('../app/api/availability/route.ts');
const { validateCreateAvailabilityPayload } = require('../lib/validation/staffing-mutations.ts');
const input = { personId: 'P-TEST', eventType: 'Leave', startsOn: '2099-01-05', endsOn: '2099-01-05', title: 'Leave', allocatedHours: 4 };

test('signed-in leave save delegates to the atomic Python endpoint on HTTP and localhost', async () => {
  for (const origin of ['http://140.245.228.123:8005', 'http://localhost:3001']) {
    backend = async (request, route, method, body) => {
      assert.equal(request.headers.get('origin'), origin);
      assert.equal(route, '/v1/availability'); assert.equal(method, 'POST');
      assert.deepEqual(body, input);
      return body;
    };
    const response = await POST(new NextRequest(`${origin}/api/availability`, {
      method: 'POST', headers: { origin, 'content-type': 'application/json' }, body: JSON.stringify(input),
    }));
    assert.equal(response.status, 201);
    assert.deepEqual(await response.json(), { data: input });
  }
  assert.equal(legacyCalls, 0);
});

test('backend refresh failure or permission denial never falls back to an unrefreshed insert', async () => {
  for (const status of [403, 409, 503]) {
    backend = async () => { throw new StaffingApiError('Save not completed', status, 'TEST_FAILURE'); };
    const response = await POST(new NextRequest('http://localhost:3001/api/availability', {
      method: 'POST', body: JSON.stringify(input),
    }));
    assert.equal(response.status, status);
    assert.equal((await response.json()).data, undefined);
  }
  assert.equal(legacyCalls, 0);
});

test('invalid hours are rejected before starting an availability transaction', () => {
  for (const allocatedHours of [0, -1, 1.001, 25]) {
    assert.throws(() => validateCreateAvailabilityPayload({ ...input, allocatedHours }));
  }
  assert.equal(validateCreateAvailabilityPayload({ ...input, allocatedHours: 0.29 }).allocatedHours, 0.29);
});
