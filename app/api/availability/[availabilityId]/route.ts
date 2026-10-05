import type { NextRequest } from 'next/server';
import { NextResponse } from 'next/server';

import { staffingApiErrorResponse } from '@/lib/api/staffing-api-response';
import { StaffingApiError } from '@/lib/errors/staffing-api-error';
import { validateCreateAvailabilityPayload } from '@/lib/validation/staffing-mutations';
import { staffingBackend } from '@/backend/staffing/bridge';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

function identifier(value: string): string {
  if (!/^\d{1,18}$/.test(value)) throw new StaffingApiError('Availability event not found.', 404, 'NOT_FOUND');
  return value;
}

export async function PATCH(request: NextRequest, context: { params: Promise<{ availabilityId: string }> }) {
  try {
    const { availabilityId } = await context.params;
    const body = await request.json().catch(() => {
      throw new StaffingApiError('The request body is not valid JSON.', 400, 'INVALID_JSON');
    });
    const input = validateCreateAvailabilityPayload(body);
    if (!Number.isSafeInteger(body.revision) || body.revision < 1) throw new StaffingApiError('Refresh this event before editing.', 409, 'STALE_AVAILABILITY');
    const data = await staffingBackend(request, `/v1/availability/${identifier(availabilityId)}`, 'PATCH', { ...input, revision: body.revision });
    return NextResponse.json({ data }, { headers: { 'Cache-Control': 'no-store' } });
  } catch (error) {
    return staffingApiErrorResponse(error);
  }
}

export async function DELETE(request: NextRequest, context: { params: Promise<{ availabilityId: string }> }) {
  try {
    const { availabilityId } = await context.params;
    const body = await request.json().catch(() => null);
    if (!body || !Number.isSafeInteger(body.revision) || body.revision < 1 || typeof body.effectiveOn !== 'string') {
      throw new StaffingApiError('Refresh this event and choose when to end it.', 409, 'STALE_AVAILABILITY');
    }
    const data = await staffingBackend(request, `/v1/availability/${identifier(availabilityId)}`, 'DELETE', body);
    return NextResponse.json({ data }, { headers: { 'Cache-Control': 'no-store' } });
  } catch (error) {
    return staffingApiErrorResponse(error);
  }
}
