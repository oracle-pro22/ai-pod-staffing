import type { NextRequest } from 'next/server';
import { NextResponse } from 'next/server';

import { rephraseText } from '@/backend/ai/rephrase/service';
import { requireSelfSkillsEditing } from '@/backend/skills/service';
import { validateAiRephrasePayload } from '@/backend/ai/rephrase/validation';
import { staffingApiErrorResponse } from '@/lib/api/staffing-api-response';
import { staffingRequestContext } from '@/lib/auth/staffing-request-context';
import { requireStaffingPermission } from '@/lib/auth/staffing-authorization';
import { StaffingApiError } from '@/lib/errors/staffing-api-error';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function POST(request: NextRequest) {
  try {
    const context = staffingRequestContext(request);
    const body = await request.json().catch(() => {
      throw new StaffingApiError('The request body is not valid JSON.', 400, 'INVALID_JSON');
    });
    const input = validateAiRephrasePayload(body);
    if (input.field === 'deliverableExperience') await requireSelfSkillsEditing(context);
    else await requireStaffingPermission(context, 'REQUESTS', 'canCreate');
    const result = await rephraseText(input, context);
    return NextResponse.json(
      { data: result },
      { status: 200, headers: { 'Cache-Control': 'no-store' } },
    );
  } catch (error) {
    if (!(error instanceof StaffingApiError)) console.error('Unable to rephrase request text.', error);
    return staffingApiErrorResponse(error);
  }
}
