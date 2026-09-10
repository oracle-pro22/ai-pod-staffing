import 'server-only';

import oracledb from 'oracledb';
import { withOracleConnection } from '@/lib/db/oracle';
import { forbiddenError } from '@/lib/errors/staffing-api-error';
import { ROLE_CODES } from '@/types/roles';
import type { StaffingMutationContext } from '@/types/mutations';

/** Preview role validation is separate from future authenticated OCI identity mapping. */
export async function requireStaffingPermission(
  context: StaffingMutationContext,
  resourceCode: string,
  action: 'canView' | 'canCreate',
): Promise<void> {
  await withOracleConnection(async (connection) => {
    const result = await connection.execute<Record<string, unknown>>(`
      SELECT rp.can_view, rp.can_create, rp.access_scope
        FROM app_roles ar JOIN role_permissions rp ON rp.role_code = ar.role_code
       WHERE ar.role_code = :roleCode AND ar.role_name = :roleName
         AND ar.active_flag = 'Y' AND rp.resource_code = :resourceCode
    `, { roleCode: ROLE_CODES[context.role], roleName: context.role, resourceCode }, { outFormat: oracledb.OUT_FORMAT_OBJECT });
    const row = result.rows?.[0];
    if (!row || row.CAN_VIEW !== 'Y' || !['FULL', 'SCOPED', 'OWN'].includes(String(row.ACCESS_SCOPE))
      || (action === 'canCreate' && row.CAN_CREATE !== 'Y')) throw forbiddenError();
  });
}
