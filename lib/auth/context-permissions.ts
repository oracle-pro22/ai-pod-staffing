import 'server-only';
import oracledb, { type Connection } from 'oracledb';
import type { StaffingMutationContext } from '@/types/mutations';
import { ROLE_CODES } from '@/types/roles';
import { ACTIVE_IDENTITY_ACCOUNT_SQL, assertIdentityMapping } from './identity-mapping';

export type ContextPermission = Record<string, unknown>;

/** Read current database grants for the verified identity, not its display role or a browser header. */
export async function contextPermissions(connection: Connection, context: StaffingMutationContext, resourceCode: string): Promise<ContextPermission[]> {
  await assertIdentityMapping(connection, context);
  const result = await connection.execute<ContextPermission>(`
    SELECT ar.role_code, rp.access_scope, rp.can_view, rp.can_create, rp.can_update,
           rp.can_approve, rp.can_export, rp.can_administer
      FROM app_roles ar JOIN role_permissions rp ON rp.role_code = ar.role_code
     WHERE ar.active_flag = 'Y' AND rp.resource_code = :resourceCode
       AND ${context.authenticated ? `EXISTS (
         SELECT 1 FROM app_user_roles ur
          WHERE ur.role_code = ar.role_code AND ur.identity_subject = :identitySubject
            AND ur.person_id = :personId AND ur.active_flag = 'Y'
            AND ur.effective_from <= TRUNC(SYSDATE)
            AND (ur.effective_to IS NULL OR ur.effective_to >= TRUNC(SYSDATE))
            AND ${ACTIVE_IDENTITY_ACCOUNT_SQL})`
      : 'ar.role_code = :roleCode AND ar.role_name = :roleName'}
  `, { resourceCode, ...(context.authenticated
    ? { identitySubject: context.actor, personId: context.personId }
    : { roleCode: ROLE_CODES[context.role], roleName: context.role }) }, { outFormat: oracledb.OUT_FORMAT_OBJECT });
  return result.rows ?? [];
}
