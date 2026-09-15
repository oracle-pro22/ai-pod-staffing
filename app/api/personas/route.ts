import type { NextRequest } from 'next/server';
import { listPersonas } from '@/backend/staffing/personas';
import { staffingApiErrorResponse } from '@/lib/api/staffing-api-response';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export async function GET(request: NextRequest) {
  try { return await listPersonas(request); } catch (error) { return staffingApiErrorResponse(error); }
}
