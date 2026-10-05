import type { NextRequest } from 'next/server';
import { passwordChange } from '@/backend/staffing/password-login';
import { staffingApiErrorResponse } from '@/lib/api/staffing-api-response';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  try { return await passwordChange(request); }
  catch (error) { return staffingApiErrorResponse(error); }
}
