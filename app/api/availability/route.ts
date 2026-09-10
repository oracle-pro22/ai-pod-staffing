import type { NextRequest } from 'next/server';
import { NextResponse } from 'next/server';

import { staffingApiErrorResponse } from '@/lib/api/staffing-api-response';
import { staffingRequestContext } from '@/lib/auth/staffing-request-context';
import { StaffingApiError } from '@/lib/errors/staffing-api-error';
import { createAvailabilityEvent } from '@/lib/repositories/staffing-mutation-repository';
import { validateCreateAvailabilityPayload } from '@/lib/validation/staffing-mutations';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function POST(request: NextRequest) {
  try {
    if ((process.env.STAFFING_DATA_SOURCE ?? 'oracle').trim().toLowerCase() !== 'oracle') {
      throw new StaffingApiError('Availability saving requires the Oracle data source.', 503, 'ORACLE_REQUIRED');
    }
    const context = staffingRequestContext(request);
    const body = await request.json().catch(() => {
      throw new StaffingApiError('The request body is not valid JSON.', 400, 'INVALID_JSON');
    });
    const input = validateCreateAvailabilityPayload(body);
    const result = await createAvailabilityEvent(input, context);
    return NextResponse.json(
      { data: result },
      { status: 201, headers: { 'Cache-Control': 'no-store' } },
    );
  } catch (error) {
    if (!(error instanceof StaffingApiError)) console.error('Unable to create availability event.', error);
    return staffingApiErrorResponse(error);
  }
}
