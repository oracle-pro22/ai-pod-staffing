import { type NextRequest, NextResponse } from 'next/server';
import { completeLogin } from '@/backend/staffing/login';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export async function GET(request: NextRequest) {
  try { return await completeLogin(request); }
  catch { return NextResponse.json({ error: { message: 'Sign-in failed or expired. Start sign-in again; check your employee mapping if the problem continues.' } },
    { status: 401, headers: { 'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer' } }); }
}
