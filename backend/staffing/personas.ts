import 'server-only';
import { NextRequest, NextResponse } from 'next/server';
import { ROLE_CODES, STAFFING_ROLES } from '@/types/roles';
import { StaffingApiError } from '@/lib/errors/staffing-api-error';
import { staffingBackend, type BackendIdentity } from './bridge';
import { PERSONA_COOKIE, PERSONA_PAGE_HEADER, personaSessionKey, requirePersonaMode } from './persona-mode';
import { browserRequestOrigin } from './request-origin';

const names = Object.fromEntries(STAFFING_ROLES.map(role => [ROLE_CODES[role], role]));
const validId = (value: unknown): value is string => typeof value === 'string' && /^[A-Za-z0-9_-]{1,30}$/.test(value);

export async function listPersonas(request: NextRequest) {
  requirePersonaMode(request);
  const payload = await staffingBackend(request, '/v1/local-personas', 'GET', undefined, { personaManagement: true }) as {
    personas?: { person_id: string; full_name: string; role_code: string; role_name: string }[];
  };
  if (!Array.isArray(payload?.personas) || payload.personas.length > 200
      || payload.personas.some(p => !p || typeof p !== 'object' || !validId(p.person_id) || !Object.hasOwn(names, p.role_code)
        || p.role_name !== names[p.role_code] || typeof p.full_name !== 'string' || !p.full_name.trim() || p.full_name.length > 255)) {
    throw new StaffingApiError('The available profiles could not be loaded. Check the employee role mappings.', 503, 'PERSONA_DIRECTORY_INVALID');
  }
  // Deliberately return names/IDs/profiles only; no subject, token, email, skills or location.
  return NextResponse.json({ personas: payload.personas.map(p => ({
    person_id: p.person_id, full_name: p.full_name, role_code: p.role_code, role_name: p.role_name,
  })) }, { headers: { 'Cache-Control': 'no-store' } });
}

export async function enterPersona(request: NextRequest) {
  requirePersonaMode(request);
  const body = await request.json().catch(() => null);
  if (!body || Array.isArray(body) || Object.keys(body).sort().join(',') !== 'person_id,role_code'
      || !validId(body.person_id) || typeof body.role_code !== 'string' || !Object.hasOwn(names, body.role_code)) {
    throw new StaffingApiError('Choose a profile and a person from its list.', 400, 'INVALID_PERSONA');
  }
  const session = await staffingBackend(request, '/v1/local-personas/session', 'POST', body, { personaManagement: true }) as {
    access_token?: string; expires_in?: number; person_id?: string; role_code?: string;
  };
  if (typeof session.access_token !== 'string' || !session.access_token.startsWith('dps1.') || session.access_token.length > 3800
      || !Number.isInteger(session.expires_in) || session.expires_in! <= 0 || session.expires_in! > 28800
      || session.person_id !== body.person_id || session.role_code !== body.role_code) {
    throw new StaffingApiError('The selected profile session could not be created.', 503, 'PERSONA_SESSION_INVALID');
  }
  const origin = browserRequestOrigin(request);
  const verifyHeaders = new Headers({ host: origin.host, cookie: `${PERSONA_COOKIE}=${session.access_token}`,
    [PERSONA_PAGE_HEADER]: personaSessionKey(session.access_token) });
  const identity = await staffingBackend(new NextRequest(origin, { headers: verifyHeaders }), '/v1/me') as BackendIdentity;
  if (identity.person_id !== body.person_id || identity.roles.length !== 1 || identity.roles[0] !== body.role_code) {
    throw new StaffingApiError('The selected employee profile has changed. Choose again.', 409, 'PERSONA_MAPPING_CHANGED');
  }
  const response = NextResponse.json({ ok: true }, { headers: { 'Cache-Control': 'no-store' } });
  response.cookies.set(PERSONA_COOKIE, session.access_token, { httpOnly: true, secure: origin.protocol === 'https:',
    sameSite: 'strict', path: '/', maxAge: session.expires_in });
  return response;
}

export function leavePersona(request: NextRequest) {
  requirePersonaMode(request);
  const response = NextResponse.json({ ok: true }, { headers: { 'Cache-Control': 'no-store' } });
  response.cookies.set(PERSONA_COOKIE, '', { httpOnly: true, secure: browserRequestOrigin(request).protocol === 'https:',
    sameSite: 'strict', path: '/', maxAge: 0 });
  return response;
}
