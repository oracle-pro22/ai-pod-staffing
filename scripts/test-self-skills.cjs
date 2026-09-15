/* Offline contract tests. Oracle SQL/locking still require the documented DB smoke test. */
const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const root = path.resolve(__dirname, '..');
const nativeLoad = Module._load;
const previewContext = { state: { role: 'POD Member' }, notify: () => {} };
let database, calls, commits, rollbacks, injectFailure;
let rephraseCalls = [];
let queue = Promise.resolve();
const catalogue = [
  { INTEREST_ID: 'SK-001', INTEREST_NAME: 'Project Manager (GTM SME)', ASSESSMENT_TYPE: 'ROLE_DERIVED', DERIVED_ROLE_CODE: null },
  { INTEREST_ID: 'SK-002', INTEREST_NAME: 'GTM SME', ASSESSMENT_TYPE: 'SELF_RATED' },
  { INTEREST_ID: 'SK-014', INTEREST_NAME: 'Comms Team', ASSESSMENT_TYPE: 'SELF_RATED' },
];
const deliverableCatalogue = [
  { DELIVERABLE_ID: 'DEL-001', DELIVERABLE_NAME: 'Launch communication', PROJECT_NAME: 'Service Launch', ACTIVE_FLAG: 'Y' },
  { DELIVERABLE_ID: 'DEL-002', DELIVERABLE_NAME: 'Demo video', PROJECT_NAME: 'Demo Package', ACTIVE_FLAG: 'Y' },
  { DELIVERABLE_ID: 'DEL-OLD', DELIVERABLE_NAME: 'Old launch asset', PROJECT_NAME: 'Service Launch', ACTIVE_FLAG: 'N' },
];
function reset() {
  process.env.STAFFING_DATA_SOURCE = 'oracle';
  process.env.STAFFING_AUTH_MODE = 'preview';
  calls = []; commits = 0; rollbacks = 0; injectFailure = null;
  database = {
    permitted: true, people: {
      'P-001': { PERSON_ID: 'P-001', FULL_NAME: 'Member One', SKILLS_VERSION: 0 },
      'P-006': { PERSON_ID: 'P-006', FULL_NAME: 'Lead Six', SKILLS_VERSION: 0 },
    },
    assessments: [
      { PERSON_ID: 'P-001', INTEREST_ID: 'SK-001', STRENGTH: 5, EVIDENCE_NOTE: 'Legacy project management rating', SOURCE: 'Excel', INTERESTED_FLAG: 'N' },
    ],
    derived: [],
  };
}
async function transaction(fn) {
  // Serialize the fixture transactions, like the person-level lock for two same-person saves.
  const before = queue;
  let release;
  queue = new Promise((resolve) => { release = resolve; });
  await before;
  const working = structuredClone(database);
  try {
    const result = await fn({ execute: async (sql, binds = {}) => {
      calls.push({ sql, binds });
      if (injectFailure?.(sql, binds)) throw Object.assign(new Error('Injected database failure'), { errorNum: 99999 });
      if (/^(ALTER SESSION|SET TRANSACTION)/.test(sql)) return {};
      if (/FROM role_permissions rp/.test(sql)) return { rows: working.permitted ? [{ ACCESS_SCOPE: 'OWN', CAN_VIEW: 'Y', CAN_CREATE: 'Y', CAN_UPDATE: 'Y' }] : [] };
      if (/FROM people/.test(sql)) return { rows: working.people[binds.personId] ? [structuredClone(working.people[binds.personId])] : [] };
      if (/FROM interests ORDER/.test(sql)) return { rows: structuredClone(catalogue) };
      if (/FROM interests WHERE interest_id/.test(sql)) return { rows: catalogue.filter((row) => row.INTEREST_ID === binds.skillId) };
      if (/FROM deliverables ORDER/.test(sql)) return { rows: structuredClone(deliverableCatalogue) };
      if (/FROM deliverables WHERE deliverable_id/.test(sql)) return { rows: deliverableCatalogue.filter((row) => row.DELIVERABLE_ID === binds.deliverableId) };
      if (/UPDATE.*people SET deliverable_experience_json/s.test(sql)) {
        working.people[binds.personId].DELIVERABLE_EXPERIENCE_JSON = binds.experienceJson.val;
        return { rowsAffected: 1 };
      }
      if (/FROM person_interests pi/.test(sql)) return { rows: working.assessments.filter((row) => row.PERSON_ID === binds.personId && row.INTEREST_ID !== 'SK-001')
        .map((row) => ({ ...row, INTEREST_NAME: catalogue.find((skill) => skill.INTEREST_ID === row.INTEREST_ID).INTEREST_NAME })) };
      if (/SELECT DISTINCT/.test(sql)) return { rows: structuredClone(working.derived) };
      if (/UPDATE.*person_interests/s.test(sql)) {
        const row = working.assessments.find((row) => row.PERSON_ID === binds.personId && row.INTEREST_ID === binds.skillId);
        if (!row) return { rowsAffected: 0 };
        Object.assign(row, { STRENGTH: binds.strength, INTERESTED_FLAG: binds.interestedFlag, EVIDENCE_NOTE: binds.evidence, SOURCE: 'Self-assessment' });
        return { rowsAffected: 1 };
      }
      if (/INSERT INTO person_interests/.test(sql)) {
        working.assessments.push({ PERSON_ID: binds.personId, INTEREST_ID: binds.skillId, STRENGTH: binds.strength,
          INTERESTED_FLAG: binds.interestedFlag, EVIDENCE_NOTE: binds.evidence, SOURCE: 'Self-assessment' });
        return { rowsAffected: 1 };
      }
      if (/DELETE .*FROM person_interests/s.test(sql)) {
        working.assessments = working.assessments.filter((row) => row.PERSON_ID !== binds.personId || row.INTEREST_ID !== binds.skillId);
        return { rowsAffected: 1 };
      }
      if (/UPDATE.*people SET skills_version/s.test(sql)) { working.people[binds.personId].SKILLS_VERSION += 1; return { rowsAffected: 1 }; }
      throw new Error('Unexpected SQL: ' + sql);
    } });
    database = working; commits += 1;
    return result;
  } catch (error) { rollbacks += 1; throw error; }
  finally { release(); }
}
Module._load = function (id, parent, main) {
  if (id === 'server-only') return {};
  if (id === '@/context/StaffingAppProvider') return { useStaffingApp: () => previewContext };
  if (id === '@/backend/ai/rephrase/service') return { rephraseText: async (input) => { rephraseCalls.push(input); return { suggestion: 'I contributed to the demo video with support from my team.' }; } };
  if (id === '@/lib/auth/staffing-authorization') return { requireStaffingPermission: async (context, resource, action) => {
    assert.equal(resource, 'REQUESTS'); assert.equal(action, 'canCreate');
    if (context.role !== 'POD Captain') throw require('../lib/errors/staffing-api-error.ts').forbiddenError();
  } };
  if (id === '@/lib/db/oracle') return { withOracleTransaction: transaction, publicOracleError: () => 'Database request failed.' };
  if (id.startsWith('@/')) id = path.join(root, id.slice(2));
  return nativeLoad.call(this, id, parent, main);
};
require.extensions['.tsx'] = require.extensions['.ts'] = (mod, filename) => {
  const result = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true }, fileName: filename,
  });
  mod._compile(result.outputText, filename);
};
const { validateSelfSkillsPatch } = require('../backend/skills/validation.ts');
const { getSelfSkills, updateSelfSkills } = require('../backend/skills/service.ts');
const { buildOracleStaffingViewModel } = require('../lib/mappers/oracle-staffing-mapper.ts');
const { GET, PATCH } = require('../app/api/me/skills/route.ts');
const { NextRequest } = require('next/server');
const member = { role: 'POD Member', actor: 'PREVIEW:POD_MEMBER' };
const lead = { role: 'POD Lead', actor: 'PREVIEW:POD_LEAD' };
const assessment = { skillId: 'SK-002', strength: 3, interested: true, evidence: 'Created a service launch communications plan.' };
const patch = (upserts = [assessment], version = 0) => ({ version, upserts });
const status = (expected) => (error) => error.status === expected;

