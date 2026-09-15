import 'server-only';

import type { NextRequest } from 'next/server';

import { StaffingApiError } from '@/lib/errors/staffing-api-error';
import { isStaffingRole } from '@/types/roles';
import type { StaffingMutationContext } from '@/types/mutations';
import { agenticEnabled, staffingBackend, type BackendIdentity } from '@/backend/staffing/bridge';
import { ROLE_CODES, STAFFING_ROLES } from '@/types/roles';

export async function staffingRequestContext(request: NextRequest): Promise<StaffingMutationContext> {
  if (agenticEnabled()) {
    const identity = await staffingBackend(request, '/v1/me') as BackendIdentity;
    const requested = request.headers.get('x-staffing-role');
    const role = requested ?? STAFFING_ROLES.find(r => identity.roles.includes(ROLE_CODES[r]));
    if (!isStaffingRole(role) || !identity.roles.includes(ROLE_CODES[role])) {
      throw new StaffingApiError('This profile is not assigned to your signed-in identity.', 403, 'FORBIDDEN');
    }
    return { role, actor: identity.identity_subject, personId: identity.person_id, authenticated: true };
  }
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
