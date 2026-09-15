import { type NextRequest, NextResponse } from 'next/server';
import { staffingRequestContext } from '@/lib/auth/staffing-request-context';
import { requireStaffingPermission } from '@/lib/auth/staffing-authorization';
import { staffingApiErrorResponse } from '@/lib/api/staffing-api-response';
import { StaffingApiError, validationError } from '@/lib/errors/staffing-api-error';
import { createPerson, listActivePeopleNames } from '@/lib/repositories/people-repository';
import { validateCreatePerson } from '@/lib/validation/people';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
function requireOracle() {
  if ((process.env.STAFFING_DATA_SOURCE ?? 'oracle').trim().toLowerCase() !== 'oracle') throw new StaffingApiError('People management requires Oracle.', 503, 'ORACLE_REQUIRED');
}
export async function GET(request: NextRequest) {
  try {
    requireOracle();
    const context = await staffingRequestContext(request);
    await requireStaffingPermission(context, 'REQUESTS', 'canCreate');
    return NextResponse.json({ data: await listActivePeopleNames() }, { headers: { 'Cache-Control': 'no-store' } });
  } catch (error) { return staffingApiErrorResponse(error); }
}
export async function POST(request: NextRequest) {
  try {
    requireOracle();
    const context = await staffingRequestContext(request);
    const body = await request.json().catch(() => { throw validationError('Invalid JSON body.'); });
    const data = await createPerson(validateCreatePerson(body), context);
    return NextResponse.json({ data }, { status: 201, headers: { 'Cache-Control': 'no-store' } });
  } catch (error) { return staffingApiErrorResponse(error); }
}
