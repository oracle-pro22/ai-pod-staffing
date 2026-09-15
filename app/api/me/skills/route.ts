import { type NextRequest, NextResponse } from 'next/server';
import { staffingRequestContext } from '@/lib/auth/staffing-request-context';
import { staffingApiErrorResponse } from '@/lib/api/staffing-api-response';
import { validationError } from '@/lib/errors/staffing-api-error';
import { getSelfSkills, updateSelfSkills } from '@/backend/skills/service';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
const headers = { 'Cache-Control': 'no-store' };

export async function GET(request: NextRequest) {
  try {
    return NextResponse.json({ data: await getSelfSkills(await staffingRequestContext(request)) }, { headers });
  } catch (error) { return staffingApiErrorResponse(error); }
}

export async function PATCH(request: NextRequest) {
  try {
    const context = await staffingRequestContext(request);
    const raw = await request.text();
    if (Buffer.byteLength(raw, 'utf8') > 256000) throw validationError('Skills request is too large.');
    let body: unknown;
    try { body = JSON.parse(raw); } catch { throw validationError('Invalid JSON body.'); }
    return NextResponse.json({ data: await updateSelfSkills(body, context) }, { headers });
  } catch (error) { return staffingApiErrorResponse(error); }
}
