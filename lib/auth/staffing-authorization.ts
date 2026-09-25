import 'server-only';

import { withOracleConnection } from '@/lib/db/oracle';
import { forbiddenError } from '@/lib/errors/staffing-api-error';
import type { StaffingMutationContext } from '@/types/mutations';
import { contextPermissions } from './context-permissions';

/** Preview role validation is separate from future authenticated OCI identity mapping. */
export async function requireStaffingPermission(
  context: StaffingMutationContext,
  resourceCode: string,
  action: 'canView' | 'canCreate',
): Promise<void> {
  await withOracleConnection(async (connection) => {
    const permissions = await contextPermissions(connection, context, resourceCode);
    if (!permissions.some(row => row.CAN_VIEW === 'Y' && ['FULL', 'SCOPED', 'OWN'].includes(String(row.ACCESS_SCOPE))
      && (action !== 'canCreate' || row.CAN_CREATE === 'Y'))) throw forbiddenError();
  });
}
