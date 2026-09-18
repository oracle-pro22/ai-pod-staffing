import 'server-only';
import type { NextRequest } from 'next/server';
import { StaffingApiError } from '@/lib/errors/staffing-api-error';
import { browserRequestOrigin, requireSameOrigin } from './request-origin';

export const PASSWORD_COOKIE = 'staffing_password_session';

export function passwordModeEnabled() {
  const enabled = process.env.STAFFING_BACKEND_AUTH_MODE === 'password';
  if (enabled && (process.env.STAFFING_AGENTIC_ENABLED !== 'true'
      || process.env.NEXT_PUBLIC_STAFFING_AGENTIC_ENABLED !== 'true')) {
    throw new StaffingApiError('Password sign-in requires staffing integration.', 503, 'LOGIN_CONFIGURATION');
  }
  return enabled;
}

export function requirePasswordOrigin(request: NextRequest, mutation = false) {
  if (!passwordModeEnabled()) throw new StaffingApiError('Password sign-in is not enabled.', 404, 'PASSWORD_LOGIN_DISABLED');
  let configured: URL;
  try { configured = new URL(process.env.STAFFING_APP_ORIGIN || ''); }
  catch { throw new StaffingApiError('Set STAFFING_APP_ORIGIN to the application address.', 503, 'LOGIN_CONFIGURATION'); }
  if (!['http:', 'https:'].includes(configured.protocol) || configured.username || configured.password
      || configured.pathname !== '/' || configured.search || configured.hash) {
    throw new StaffingApiError('Invalid application origin.', 503, 'LOGIN_CONFIGURATION');
  }
  if (browserRequestOrigin(request).origin !== configured.origin) {
    throw new StaffingApiError('Open the configured application address.', 403, 'ORIGIN_REJECTED');
  }
  requireSameOrigin(request, mutation);
  return configured;
}
