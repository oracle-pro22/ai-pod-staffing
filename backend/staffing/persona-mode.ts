import 'server-only';
import { createHash } from 'node:crypto';
import type { NextRequest } from 'next/server';
import { StaffingApiError } from '@/lib/errors/staffing-api-error';
import { browserRequestOrigin, LOOPBACK_HOSTS, requireSameOrigin } from './request-origin';

export const PERSONA_COOKIE = 'staffing_persona_session';
export const PERSONA_PAGE_HEADER = 'x-staffing-persona-session';

export function personaModeEnabled(): boolean {
  if (process.env.STAFFING_DEMO_PERSONAS_ENABLED !== 'true') return false;
  if (process.env.NODE_ENV !== 'development' || process.env.STAFFING_BACKEND_AUTH_MODE !== 'local'
      || process.env.STAFFING_AGENTIC_ENABLED !== 'true' || process.env.NEXT_PUBLIC_STAFFING_AGENTIC_ENABLED !== 'true') {
    throw new StaffingApiError('Profile selection requires local development with staffing integration enabled.', 503, 'PERSONA_CONFIGURATION');
  }
  return true;
}

export function requirePersonaMode(request: NextRequest) {
  if (!personaModeEnabled()) throw new StaffingApiError('Profile selection is not enabled.', 404, 'PERSONAS_DISABLED');
  if (!LOOPBACK_HOSTS.includes(browserRequestOrigin(request).hostname)) {
    throw new StaffingApiError('Local profiles are available only on this computer.', 403, 'LOCAL_AUTH_RESTRICTED');
  }
  requireSameOrigin(request, !['GET', 'HEAD'].includes(request.method));
}

// Non-secret page binding, not an authorization token. Old tabs cannot submit
// under a newly selected browser identity without loading that workspace first.
export function personaSessionKey(token: string) {
  return createHash('sha256').update(token).digest('hex').slice(0, 32);
}
