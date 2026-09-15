import type { NextRequest } from 'next/server';
import { logout } from '@/backend/staffing/login';
import { staffingApiErrorResponse } from '@/lib/api/staffing-api-response';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export function POST(request: NextRequest) { try { return logout(request); } catch (e) { return staffingApiErrorResponse(e); } }
