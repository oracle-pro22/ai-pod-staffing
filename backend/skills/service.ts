import 'server-only';
import oracledb, { type Connection } from 'oracledb';
import { withOracleTransaction } from '@/lib/db/oracle';
import { StaffingApiError, conflictError, forbiddenError, validationError } from '@/lib/errors/staffing-api-error';
import { PREVIEW_PERSON_IDS } from '@/lib/preview-person-ids';
import { ROLE_CODES } from '@/types/roles';
import type { StaffingMutationContext } from '@/types/mutations';
import type { SelfSkillsProfile } from '@/types/self-skills';
import { validateSelfSkillsPatch } from './validation';
import { readDeliverableCatalogue, readDeliverableExperience, saveDeliverableExperience } from './deliverables';
import { assertIdentityMapping } from '@/lib/auth/identity-mapping';

type Row = Record<string, unknown>;
const options = { outFormat: oracledb.OUT_FORMAT_OBJECT } as const;

function previewPerson(context: StaffingMutationContext): string {
  if (context.authenticated && context.personId && ['POD Lead', 'POD Member'].includes(context.role)) return context.personId;
  if ((process.env.STAFFING_DATA_SOURCE ?? 'oracle').trim().toLowerCase() !== 'oracle') {
    throw new StaffingApiError('Skills management requires Oracle.', 503, 'ORACLE_REQUIRED');
  }
  if ((process.env.STAFFING_AUTH_MODE ?? 'preview').trim().toLowerCase() !== 'preview') {
    throw new StaffingApiError('Authenticated employee identity integration is not available yet.', 503, 'IDENTITY_MODE_UNAVAILABLE');
  }
  if (!['POD Lead', 'POD Member'].includes(context.role)
    || context.actor !== `PREVIEW:${context.role.toUpperCase().replaceAll(' ', '_')}`) throw forbiddenError();
  return context.role === 'POD Lead' ? PREVIEW_PERSON_IDS.podLeadPersonId : PREVIEW_PERSON_IDS.podMemberPersonId;
}

async function authorize(connection: Connection, context: StaffingMutationContext, write: boolean) {
  await assertIdentityMapping(connection, context);
  const result = await connection.execute<Row>(`
    SELECT rp.access_scope, rp.can_view, rp.can_create, rp.can_update
      FROM role_permissions rp JOIN app_roles ar ON ar.role_code = rp.role_code
     WHERE ar.role_code = :roleCode AND ar.role_name = :roleName AND ar.active_flag = 'Y'
       AND rp.resource_code = 'MY_SKILLS'
  `, { roleCode: ROLE_CODES[context.role], roleName: context.role }, options);
  const row = result.rows?.[0];
  if (!row || row.ACCESS_SCOPE !== 'OWN' || row.CAN_VIEW !== 'Y'
    || (write && (row.CAN_CREATE !== 'Y' || row.CAN_UPDATE !== 'Y'))) throw forbiddenError();
}

async function person(connection: Connection, personId: string, lock = false) {
  const result = await connection.execute<Row>(`
    SELECT /*+ NO_PARALLEL */ person_id, full_name, skills_version, deliverable_experience_json FROM people
     WHERE person_id = :personId AND active_flag = 'Y' ${lock ? 'FOR UPDATE WAIT 5' : ''}
  `, { personId }, options);
  const row = result.rows?.[0];
  if (!row) throw new StaffingApiError('The preview employee profile is missing or inactive.', 409, 'PROFILE_NOT_LINKED');
  return row;
}

async function catalogue(connection: Connection) {
  const result = await connection.execute<Row>(`
    SELECT interest_id, interest_name, assessment_type, derived_role_code
      FROM interests ORDER BY interest_name, interest_id
  `, {}, options);
  return result.rows ?? [];
}

async function readProfile(connection: Connection, personId: string): Promise<SelfSkillsProfile> {
  const employee = await person(connection, personId);
  const allSkills = await catalogue(connection);
  const allDeliverables = await readDeliverableCatalogue(connection);
  const savedDeliverables = readDeliverableExperience(employee.DELIVERABLE_EXPERIENCE_JSON);
  const assessments = await connection.execute<Row>(`
    SELECT pi.interest_id, i.interest_name, pi.strength, pi.interested_flag, pi.evidence_note, pi.source
      FROM person_interests pi JOIN interests i ON i.interest_id = pi.interest_id
     WHERE pi.person_id = :personId AND i.assessment_type = 'SELF_RATED'
     ORDER BY i.interest_name, i.interest_id
  `, { personId }, options);
  // A preview profile selection never grants this capability. Only actual, effective DB assignments do.
  const derived = await connection.execute<Row>(`
    SELECT DISTINCT i.interest_id, i.interest_name, ar.role_code
      FROM interests i JOIN app_roles ar ON ar.role_code = i.derived_role_code AND ar.active_flag = 'Y'
      JOIN app_user_roles aur ON aur.role_code = ar.role_code
     WHERE i.assessment_type = 'ROLE_DERIVED' AND aur.person_id = :personId
       AND aur.active_flag = 'Y' AND aur.effective_from <= TRUNC(SYSDATE)
       AND (aur.effective_to IS NULL OR aur.effective_to >= TRUNC(SYSDATE))
     ORDER BY i.interest_name
  `, { personId }, options);
  return {
    personId, fullName: String(employee.FULL_NAME), version: Number(employee.SKILLS_VERSION),
    identityMode: 'preview',
    deliverableCatalogue: allDeliverables.filter((row) => row.active).map(({ active: _active, ...row }) => row),
    deliverables: savedDeliverables.map(({ deliverableId, experienceLevel, contributionScope, interested, experience, name, projectName }) => {
      const current = allDeliverables.find((row) => row.deliverableId === deliverableId);
      return { deliverableId, experienceLevel, contributionScope, interested, experience,
        name: current?.name ?? name ?? deliverableId, projectName: current?.projectName ?? projectName ?? '', active: current?.active ?? false };
    }),
    catalogue: allSkills.filter((row) => row.ASSESSMENT_TYPE === 'SELF_RATED')
      .map((row) => ({ skillId: String(row.INTEREST_ID), name: String(row.INTEREST_NAME) })),
    skills: (assessments.rows ?? []).map((row) => ({
      skillId: String(row.INTEREST_ID), name: String(row.INTEREST_NAME),
      strength: row.STRENGTH == null ? null : Number(row.STRENGTH),
      interested: row.INTERESTED_FLAG === 'Y', evidence: String(row.EVIDENCE_NOTE ?? ''), source: String(row.SOURCE),
    })),
    roleCapabilities: (derived.rows ?? []).map((row) => ({ skillId: String(row.INTEREST_ID), name: String(row.INTEREST_NAME), roleCode: String(row.ROLE_CODE) })),
    warnings: allSkills.filter((row) => row.ASSESSMENT_TYPE === 'ROLE_DERIVED' && !row.DERIVED_ROLE_CODE)
      .map((row) => `${String(row.INTEREST_NAME)}: role mapping awaits confirmation.`),
  };
}

