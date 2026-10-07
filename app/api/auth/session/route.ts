import type { NextRequest } from 'next/server';
import { passwordSession } from '@/backend/staffing/password-login';
import { staffingApiErrorResponse } from '@/lib/api/staffing-api-response';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  try { return await passwordSession(request); }
  catch (error) { return staffingApiErrorResponse(error); }
}

export async function POST(request: NextRequest) {
  try { return await passwordSession(request, true); }
  catch (error) { return staffingApiErrorResponse(error); }
}