test('validates ratings and distinguishes an unrated interest from a zero rating', () => {
  assert.equal(validateSelfSkillsPatch(patch()).upserts[0].strength, 3);
  const interest = validateSelfSkillsPatch(patch([{ skillId: 'SK-014', strength: null, interested: true }]));
  assert.equal(interest.upserts[0].strength, null);
  for (const strength of [0, 6, 2.5, '3', undefined, NaN]) assert.throws(() => validateSelfSkillsPatch(patch([{ ...assessment, strength }])), status(400));
  assert.throws(() => validateSelfSkillsPatch(patch([{ ...assessment, strength: null, interested: false }])), status(400));
  assert.throws(() => validateSelfSkillsPatch(patch([{ ...assessment, evidence: '  ' }])), status(400));
});

test('rejects identity/source overrides, duplicate operations, invalid versions and oversized evidence', () => {
  for (const extra of [{ personId: 'P-006' }, { source: 'Verified' }, { role: 'Administrator' }]) assert.throws(() => validateSelfSkillsPatch({ ...patch(), ...extra }), status(400));
  assert.throws(() => validateSelfSkillsPatch(patch([{ ...assessment, personId: 'P-006' }])), status(400));
  assert.throws(() => validateSelfSkillsPatch(patch([assessment, assessment])), status(400));
  assert.throws(() => validateSelfSkillsPatch({ ...patch(), removeSkillIds: ['SK-002'] }), status(400));
  assert.throws(() => validateSelfSkillsPatch(patch([{ ...assessment, evidence: '界'.repeat(667) }])), status(400));
  for (const version of [-1, null, '0', 0.5, 9999999999]) assert.throws(() => validateSelfSkillsPatch(patch([assessment], version)), status(400));
  assert.throws(() => validateSelfSkillsPatch({ version: 0 }), status(400));
});

