import 'server-only';
import oracledb, { type Connection } from 'oracledb';
import type { StaffingMutationContext } from '@/types/mutations';
import { ROLE_CODES } from '@/types/roles';
import { forbiddenError } from '@/lib/errors/staffing-api-error';

/** Existing enterprise identities without MVP accounts remain supported; a disabled/mismatched account never does. */
export const ACTIVE_IDENTITY_ACCOUNT_SQL = `(NOT EXISTS (
      SELECT 1 FROM app_accounts identity_account WHERE identity_account.identity_subject=ur.identity_subject
    ) OR EXISTS (
      SELECT 1 FROM app_accounts identity_account WHERE identity_account.identity_subject=ur.identity_subject
        AND identity_account.person_id=ur.person_id AND identity_account.active_flag='Y'
    ))`;

/** Recheck a backend-verified mapping inside the Oracle operation. No client supplied person IDs. */
export async function assertIdentityMapping(connection: Connection, context: StaffingMutationContext) {
  if (!context.authenticated) return;
  if (!context.personId) throw forbiddenError();
  const schema = await connection.execute<{ DB_USER: string; CURRENT_SCHEMA: string }>(
    "SELECT USER AS db_user, SYS_CONTEXT('USERENV','CURRENT_SCHEMA') AS current_schema FROM dual", {},
    { outFormat: oracledb.OUT_FORMAT_OBJECT });
  if (schema.rows?.[0]?.DB_USER !== 'AI_POD_STAFFING' || schema.rows[0].CURRENT_SCHEMA !== 'AI_POD_STAFFING') throw forbiddenError('Unexpected database schema.');
  const result = await connection.execute(`SELECT ur.person_id FROM app_user_roles ur
    JOIN people p ON p.person_id=ur.person_id AND p.active_flag='Y'
    JOIN app_roles ar ON ar.role_code=ur.role_code AND ar.active_flag='Y'
    WHERE ur.identity_subject=:identitySubject AND ur.person_id=:personId AND ur.role_code=:roleCode
    AND ur.active_flag='Y' AND ur.effective_from<=TRUNC(SYSDATE)
    AND (ur.effective_to IS NULL OR ur.effective_to>=TRUNC(SYSDATE))
    AND ${ACTIVE_IDENTITY_ACCOUNT_SQL}
    AND NOT EXISTS (SELECT 1 FROM roster_onboarding onboarding
      WHERE onboarding.person_id=ur.person_id AND onboarding.status NOT IN ('COMPLETE','REVIEW'))`,
    { identitySubject: context.actor, personId: context.personId, roleCode: ROLE_CODES[context.role] },
    { outFormat: oracledb.OUT_FORMAT_OBJECT });
  if (result.rows?.length !== 1) throw forbiddenError('Your employee role mapping changed. Sign in again.');
}