export async function getSelfSkills(context: StaffingMutationContext): Promise<SelfSkillsProfile> {
  const personId = previewPerson(context);
  return withOracleTransaction(async (connection) => {
    // One consistent version + assessments snapshot, including across concurrent saves.
    await connection.execute('SET TRANSACTION READ ONLY');
    await authorize(connection, context, false);
    const profile = await readProfile(connection, personId);
    return { ...profile, identityMode: context.authenticated ? 'authenticated' : 'preview' };
  });
}

/** Same OWN/write permission and employee resolution as Save, without changing the database. */
export async function requireSelfSkillsEditing(context: StaffingMutationContext): Promise<void> {
  const personId = previewPerson(context);
  await withOracleTransaction(async (connection) => {
    await connection.execute('SET TRANSACTION READ ONLY');
    await authorize(connection, context, true);
    await person(connection, personId);
  });
}

export async function updateSelfSkills(value: unknown, context: StaffingMutationContext): Promise<{ personId: string; version: number }> {
  const personId = previewPerson(context);
  const patch = validateSelfSkillsPatch(value);
  try {
    return await withOracleTransaction(async (connection) => {
      await connection.execute('ALTER SESSION DISABLE PARALLEL DML');
      await connection.execute('ALTER SESSION DISABLE PARALLEL QUERY');
      await authorize(connection, context, true);
      await person(connection, personId, true);
      // Start a fresh read AFTER any lock wait; do not compare a pre-wait snapshot.
      const employee = await person(connection, personId);
      if (Number(employee.SKILLS_VERSION) !== patch.version) throw conflictError('Your skills changed in another session. Reload before saving again.');
      await saveDeliverableExperience(connection, personId, employee.DELIVERABLE_EXPERIENCE_JSON, patch, context.actor);
      // Lock touched catalogue rows in stable order so classification cannot change
      // between validation and save. Untouched skills and other employees stay unchanged.
      for (const skillId of [...patch.upserts.map((row) => row.skillId), ...patch.removeSkillIds].sort()) {
        await connection.execute(`SELECT /*+ NO_PARALLEL */ interest_id FROM interests WHERE interest_id = :skillId FOR UPDATE WAIT 5`, { skillId }, options);
        const classification = await connection.execute<Row>(`SELECT assessment_type FROM interests WHERE interest_id = :skillId`, { skillId }, options);
        if (classification.rows?.[0]?.ASSESSMENT_TYPE !== 'SELF_RATED') throw validationError('Choose an existing self-assessed skill. Role-derived capabilities cannot be changed.');
      }
      for (const row of patch.upserts) {
        const binds = { personId, skillId: row.skillId, strength: row.strength, interestedFlag: row.interested ? 'Y' : 'N', evidence: row.evidence || null, actorName: context.actor };
        const result = await connection.execute(`
          UPDATE /*+ DISABLE_PARALLEL_DML NO_PARALLEL */ person_interests
             SET strength = :strength, interested_flag = :interestedFlag, evidence_note = :evidence,
                 source = 'Self-assessment', updated_by = :actorName, updated_at = SYSTIMESTAMP
           WHERE person_id = :personId AND interest_id = :skillId
        `, binds);
        if (!result.rowsAffected) await connection.execute(`
          INSERT INTO person_interests (person_id, interest_id, strength, interested_flag, evidence_note, source, updated_by, updated_at)
          VALUES (:personId, :skillId, :strength, :interestedFlag, :evidence, 'Self-assessment', :actorName, SYSTIMESTAMP)
        `, binds);
      }
      for (const skillId of patch.removeSkillIds) await connection.execute(`
        DELETE /*+ DISABLE_PARALLEL_DML NO_PARALLEL */ FROM person_interests
         WHERE person_id = :personId AND interest_id = :skillId
      `, { personId, skillId });
      await connection.execute(`
        UPDATE /*+ DISABLE_PARALLEL_DML NO_PARALLEL */ people SET skills_version = skills_version + 1
         WHERE person_id = :personId
      `, { personId });
      return { personId, version: patch.version + 1 };
    });
  } catch (error) {
    if (typeof error === 'object' && error && 'errorNum' in error && [30006, 54, 60, 8177].includes(Number(error.errorNum))) {
      throw conflictError('Your skills are being updated. Reload and try again.');
    }
    throw error;
  }
}
