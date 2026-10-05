import 'server-only';
import { NextRequest, NextResponse } from 'next/server';
import { staffingBackend } from './bridge';
import { PASSWORD_COOKIE, requirePasswordOrigin } from './password-mode';
import { PERSONA_COOKIE, PERSONA_PAGE_HEADER, personaSessionKey } from './persona-mode';
import { StaffingApiError } from '@/lib/errors/staffing-api-error';

export async function passwordLogin(request: NextRequest) {
  const origin = requirePasswordOrigin(request, true);
  const raw = await request.text();
  if (raw.length > 8192) throw new StaffingApiError('Invalid sign-in request.', 400, 'INVALID_REQUEST');
  let body;
  try { body = JSON.parse(raw); } catch { throw new StaffingApiError('Invalid sign-in request.', 400, 'INVALID_REQUEST'); }
  if (!body || Array.isArray(body) || Object.keys(body).sort().join(',') !== 'email,password'
      || typeof body.email !== 'string' || typeof body.password !== 'string' || body.password.length > 1024 || body.email.length > 320) {
    throw new StaffingApiError('Enter your email and password.', 400, 'INVALID_REQUEST');
  }
  const session = await staffingBackend(request, '/v1/auth/password/login', 'POST', body, { passwordLogin: true }) as {
    access_token: string; expires_in: number;
  };
  if (!/^aps1\.[A-Za-z0-9_-]{43}$/.test(session?.access_token) || !Number.isInteger(session.expires_in)
      || session.expires_in <= 0 || session.expires_in > 86400) throw new StaffingApiError('Unable to start your session.', 503, 'LOGIN_FAILED');
  const response = NextResponse.json({ ok: true }, { headers: { 'Cache-Control': 'no-store' } });
  response.cookies.set(PASSWORD_COOKIE, session.access_token, { httpOnly: true, secure: origin.protocol === 'https:', sameSite: 'strict', path: '/', maxAge: session.expires_in });
  for (const name of [PERSONA_COOKIE, 'staffing_access_token']) response.cookies.set(name, '', { httpOnly: true, secure: origin.protocol === 'https:', sameSite: 'strict', path: '/', maxAge: 0 });
  return response;
}

export async function passwordLogout(request: NextRequest) {
  const origin = requirePasswordOrigin(request, true);
  // Require the tab binding, including logout: an old tab must not revoke a new user's session.
  const token = request.cookies.get(PASSWORD_COOKIE)?.value;
  if (token) {
    if (request.headers.get(PERSONA_PAGE_HEADER) !== personaSessionKey(token)) throw new StaffingApiError('Your account changed. Reload the workspace.', 409, 'PERSONA_CHANGED');
    await staffingBackend(request, '/v1/auth/password/logout', 'POST');
  }
  const response = NextResponse.json({ ok: true }, { headers: { 'Cache-Control': 'no-store' } });
  response.cookies.set(PASSWORD_COOKIE, '', { httpOnly: true, secure: origin.protocol === 'https:', sameSite: 'strict', path: '/', maxAge: 0 });
  return response;
}

export async function passwordChange(request: NextRequest) {
  const origin = requirePasswordOrigin(request, true);
  const raw = await request.text();
  if (raw.length > 4096) throw new StaffingApiError('Invalid password change request.', 400, 'INVALID_REQUEST');
  let body: unknown;
  try { body = JSON.parse(raw); } catch { throw new StaffingApiError('Invalid password change request.', 400, 'INVALID_REQUEST'); }
  if (!body || Array.isArray(body) || typeof body !== 'object'
      || Object.keys(body).sort().join(',') !== 'confirmPassword,currentPassword,newPassword') {
    throw new StaffingApiError('Complete all password fields.', 400, 'INVALID_REQUEST');
  }
  const values = body as Record<string, unknown>;
  if (typeof values.currentPassword !== 'string' || typeof values.newPassword !== 'string'
      || typeof values.confirmPassword !== 'string' || values.currentPassword.length < 1
      || values.currentPassword.length > 1024 || values.newPassword.length < 1 || values.newPassword.length > 128) {
    throw new StaffingApiError('Complete all password fields.', 400, 'INVALID_REQUEST');
  }
  if (values.newPassword !== values.confirmPassword) {
    throw new StaffingApiError('The new passwords do not match.', 400, 'PASSWORD_MISMATCH');
  }
  const result = await staffingBackend(request, '/v1/auth/password/change', 'POST', {
    current_password: values.currentPassword,
    new_password: values.newPassword,
  }) as { ok?: unknown; sessions_revoked?: unknown };
  if (result?.ok !== true || result.sessions_revoked !== true) {
    throw new StaffingApiError('Password change could not be confirmed.', 503, 'PASSWORD_CHANGE_UNCONFIRMED');
  }
  const response = NextResponse.json({ ok: true, sessionsRevoked: true }, { headers: { 'Cache-Control': 'no-store' } });
  response.cookies.set(PASSWORD_COOKIE, '', { httpOnly: true, secure: origin.protocol === 'https:', sameSite: 'strict', path: '/', maxAge: 0 });
  return response;
}
