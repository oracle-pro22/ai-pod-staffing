import 'server-only';
import { createHmac, randomBytes, createHash, timingSafeEqual } from 'node:crypto';
import { NextRequest, NextResponse } from 'next/server';
import { agenticEnabled, staffingBackend } from './bridge';
import { StaffingApiError } from '@/lib/errors/staffing-api-error';

function config() {
  if (process.env.STAFFING_BACKEND_AUTH_MODE === 'password') throw new StaffingApiError('Organization sign-in is disabled in password mode.', 404, 'LOGIN_DISABLED');
  if (!agenticEnabled()) throw new StaffingApiError('Identity integration is not enabled.', 503, 'LOGIN_DISABLED');
  const secret = process.env.STAFFING_LOGIN_STATE_SECRET || '';
  const clientId = process.env.STAFFING_OIDC_CLIENT_ID || '';
  const origin = new URL(process.env.STAFFING_APP_ORIGIN || 'https://invalid');
  const authorization = new URL(process.env.STAFFING_OIDC_AUTHORIZATION_URL || 'https://invalid');
  const token = new URL(process.env.STAFFING_OIDC_TOKEN_URL || 'https://invalid');
  if (secret.length < 32 || !clientId || [origin, authorization, token].some(u => u.hostname === 'invalid' || u.username || u.password || u.hash || u.search)
      || origin.pathname !== '/' || authorization.protocol !== 'https:' || token.protocol !== 'https:'
      || (origin.protocol !== 'https:' && !(process.env.NODE_ENV === 'development' && origin.protocol === 'http:' && ['localhost','127.0.0.1'].includes(origin.hostname)))) {
    throw new StaffingApiError('Organization sign-in needs configuration.', 503, 'LOGIN_CONFIGURATION');
  }
  return { secret, clientId, origin: origin.origin, authorization, token, secure: origin.protocol === 'https:' };
}

function sign(value: string, secret: string) { return createHmac('sha256', secret).update(value).digest('base64url'); }

export function beginLogin() {
  const c = config();
  const state = randomBytes(32).toString('base64url'), verifier = randomBytes(48).toString('base64url');
  const payload = Buffer.from(JSON.stringify({ state, verifier, expires: Date.now() + 300000 })).toString('base64url');
  const url = c.authorization;
  for (const [key, value] of Object.entries({ client_id: c.clientId, response_type: 'code', redirect_uri: `${c.origin}/api/auth/callback`,
    scope: process.env.STAFFING_OIDC_SCOPE || 'openid', state, code_challenge: createHash('sha256').update(verifier).digest('base64url'), code_challenge_method: 'S256' })) url.searchParams.set(key, value);
  const response = NextResponse.redirect(url);
  response.cookies.set('staffing_login_state', `${payload}.${sign(payload, c.secret)}`, { httpOnly: true, secure: c.secure, sameSite: 'lax', maxAge: 300, path: '/api/auth' });
  response.headers.set('Cache-Control', 'no-store');
  return response;
}

export async function completeLogin(request: NextRequest) {
  const c = config();
  const [payload = '', signature = ''] = (request.cookies.get('staffing_login_state')?.value || '').split('.');
  const expected = sign(payload, c.secret);
  if (signature.length !== expected.length || !timingSafeEqual(Buffer.from(signature), Buffer.from(expected))) throw new StaffingApiError('Sign-in expired. Start again.', 401, 'LOGIN_STATE');
  const saved = JSON.parse(Buffer.from(payload, 'base64url').toString('utf8'));
  const code = request.nextUrl.searchParams.get('code');
  if (!code || code.length > 8192 || saved.expires < Date.now() || request.nextUrl.searchParams.get('state') !== saved.state) throw new StaffingApiError('Sign-in expired. Start again.', 401, 'LOGIN_STATE');
  const params = new URLSearchParams({ grant_type: 'authorization_code', code, client_id: c.clientId, code_verifier: saved.verifier, redirect_uri: `${c.origin}/api/auth/callback` });
  const headers: Record<string, string> = { 'Content-Type': 'application/x-www-form-urlencoded' };
  const secret = process.env.STAFFING_OIDC_CLIENT_SECRET;
  if (secret) headers.Authorization = `Basic ${Buffer.from(`${encodeURIComponent(c.clientId)}:${encodeURIComponent(secret)}`).toString('base64')}`;
  const exchanged = await fetch(c.token, { method: 'POST', headers, body: params, cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(15000) });
  const tokens = await exchanged.json().catch(() => null);
  if (!exchanged.ok || typeof tokens?.access_token !== 'string' || tokens.access_token.length > 3800 || tokens.token_type?.toLowerCase() !== 'bearer') throw new StaffingApiError('Organization sign-in failed. Check access-token format and cookie size.', 401, 'LOGIN_FAILED');
  // Access-token signature/issuer/audience/expiry AND employee mapping are independently verified by Python.
  await staffingBackend(new NextRequest(c.origin, { headers: { Authorization: `Bearer ${tokens.access_token}` } }), '/v1/me');
  const response = NextResponse.redirect(new URL('/', c.origin));
  const expires = Number(tokens.expires_in);
  response.cookies.set('staffing_access_token', tokens.access_token, { httpOnly: true, secure: c.secure, sameSite: 'lax', path: '/', maxAge: Number.isFinite(expires) && expires > 0 ? Math.min(expires, 3600) : 300 });
  response.cookies.set('staffing_login_state', '', { httpOnly: true, secure: c.secure, sameSite: 'lax', maxAge: 0, path: '/api/auth' });
  response.headers.set('Cache-Control', 'no-store');
  response.headers.set('Referrer-Policy', 'no-referrer');
  return response;
}

export function logout(request: NextRequest) {
  const c = config();
  if (request.headers.get('origin') !== c.origin || request.headers.get('sec-fetch-site') === 'cross-site') throw new StaffingApiError('Invalid sign-out origin.', 403, 'ORIGIN_REJECTED');
  const response = NextResponse.redirect(new URL('/', c.origin), 303);
  response.cookies.set('staffing_access_token', '', { httpOnly: true, secure: c.secure, sameSite: 'lax', path: '/', maxAge: 0 });
  response.headers.set('Cache-Control', 'no-store');
  return response;
}
