import type { NextRequest } from 'next/server';
import { enterPersona, leavePersona } from '@/backend/staffing/personas';
import { staffingApiErrorResponse } from '@/lib/api/staffing-api-response';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export async function POST(request: NextRequest) {
  try { return await enterPersona(request); } catch (error) { return staffingApiErrorResponse(error); }
}
export function DELETE(request: NextRequest) {
  try { return leavePersona(request); } catch (error) { return staffingApiErrorResponse(error); }
}