test('GET uses a consistent snapshot and excludes legacy Project Manager ratings and selectable role skills', async () => {
  reset();
  database.assessments.push({ PERSON_ID: 'P-001', INTEREST_ID: 'SK-014', STRENGTH: null, INTERESTED_FLAG: 'Y', SOURCE: 'Self-assessment' });
  const result = await getSelfSkills(member);
  assert.equal(calls[0].sql, 'SET TRANSACTION READ ONLY');
  assert.deepEqual(result.catalogue.map((row) => row.skillId), ['SK-002', 'SK-014']);
  assert.equal(result.skills[0].strength, null);
  assert.equal(result.roleCapabilities.length, 0);
  assert.match(result.warnings[0], /mapping awaits confirmation/);
  assert.equal(database.assessments[0].STRENGTH, 5);
});

test('role capabilities query requires active effective DB assignments, not the demo profile', async () => {
  reset();
  await getSelfSkills(lead);
  const query = calls.find((call) => /SELECT DISTINCT/.test(call.sql));
  assert.equal(query.binds.personId, 'P-006');
  for (const fragment of ['app_user_roles', "ar.active_flag = 'Y'", "aur.active_flag = 'Y'", 'aur.effective_from <= TRUNC(SYSDATE)', 'aur.effective_to >= TRUNC(SYSDATE)', 'i.derived_role_code']) assert.ok(query.sql.includes(fragment));
  assert.ok(!query.sql.includes(':roleCode'));
});

test('saves work without an opt-in flag, ignore the obsolete false flag, and retain profile permissions', async () => {
  reset(); delete process.env.STAFFING_SKILLS_PREVIEW_WRITES;
  assert.equal((await updateSelfSkills(patch(), member)).version, 1);
  process.env.STAFFING_SKILLS_PREVIEW_WRITES = 'false';
  assert.equal((await updateSelfSkills(patch([{ ...assessment, strength: 4 }], 1), member)).version, 2);
  for (const role of ['Administrator', 'POD Captain']) await assert.rejects(updateSelfSkills(patch(), { role, actor: 'PREVIEW:X' }), status(403));
  process.env.STAFFING_AUTH_MODE = 'oci';
  await assert.rejects(getSelfSkills(member), (error) => error.code === 'IDENTITY_MODE_UNAVAILABLE');
});

test('missing permissions and missing employee fail closed without writes', async () => {
  reset(); database.permitted = false;
  await assert.rejects(updateSelfSkills(patch(), member), status(403));
  database.permitted = true; delete database.people['P-001'];
  await assert.rejects(updateSelfSkills(patch(), member), (error) => error.code === 'PROFILE_NOT_LINKED');
  assert.equal(commits, 0);
  assert.equal(database.assessments.length, 1);
});

test('rejects add, change and removal of role-derived or unknown catalogue IDs before DML', async () => {
  reset();
  for (const skillId of ['SK-001', 'SK-UNKNOWN']) {
    await assert.rejects(updateSelfSkills(patch([{ ...assessment, skillId }]), member), status(400));
    await assert.rejects(updateSelfSkills({ version: 0, removeSkillIds: [skillId] }, member), status(400));
  }
  assert.ok(!calls.some((call) => /UPDATE \/\*\+ DISABLE_PARALLEL_DML|INSERT INTO|DELETE \/\*/.test(call.sql)));
});

test('atomic save uses own person ID, preserves others and stamps self-assessment provenance', async () => {
  reset();
  database.assessments.push({ PERSON_ID: 'P-006', INTEREST_ID: 'SK-002', STRENGTH: 4, SOURCE: 'Excel' });
  const result = await updateSelfSkills(patch([assessment, { skillId: 'SK-014', strength: null, interested: true }]), member);
  assert.deepEqual(result, { personId: 'P-001', version: 1 });
  assert.ok(calls.some((call) => /FOR UPDATE WAIT 5/.test(call.sql)));
  const lockIndex = calls.findIndex((call) => /FROM people/.test(call.sql) && /FOR UPDATE/.test(call.sql));
  assert.match(calls[lockIndex + 1].sql, /FROM people/);
  assert.ok(!calls[lockIndex + 1].sql.includes('FOR UPDATE'));
  assert.equal(database.assessments.find((row) => row.PERSON_ID === 'P-006').STRENGTH, 4);
  const inserts = calls.filter((call) => /INSERT INTO/.test(call.sql));
  assert.equal(inserts.length, 2);
  assert.ok(inserts.every((call) => call.binds.personId === 'P-001' && call.binds.actorName === 'PREVIEW:POD_MEMBER' && call.sql.includes("'Self-assessment'")));
  assert.equal(commits, 1);
});

