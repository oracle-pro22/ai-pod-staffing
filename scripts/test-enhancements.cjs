/* Offline editor interactions and Next proxy checks; no database or network calls. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const React = require('react');
const root = path.resolve(__dirname, '..');
const nativeLoad = Module._load;
let harness;
let responses = [];
let calls = [];
let forwarded = [];
const hookReact = { ...React,
  useState(initial) {
    const h = harness, i = h.index++;
    if (!(i in h.slots)) h.slots[i] = initial;
    return [h.slots[i], value => { h.slots[i] = typeof value === 'function' ? value(h.slots[i]) : value; }];
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
  if (id === 'server-only') return {};
  if (id === 'react' && parent.filename.endsWith('EnhancementNotepad.tsx')) return hookReact;
  if (id === '@/lib/staffing-fetch') return { staffingFetch: async (...args) => {
    calls.push(args);
    const response = responses.shift();
    if (response instanceof Error) throw response;
    assert.ok(response, 'Every request must have an offline response');
    return response;
  } };
  if (id === '@/backend/staffing/bridge') return { staffingBackend: async (...args) => {
    forwarded.push(args); return { content: 'saved', revision: 2 };
  } };
  if (id.startsWith('@/')) id = path.join(root, id.slice(2));
  return nativeLoad.call(this, id, parent, main);
};
for (const extension of ['.ts', '.tsx']) require.extensions[extension] = (mod, filename) => mod._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true }, fileName: filename,
}).outputText, filename);
const { EnhancementNotepad } = require('../components/screens/administration/EnhancementNotepad.tsx');
const { GET, POST } = require('../app/api/agentic/[...path]/route.ts');
const { NextRequest } = require('next/server');
const document = (content = 'Original', revision = 1) => ({ content, revision, updated_by_name: 'Admin', updated_at: '2026-10-14T00:00:00Z' });
const response = (value, status = 200) => new Response(JSON.stringify(status === 200 ? { data: value } : value), { status });
const flush = async () => { for (let i = 0; i < 4; i++) await new Promise(resolve => setImmediate(resolve)); };
function all(tree) {
  if (!tree || typeof tree !== 'object') return [];
  if (Array.isArray(tree)) return tree.flatMap(all);
  return [tree, ...all(tree.props?.children)];
}
function text(tree) {
  if (tree === null || tree === undefined || typeof tree === 'boolean') return '';
  if (Array.isArray(tree)) return tree.map(text).join('');
  if (typeof tree !== 'object') return String(tree);
  return text(tree.props?.children);
}
async function editor(canEdit = true) {
  calls = []; responses = [response(document())];
  global.window = { confirm: () => true, addEventListener() {}, removeEventListener() {} };
  const h = { index: 0, slots: [], effects: [], tree: null, dirty: false };
  const onDirtyChange = value => { h.dirty = value; };
  h.render = () => {
    harness = h; h.index = 0; h.effects = [];
    h.tree = EnhancementNotepad({ canEdit, onDirtyChange });
    for (const effect of h.effects) effect();
    return h.tree;
  };
  h.byId = id => all(h.tree).find(node => node.props?.id === id);
  h.button = label => all(h.tree).find(node => node.props?.onClick && text(node) === label);
  h.edit = value => { h.byId('enhancement-notes').props.onChange({ target: { value } }); h.render(); };
  h.click = async label => { const button = h.button(label); assert.ok(button, label); assert.ok(!button.props.disabled, label); button.props.onClick(); await flush(); h.render(); };
  h.render(); await flush(); h.render();
  return h;
}

test('editor loads plain text, explicitly saves, and disables unchanged save', async () => {
  const h = await editor();
  assert.ok(h.button('Save changes').props.disabled);
  const content = '  • café\n<script>alert(1)</script>\n';
  h.edit(content);
  assert.equal(calls.length, 1, 'Editing must not autosave');
  responses.push(response(document(content, 2)));
  await h.click('Save changes');
  assert.deepEqual(JSON.parse(calls[1][1].body), { content, expected_revision: 1 });
  assert.equal(h.byId('enhancement-notes').props.value, content);
  assert.equal(h.dirty, false);
  assert.match(text(h.tree), /notes saved/);
  assert.ok(!all(h.tree).some(node => node.props?.dangerouslySetInnerHTML));
});

test('failed save preserves the draft and revision for retry', async () => {
  const h = await editor(); h.edit('Keep my work');
  responses.push(response({ error: 'Database unavailable' }, 503));
  await h.click('Save changes');
  assert.equal(h.byId('enhancement-notes').props.value, 'Keep my work');
  assert.ok(h.dirty);
  assert.match(text(h.tree), /Database unavailable/);
  responses.push(response(document('Keep my work', 2)));
  await h.click('Save changes');
  assert.equal(JSON.parse(calls.at(-1)[1].body).expected_revision, 1);
});

test('conflict preserves both versions and saves only after deliberate reconciliation', async () => {
  const h = await editor(); h.edit('My idea');
  responses.push(response({ code: 'ENHANCEMENTS_CONFLICT' }, 409), response(document('Other admin idea', 2)));
  await h.click('Save changes');
  assert.equal(h.byId('enhancement-notes').props.value, 'My idea');
  assert.equal(h.byId('enhancement-latest').props.value, 'Other admin idea');
  assert.ok(h.button('Save changes').props.disabled);
  await h.click('Edit latest version');
  assert.equal(h.byId('enhancement-notes').props.value, 'Other admin idea');
  assert.equal(all(h.tree).find(n => n.props?.['aria-label'] === 'Retained previous draft').props.value, 'My idea');
  h.edit('Other admin idea\nMy idea');
  responses.push(response(document('Other admin idea\nMy idea', 3)));
  await h.click('Save changes');
  assert.equal(JSON.parse(calls.at(-1)[1].body).expected_revision, 2);
  assert.equal(h.dirty, false);
});

test('failed conflict reload retains draft and allows a safe retry', async () => {
  const h = await editor(); h.edit('Draft');
  responses.push(response({}, 409), new Error('Offline'));
  await h.click('Save changes');
  assert.equal(h.byId('enhancement-notes').props.value, 'Draft');
  assert.ok(h.button('Save changes').props.disabled);
  responses.push(response(document('New text', 3)));
  await h.click('Load latest without losing my draft');
  assert.equal(h.byId('enhancement-notes').props.value, 'Draft');
  assert.equal(h.byId('enhancement-latest').props.value, 'New text');
});

test('refresh warns before discarding unsaved text; view-only editor cannot save', async () => {
  const h = await editor(); h.edit('Draft');
  window.confirm = () => false;
  await h.click('Refresh');
  assert.equal(calls.length, 1);
  assert.equal(h.byId('enhancement-notes').props.value, 'Draft');
  const readOnly = await editor(false);
  assert.equal(readOnly.byId('enhancement-notes').props.readOnly, true);
  assert.equal(readOnly.button('Save changes'), undefined);
});

test('proxy allows only exact notepad endpoint and accommodates escaped full-size text', async () => {
  forwarded = [];
  const context = { params: Promise.resolve({ path: ['admin', 'enhancements'] }) };
  const get = await GET(new NextRequest('http://localhost/api/agentic/admin/enhancements'), context);
  assert.equal(get.status, 200);
  assert.equal(get.headers.get('cache-control'), 'no-store');
  const content = '\u0001'.repeat(50000);
  const result = await POST(new NextRequest('http://localhost/api/agentic/admin/enhancements', { method: 'POST', body: JSON.stringify({ content, expected_revision: 1 }) }), context);
  assert.equal(result.status, 200);
  assert.equal(forwarded.at(-1)[1], '/v1/admin/enhancements');
  assert.equal(forwarded.at(-1)[3].content, content);
  const denied = await GET(new NextRequest('http://localhost/api/agentic/admin/enhancements/anything'), { params: Promise.resolve({ path: ['admin', 'enhancements', 'anything'] }) });
  assert.equal(denied.status, 404);
  const huge = await POST(new NextRequest('http://localhost/api/agentic/admin/enhancements', { method: 'POST', body: 'x'.repeat(310001) }), context);
  assert.equal(huge.status, 413);
});
