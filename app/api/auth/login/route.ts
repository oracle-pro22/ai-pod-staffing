import { beginLogin } from '@/backend/staffing/login';
import { staffingApiErrorResponse } from '@/lib/api/staffing-api-response';
import { NextRequest, NextResponse } from 'next/server';
import { passwordModeEnabled } from '@/backend/staffing/password-mode';
import { passwordLogin } from '@/backend/staffing/password-login';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export function GET(request: NextRequest) { try { return passwordModeEnabled() ? NextResponse.redirect(new URL('/', request.url)) : beginLogin(); } catch (e) { return staffingApiErrorResponse(e); } }
export async function POST(request: NextRequest) { try { return await passwordLogin(request); } catch (e) { return staffingApiErrorResponse(e); } }