test('updates and explicit removals do not delete unrelated or legacy role-derived entries', async () => {
  reset();
  await updateSelfSkills(patch(), member);
  await updateSelfSkills(patch([{ ...assessment, strength: 4 }], 1), member);
  assert.equal(database.assessments.find((row) => row.INTEREST_ID === 'SK-002').STRENGTH, 4);
  await updateSelfSkills({ version: 2, removeSkillIds: ['SK-002'] }, member);
  assert.deepEqual(database.assessments.map((row) => row.INTEREST_ID), ['SK-001']);
  assert.equal(database.people['P-001'].SKILLS_VERSION, 3);
});

test('a later write failure rolls back earlier row changes and the profile version', async () => {
  reset();
  const original = structuredClone(database);
  injectFailure = (sql, binds) => /INSERT INTO/.test(sql) && binds.skillId === 'SK-014';
  await assert.rejects(updateSelfSkills(patch([assessment, { skillId: 'SK-014', strength: null, interested: true }]), member));
  assert.deepEqual(database, original);
  assert.equal(commits, 0); assert.equal(rollbacks, 1);
});

test('serialized concurrent saves with the same version allow one commit and reject the stale save', async () => {
  reset();
  const results = await Promise.allSettled([updateSelfSkills(patch(), member), updateSelfSkills(patch(), member)]);
  assert.equal(results.filter((result) => result.status === 'fulfilled').length, 1);
  assert.equal(results.find((result) => result.status === 'rejected').reason.status, 409);
  assert.equal(database.people['P-001'].SKILLS_VERSION, 1);
});

test('existing mapper excludes interest-only and role-derived ratings from rated skill calculations', () => {
  const snapshot = Object.fromEntries(['projectTypes','interests','people','customerMapping','deliverables','deliverableSkills','personInterests','availability','requests','requirements','recommendations','roles','rolePermissions','userRoles'].map((key) => [key, []]));
  snapshot.database = {};
  snapshot.interests = catalogue;
  snapshot.people = [{ PERSON_ID: 'P-001', FULL_NAME: 'Member One' }];
  snapshot.personInterests = [
    { PERSON_ID: 'P-001', INTEREST_ID: 'SK-001', STRENGTH: 5 },
    { PERSON_ID: 'P-001', INTEREST_ID: 'SK-002', STRENGTH: 3 },
    { PERSON_ID: 'P-001', INTEREST_ID: 'SK-014', STRENGTH: null },
  ];
  assert.deepEqual(buildOracleStaffingViewModel(snapshot).people[0].skills.map((row) => row.id), ['SK-002']);
});

test('HTTP routes return no-store, reject missing profiles, bad JSON and identity tampering', async () => {
  reset();
  const url = 'http://localhost:3001/api/me/skills';
  assert.equal((await GET(new NextRequest(url))).status, 401);
  const response = await GET(new NextRequest(url, { headers: { 'x-staffing-role': 'POD Member' } }));
  assert.equal(response.status, 200); assert.equal(response.headers.get('cache-control'), 'no-store');
  for (const body of ['not-json', JSON.stringify({ ...patch(), personId: 'P-006' })]) {
    const result = await PATCH(new NextRequest(url, { method: 'PATCH', headers: { 'x-staffing-role': 'POD Member' }, body }));
    assert.equal(result.status, 400);
  }
  const saved = await PATCH(new NextRequest(url, { method: 'PATCH', headers: { 'x-staffing-role': 'POD Lead' }, body: JSON.stringify(patch()) }));
  assert.equal(saved.status, 200);
  assert.equal((await saved.json()).data.personId, 'P-006');
});

