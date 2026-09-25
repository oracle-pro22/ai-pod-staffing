/* Offline browser simulation: HTTP exposes getRandomValues but not randomUUID. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { webcrypto } = require('node:crypto');
const ts = require('typescript');
const root = path.resolve(__dirname, '..');
const source = ts.transpileModule(fs.readFileSync(path.join(root, 'lib/browser-id.ts'), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;

for (const secure of [false, true]) {
  test(`unique operation IDs on ${secure ? 'HTTPS/localhost' : 'public HTTP without randomUUID'}`, () => {
    const crypto = { getRandomValues: array => webcrypto.getRandomValues(array) };
    if (secure) crypto.randomUUID = () => webcrypto.randomUUID();
    const context = { exports: {}, crypto };
    vm.runInNewContext(source, context);
    const ids = Array.from({ length: 1000 }, () => context.exports.browserId());
    assert.equal(new Set(ids).size, 1000);
    ids.forEach(id => assert.match(id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/));
  });
}

test('fitment operations and success/error toasts use the HTTP-compatible helper', () => {
  for (const file of ['components/screens/fitment/LiveStaffingReview.tsx', 'context/StaffingAppProvider.tsx']) {
    const text = fs.readFileSync(path.join(root, file), 'utf8');
    assert.match(text, /import \{ browserId \} from '@\/lib\/browser-id'/);
    assert.match(text, /browserId\(\)/);
    assert.doesNotMatch(text, /\.randomUUID\(/);
  }
});
