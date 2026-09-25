import type { NextRequest } from 'next/server';
import { NextResponse } from 'next/server';

import { staffingApiErrorResponse } from '@/lib/api/staffing-api-response';
import { staffingRequestContext } from '@/lib/auth/staffing-request-context';
import { StaffingApiError } from '@/lib/errors/staffing-api-error';
import { createStaffingRequest } from '@/lib/repositories/staffing-mutation-repository';
import { validateCreateRequestPayload } from '@/lib/validation/staffing-mutations';
import { agenticEnabled, verifiedCaptain } from '@/backend/staffing/bridge';
import { highestStaffingRole } from '@/types/roles';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function POST(request: NextRequest) {
  try {
    if ((process.env.STAFFING_DATA_SOURCE ?? 'oracle').trim().toLowerCase() !== 'oracle') {
      throw new StaffingApiError('Request saving requires the Oracle data source.', 503, 'ORACLE_REQUIRED');
    }
    const identity = agenticEnabled() ? await verifiedCaptain(request) : null;
    const context = identity
      ? { role: highestStaffingRole(identity.roles)!, actor: identity.identity_subject,
        personId: identity.person_id, authenticated: true, responsibleCaptainId: identity.person_id }
      : await staffingRequestContext(request);
    const body = await request.json().catch(() => {
      throw new StaffingApiError('The request body is not valid JSON.', 400, 'INVALID_JSON');
    });
    const input = validateCreateRequestPayload(body);
    const result = await createStaffingRequest(input, context);
    return NextResponse.json(
      { data: result },
      { status: 201, headers: { 'Cache-Control': 'no-store' } },
    );
  } catch (error) {
    if (!(error instanceof StaffingApiError)) console.error('Unable to create staffing request.', { type: error instanceof Error ? error.name : 'Unknown' });
    return staffingApiErrorResponse(error);
  }
}