test('migration safety: schema guards, backups, serial DML, retained history and no inferred assignments', () => {
  const sql = fs.readFileSync(path.join(root, 'sql/oracle/self_skills.sql'), 'utf8');
  assert.match(sql, /SESSION_USER/); assert.match(sql, /CURRENT_SCHEMA/);
  for (const kind of ['DML','QUERY','DDL']) assert.ok(sql.includes('ALTER SESSION DISABLE PARALLEL ' + kind));
  assert.match(sql, /backup_table\('PERSON_INTERESTS'/);
  assert.match(sql, /backup_table\('ROLE_PERMISSIONS'/);
  assert.ok(!/DROP TABLE|DELETE FROM|INSERT INTO app_user_roles/i.test(sql));
  assert.ok(!/SET derived_role_code\s*=/i.test(sql));
});

const { assessmentDraft, skillsPatch, skillsDraftError, fetchSelfSkills, saveSelfSkills } = require('../lib/self-skills-client.ts');
function uiProfile() {
  return {
    personId: 'P-001', fullName: 'Member One', version: 7, identityMode: 'preview',
    catalogue: [{ skillId: 'SK-002', name: 'GTM SME' }, { skillId: 'SK-014', name: 'Comms Team' }],
    skills: [{ skillId: 'SK-002', name: 'GTM SME', strength: 4.5, interested: false, evidence: 'Existing evidence', source: 'Excel' }],
    roleCapabilities: [], warnings: ['Project Manager (GTM SME): role mapping awaits confirmation.'],
    deliverables: [], deliverableCatalogue: [{ deliverableId: 'DEL-001', name: 'Launch communication', projectName: 'Service Launch' }],
  };
}

test('UI drafts preserve unchanged legacy ratings and send only actual edits or explicit removals', () => {
  const profile = uiProfile();
  const draft = assessmentDraft(profile);
  assert.deepEqual(skillsPatch(profile, draft), { version: 7, upserts: [], removeSkillIds: [] });
  assert.equal(skillsDraftError(profile, draft), null);
  draft.push({ skillId: 'SK-014', strength: null, interested: true, evidence: '' });
  const payload = skillsPatch(profile, draft);
  assert.equal(payload.upserts.length, 1);
  assert.equal(payload.upserts[0].skillId, 'SK-014');
  assert.equal('personId' in payload, false);
  assert.equal('source' in payload.upserts[0], false);
  assert.deepEqual(skillsPatch(profile, []).removeSkillIds, ['SK-002']);
  assert.equal(profile.skills.length, 1);
});

test('UI validates changed ratings, evidence, interest-only, duplicates, and unknown skills', () => {
  const profile = uiProfile();
  const draft = assessmentDraft(profile);
  draft[0].interested = true;
  assert.match(skillsDraftError(profile, draft), /1 to 5/);
  draft[0].strength = 4; draft[0].evidence = '  ';
  assert.match(skillsDraftError(profile, draft), /evidence note/);
  draft[0].strength = null;
  assert.equal(skillsDraftError(profile, draft), null);
  draft[0].interested = false;
  assert.match(skillsDraftError(profile, draft), /mark your interest/);
  assert.match(skillsDraftError(profile, [...draft, draft[0]]), /only once/);
  assert.match(skillsDraftError(profile, [{ ...draft[0], skillId: 'SK-001' }]), /current catalogue/);
});

test('client sends role + version, does not retry ambiguous saves and preserves HTTP conflict status', async () => {
  const originalFetch = global.fetch;
  const requests = [];
  try {
    global.fetch = async (url, init) => { requests.push({ url, init }); return Response.json({ data: uiProfile() }); };
    assert.equal((await fetchSelfSkills('POD Member')).version, 7);
    assert.equal(requests[0].init.cache, 'no-store');
    global.fetch = async (url, init) => { requests.push({ url, init }); return Response.json({ error: 'Reload before saving.' }, { status: 409 }); };
    await assert.rejects(saveSelfSkills('POD Member', skillsPatch(uiProfile(), [])), status(409));
    assert.equal(requests[1].init.headers['x-staffing-role'], 'POD Member');
    assert.deepEqual(JSON.parse(requests[1].init.body), { version: 7, upserts: [], removeSkillIds: ['SK-002'] });
    let attempts = 0;
    global.fetch = async () => { attempts++; throw new Error('Network lost'); };
    await assert.rejects(saveSelfSkills('POD Member', skillsPatch(uiProfile(), [])), /Save status is unknown/);
    assert.equal(attempts, 1);
    global.fetch = originalFetch;
  } finally { global.fetch = originalFetch; }
});

test('skills modal retains role capability controls without demo warnings or a saving feature flag', () => {
  const React = require('react');
  const { renderToStaticMarkup } = require('react-dom/server');
  const { ManageSkillsModal } = require('../components/overlays/ManageSkillsModal.tsx');
  const profile = uiProfile();
  const markup = renderToStaticMarkup(React.createElement(ManageSkillsModal, { initial: profile, canEdit: true, onClose() {}, onSaved() {} }));
  assert.match(markup, /staffing-create-request-modal staffing-skills-modal/);
  assert.match(markup, /Search catalogue skills/);
  assert.ok(!markup.includes('Demo saving is disabled'));
  assert.ok(!markup.includes('in demo preview'));
  assert.ok(!markup.includes('not verified expertise'));
  const modalSource = fs.readFileSync(path.join(root, 'components/overlays/ManageSkillsModal.tsx'), 'utf8');
  assert.ok(!modalSource.includes('writesEnabled'));
  assert.match(markup, /Project Manager comes from an assigned role/);
  assert.ok(!markup.includes('Proficiency — Project Manager'));
  assert.match(markup, /<button[^>]*disabled=""[^>]*>Save changes<\/button>/);
  assert.match(markup, /Evidence \(required\) — GTM SME/);
});

const experience = { deliverableId: 'DEL-001', experienceLevel: 'SUPPORTED', contributionScope: 'CONTRIBUTOR', interested: true, experience: 'Helped produce launch communications with guidance.' };
const deliveryPatch = (row = experience, version = 0) => ({ version, deliverableUpserts: [row] });

test('deliverable payload validates enums, interests, evidence, duplicates and server-owned fields', () => {
  assert.deepEqual(validateSelfSkillsPatch(deliveryPatch()).deliverableUpserts, [experience]);
  for (const change of [{ experienceLevel: 'Expert' }, { contributionScope: 'POD_LEAD' }, { interested: 'Y' }, { experience: '' },
    { experience: 'x'.repeat(8001) }, { updatedBy: 'someone' }, { deliverableId: 12 }, { experienceLevel: 'LEARNING', interested: false }]) {
    assert.throws(() => validateSelfSkillsPatch(deliveryPatch({ ...experience, ...change })), status(400));
  }
  assert.throws(() => validateSelfSkillsPatch({ ...deliveryPatch(), removeDeliverableIds: ['DEL-001'] }), status(400));
  assert.throws(() => validateSelfSkillsPatch({ version: 0, deliverableUpserts: [experience, experience] }), status(400));
  assert.equal(validateSelfSkillsPatch(deliveryPatch({ ...experience, experienceLevel: 'LEARNING', experience: '' })).deliverableUpserts[0].experience, '');
});

test('deliverable-only save round-trips on the own person without granting mapped skills or roles', async () => {
  reset();
  const original = structuredClone(database.assessments);
  const result = await updateSelfSkills(deliveryPatch(), member);
  assert.equal(result.version, 1);
  const stored = JSON.parse(database.people['P-001'].DELIVERABLE_EXPERIENCE_JSON);
  assert.equal(stored[0].source, 'Self-assessment'); assert.equal(stored[0].updatedBy, member.actor);
  assert.equal(stored[0].name, 'Launch communication');
  assert.equal(database.people['P-006'].DELIVERABLE_EXPERIENCE_JSON, undefined);
  assert.deepEqual(database.assessments, original); assert.deepEqual(database.derived, []);
  const profile = await getSelfSkills(member);
  assert.equal(profile.deliverables[0].experience, experience.experience);
  assert.deepEqual(profile.deliverableCatalogue.map((row) => row.deliverableId), ['DEL-001', 'DEL-002']);
  assert.ok(calls.some((call) => /FROM deliverables.*FOR UPDATE WAIT 5/s.test(call.sql)));
});

test('old skill-only clients preserve saved experience; deliverable removals preserve skill ratings', async () => {
  reset(); await updateSelfSkills(deliveryPatch(), member);
  const stored = database.people['P-001'].DELIVERABLE_EXPERIENCE_JSON;
  await updateSelfSkills(patch([assessment], 1), member);
  assert.equal(database.people['P-001'].DELIVERABLE_EXPERIENCE_JSON, stored);
  const skills = structuredClone(database.assessments);
  await updateSelfSkills({ version: 2, removeDeliverableIds: ['DEL-001'] }, member);
  assert.equal(database.people['P-001'].DELIVERABLE_EXPERIENCE_JSON, '[]');
  assert.deepEqual(database.assessments, skills);
});

test('canonical Python/imported experience is readable as text or native JSON without adding audit metadata', async () => {
  for (const native of [false, true]) {
    reset();
    const canonical = [{ ...experience }];
    const raw = native ? canonical : JSON.stringify(canonical);
    database.people['P-006'].DELIVERABLE_EXPERIENCE_JSON = structuredClone(raw);
    const profile = await getSelfSkills(lead);
    assert.equal(profile.deliverables.length, 1);
    assert.deepEqual(profile.deliverables[0], { ...experience, name: 'Launch communication', projectName: 'Service Launch', active: true });
    assert.deepEqual(database.people['P-006'].DELIVERABLE_EXPERIENCE_JSON, raw);
    assert.equal(calls.some(({ sql }) => /UPDATE|INSERT|DELETE/.test(sql)), false);
  }
});

test('saving an unrelated skill preserves canonical deliverable storage exactly', async () => {
  for (const native of [false, true]) {
    reset();
    const rows = [{ ...experience, importReference: { batch: 'import-v1', sourceRow: 17 } }];
    const raw = native ? rows : JSON.stringify(rows);
    database.people['P-001'].DELIVERABLE_EXPERIENCE_JSON = structuredClone(raw);
    await updateSelfSkills(patch(), member);
    assert.deepEqual(database.people['P-001'].DELIVERABLE_EXPERIENCE_JSON, raw);
  }
});

test('editing one imported deliverable retains untouched entries and extension fields', async () => {
  reset();
  const untouched = { ...experience, importReference: { batch: 'import-v1', sourceRow: 17 } };
  const changed = { ...experience, deliverableId: 'DEL-002', importReference: { batch: 'import-v1', sourceRow: 18 } };
  database.people['P-001'].DELIVERABLE_EXPERIENCE_JSON = [untouched, changed];
  await updateSelfSkills(deliveryPatch({ ...experience, deliverableId: 'DEL-002', experience: 'Updated only my demo video evidence.' }), member);
  const saved = JSON.parse(database.people['P-001'].DELIVERABLE_EXPERIENCE_JSON);
  assert.deepEqual(saved.find(row => row.deliverableId === 'DEL-001'), untouched);
  const updated = saved.find(row => row.deliverableId === 'DEL-002');
  assert.equal(updated.experience, 'Updated only my demo video evidence.');
  assert.deepEqual(updated.importReference, changed.importReference);
  assert.equal(updated.name, 'Demo video');
  assert.equal(updated.source, 'Self-assessment');
  assert.equal(updated.updatedBy, member.actor);
  assert.equal('updatedBy' in saved.find(row => row.deliverableId === 'DEL-001'), false);
});

test('imported missing-catalogue references remain visible by ID and removable without dropping evidence on read', async () => {
  reset();
  const canonical = { ...experience, deliverableId: 'DEL-REMOVED' };
  database.people['P-001'].DELIVERABLE_EXPERIENCE_JSON = JSON.stringify([canonical]);
  const profile = await getSelfSkills(member);
  assert.deepEqual(profile.deliverables[0], { ...canonical, name: 'DEL-REMOVED', projectName: '', active: false });
  assert.deepEqual(JSON.parse(database.people['P-001'].DELIVERABLE_EXPERIENCE_JSON), [canonical]);
  await updateSelfSkills({ version: 0, removeDeliverableIds: ['DEL-REMOVED'] }, member);
  assert.equal(database.people['P-001'].DELIVERABLE_EXPERIENCE_JSON, '[]');
});

test('optional imported metadata is validated when present, without weakening canonical evidence validation', async () => {
  reset();
  for (const extra of [{ source: null }, { updatedBy: 42 }, { name: {} }, { interested: 'Y' }, { experienceLevel: 'Unknown' }]) {
    const raw = JSON.stringify([{ ...experience, ...extra }]);
    database.people['P-001'].DELIVERABLE_EXPERIENCE_JSON = raw;
    await assert.rejects(getSelfSkills(member), error => error.code === 'INVALID_DELIVERABLE_PROFILE');
    await assert.rejects(updateSelfSkills(deliveryPatch(), member), error => error.code === 'INVALID_DELIVERABLE_PROFILE');
    assert.equal(database.people['P-001'].DELIVERABLE_EXPERIENCE_JSON, raw);
  }
});

test('combined saves rollback deliverable JSON when a later skill write fails', async () => {
  reset(); const original = structuredClone(database);
  injectFailure = (sql) => /INSERT INTO person_interests/.test(sql);
  await assert.rejects(updateSelfSkills({ ...deliveryPatch(), upserts: [assessment] }, member));
  assert.deepEqual(database, original); assert.equal(commits, 0); assert.equal(rollbacks, 1);
});

test('retired/unknown deliverables reject upserts; historical experience is visible and removable', async () => {
  reset();
  for (const deliverableId of ['DEL-OLD', 'MISSING']) await assert.rejects(updateSelfSkills(deliveryPatch({ ...experience, deliverableId }), member), status(400));
  database.people['P-001'].DELIVERABLE_EXPERIENCE_JSON = JSON.stringify([{ ...experience, deliverableId: 'DEL-OLD', name: 'Old launch asset',
    projectName: 'Service Launch', source: 'Self-assessment', updatedAt: '2026-09-10T00:00:00Z', updatedBy: member.actor }]);
  assert.equal((await getSelfSkills(member)).deliverables[0].active, false);
  await updateSelfSkills({ version: 0, removeDeliverableIds: ['DEL-OLD'] }, member);
  assert.equal(database.people['P-001'].DELIVERABLE_EXPERIENCE_JSON, '[]');
});

test('malformed saved JSON fails visibly and is never overwritten with an empty draft', async () => {
  reset();
  for (const raw of ['{"not":"an array"}', '[{"deliverableId":"DEL-001"}]', 'not json']) {
    database.people['P-001'].DELIVERABLE_EXPERIENCE_JSON = raw;
    await assert.rejects(getSelfSkills(member), (error) => error.code === 'INVALID_DELIVERABLE_PROFILE');
    await assert.rejects(updateSelfSkills(deliveryPatch(), member), (error) => error.code === 'INVALID_DELIVERABLE_PROFILE');
    assert.equal(database.people['P-001'].DELIVERABLE_EXPERIENCE_JSON, raw);
  }
});

test('skills and deliverables share the same version so concurrent edits cannot lose data', async () => {
  reset();
  const results = await Promise.allSettled([updateSelfSkills(deliveryPatch(), member), updateSelfSkills(patch(), member)]);
  assert.equal(results.filter((row) => row.status === 'fulfilled').length, 1);
  assert.equal(results.find((row) => row.status === 'rejected').reason.status, 409);
});

test('deliverable UI diff preserves untouched entries and ignores server-owned metadata', () => {
  const { deliverableDraft, deliverablePatch: diff } = require('../lib/deliverable-experience.ts');
  const profile = { ...uiProfile(), deliverables: [{ ...experience, name: 'Launch communication', projectName: 'Service Launch', active: true }] };
  const draft = deliverableDraft(profile);
  assert.deepEqual(diff(profile, draft), { deliverableUpserts: [], removeDeliverableIds: [] });
  draft[0].experience += ' More details.';
  const result = diff(profile, draft);
  assert.equal(result.deliverableUpserts.length, 1); assert.equal('name' in result.deliverableUpserts[0], false);
  assert.deepEqual(diff(profile, []).removeDeliverableIds, ['DEL-001']);
});

test('multiple experience textareas use unique status IDs and render in-place rephrase controls', () => {
  const React = require('react'); const { renderToStaticMarkup } = require('react-dom/server');
  const { ManageSkillsModal } = require('../components/overlays/ManageSkillsModal.tsx');
  const profile = uiProfile();
  profile.deliverableCatalogue.push({ deliverableId: 'DEL-002', name: 'Demo video', projectName: 'Demo Package' });
  profile.deliverables = profile.deliverableCatalogue.map((row) => ({ ...experience, ...row, active: true }));
  const markup = renderToStaticMarkup(React.createElement(ManageSkillsModal, { initial: profile, canEdit: true, onClose() {}, onSaved() {} }));
  assert.match(markup, /Search catalogue deliverables/);
  assert.match(markup, /Contribution scope/); assert.match(markup, /Can deliver with support/);
  assert.equal((markup.match(/Rephrase with AI/g) ?? []).length, 2);
  const ids = [...markup.matchAll(/id="([^"]+)" class="staffing-ai-rephrase-status"/g)].map((match) => match[1]);
  assert.equal(ids.length, 2); assert.equal(new Set(ids).size, 2);
});

test('rephrase endpoint uses OWN skill-edit permission for experience and request-create permission for objectives', async () => {
  reset(); rephraseCalls = [];
  const { POST } = require('../app/api/ai/rephrase/route.ts');
  const request = (role, field = 'deliverableExperience') => new NextRequest('http://localhost:3001/api/ai/rephrase', {
    method: 'POST', headers: { 'x-staffing-role': role }, body: JSON.stringify({ field, text: 'I helped make a demo video with my team.' }),
  });
  for (const role of ['POD Lead', 'POD Member']) assert.equal((await POST(request(role))).status, 200);
  assert.equal(rephraseCalls.length, 2);
  database.permitted = false;
  assert.equal((await POST(request('POD Member'))).status, 403);
  database.permitted = true;
  for (const role of ['POD Captain', 'Administrator']) assert.equal((await POST(request(role))).status, 403);
  assert.equal((await POST(request('POD Member', 'businessObjectives'))).status, 403);
  assert.equal((await POST(request('POD Captain', 'businessObjectives'))).status, 200);
  assert.equal(rephraseCalls.length, 3);
  assert.ok(!calls.some((call) => /UPDATE|INSERT INTO|DELETE FROM/.test(call.sql)));
});

test('experience rephrase prompt preserves contribution, qualifications and learning intent', () => {
  const { validateAiRephrasePayload } = require('../backend/ai/rephrase/validation.ts');
  const { buildAiRephrasePrompt } = require('../backend/ai/rephrase/prompt.ts');
  const input = validateAiRephrasePayload({ field: 'deliverableExperience', text: 'I want to learn how to make demo videos.', context: { deliverables: ['Demo video'] } });
  const prompt = buildAiRephrasePrompt(input);
  assert.match(prompt.instructions, /Never turn an interest or learning goal into claimed experience/);
  assert.match(prompt.instructions, /owned it end-to-end/); assert.match(prompt.source, /Demo video/);
  assert.throws(() => validateAiRephrasePayload({ field: 'deliverableExperience', text: 'x'.repeat(6001) }), status(400));
});

test('experience migration is additive, schema-scoped, serial and resumable without destructive fallback', () => {
  const sql = fs.readFileSync(path.join(root, 'sql/oracle/deliverable_experience.sql'), 'utf8');
  for (const text of ['SESSION_USER', 'CURRENT_SCHEMA', 'SKILLS_VERSION', 'IS JSON', 'IF n = 0 THEN', 'AI_POD_STAFFING.PEOPLE']) assert.ok(sql.includes(text));
  assert.ok(!/DROP TABLE|DELETE FROM|TRUNCATE TABLE|CREATE TABLE|UPDATE PEOPLE/i.test(sql));
});
