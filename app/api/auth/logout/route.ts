import type { NextRequest } from 'next/server';
import { logout } from '@/backend/staffing/login';
import { staffingApiErrorResponse } from '@/lib/api/staffing-api-response';
import { passwordModeEnabled } from '@/backend/staffing/password-mode';
import { passwordLogout } from '@/backend/staffing/password-login';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export async function POST(request: NextRequest) { try { return passwordModeEnabled() ? await passwordLogout(request) : logout(request); } catch (e) { return staffingApiErrorResponse(e); } }
