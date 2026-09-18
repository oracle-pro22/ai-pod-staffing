import { NextResponse, type NextRequest } from 'next/server';
import { staffingBackend } from '@/backend/staffing/bridge';
import { staffingApiErrorResponse } from '@/lib/api/staffing-api-response';
import { StaffingApiError } from '@/lib/errors/staffing-api-error';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

async function forward(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  try {
    const { path } = await context.params;
    const joined = path.join('/');
    const id = '[A-Za-z0-9_-]{1,64}';
    const allowed = request.method === 'GET'
      ? new RegExp(`^(me|workspace|reports/export|requests|admin/utilization|requests/${id}/(execution|proposal|manual)|executions/${id}|proposals/${id})$`)
      : new RegExp(`^(requests/${id}/(executions|close|manual-preview|manual-decision)|proposals/${id}/selection|decisions|admin/utilization)$`);
    if (!allowed.test(joined)) throw new StaffingApiError('Staffing endpoint not found.', 404, 'NOT_FOUND');
    let body: unknown;
    if (request.method === 'POST') {
      const content = await request.text();
      if (content.length > 12000) throw new StaffingApiError('Request is too large.', 413, 'BODY_LIMIT');
      try { body = JSON.parse(content); } catch { throw new StaffingApiError('Invalid JSON.', 400, 'INVALID_JSON'); }
    }
    const after = request.nextUrl.searchParams.get('after');
    if (after !== null && !/^\d{1,10}$/.test(after)) throw new StaffingApiError('Invalid progress cursor.', 400, 'INVALID_CURSOR');
    let suffix = after !== null && joined.startsWith('executions/') ? `?after=${after}` : '';
    if (joined === 'workspace' || joined === 'reports/export') {
      const query = new URLSearchParams();
      const week = request.nextUrl.searchParams.get('week');
      const resource = request.nextUrl.searchParams.get('resource') || 'REQUESTS';
      if (week && !/^\d{4}-\d{2}-\d{2}$/.test(week)) throw new StaffingApiError('Invalid week.', 400, 'INVALID_DATE');
      if (!['REQUESTS', 'ALLOCATION_CALENDAR', 'REPORTS', 'TEAM_SKILLS', 'MY_AVAILABILITY'].includes(resource)) throw new StaffingApiError('Invalid resource.', 400, 'INVALID_RESOURCE');
      if (week) query.set('week', week);
      if (joined === 'workspace') query.set('resource', resource);
      suffix = `?${query}`;
    }
    const data = await staffingBackend(request, `/v1/${joined}${suffix}`, request.method, body);
    return NextResponse.json({ data }, { status: request.method === 'POST' && joined.endsWith('/executions') ? 202 : 200,
      headers: { 'Cache-Control': 'no-store' } });
  } catch (error) { return staffingApiErrorResponse(error); }
}

export const GET = forward;
export const POST = forward;
