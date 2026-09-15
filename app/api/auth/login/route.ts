import { beginLogin } from '@/backend/staffing/login';
import { staffingApiErrorResponse } from '@/lib/api/staffing-api-response';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export function GET() { try { return beginLogin(); } catch (e) { return staffingApiErrorResponse(e); } }
