import 'server-only';

import type { NextRequest } from 'next/server';

import { StaffingApiError } from '@/lib/errors/staffing-api-error';
import { isStaffingRole } from '@/types/roles';
import type { StaffingMutationContext } from '@/types/mutations';

export function staffingRequestContext(request: NextRequest): StaffingMutationContext {
  const mode = (process.env.STAFFING_AUTH_MODE ?? 'preview').trim().toLowerCase();
  if (mode !== 'preview') {
    throw new StaffingApiError('The configured identity mode is not available yet.', 503, 'IDENTITY_MODE_UNAVAILABLE');
  }

  const role = request.headers.get('x-staffing-role');
  if (!isStaffingRole(role)) {
    throw new StaffingApiError('Choose a valid application role and try again.', 401, 'ROLE_REQUIRED');
  }

  // Preview mode deliberately mirrors the role selector used by the prototype.
  // In production, actor will come from the authenticated OCI identity subject.
  return { role, actor: `PREVIEW:${role.toUpperCase().replaceAll(' ', '_')}` };
}
