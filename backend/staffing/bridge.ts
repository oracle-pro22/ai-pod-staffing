import 'server-only';

import type { NextRequest } from 'next/server';
import { StaffingApiError } from '@/lib/errors/staffing-api-error';
import { browserRequestOrigin, LOOPBACK_HOSTS, requireSameOrigin } from './request-origin';
import { PERSONA_COOKIE, PERSONA_PAGE_HEADER, personaModeEnabled, personaSessionKey, requirePersonaMode } from './persona-mode';

export function agenticEnabled(): boolean {
  const enabled = process.env.STAFFING_AGENTIC_ENABLED === 'true';
  if (enabled !== (process.env.NEXT_PUBLIC_STAFFING_AGENTIC_ENABLED === 'true')) {
    throw new StaffingApiError('Staffing frontend and backend feature flags must match.', 503, 'AGENTIC_CONFIGURATION');
  }
  return enabled;
}

export type BackendIdentity = {
  person_id: string;
  full_name?: string;
  identity_subject: string;
  roles: string[];
  permissions: { role: string; resource: string; scope: string; actions: string[] }[];
};

export async function staffingBackend(request: NextRequest, path: string, method = 'GET', body?: unknown,
  options: { personaManagement?: boolean } = {}): Promise<unknown> {
  if (!agenticEnabled()) throw new StaffingApiError('Staffing integration is not enabled.', 503, 'AGENTIC_DISABLED');
  const browserOrigin = browserRequestOrigin(request);
  const endpoint = new URL(process.env.STAFFING_BACKEND_URL || 'http://127.0.0.1:8015');
  const loopback = LOOPBACK_HOSTS.includes(endpoint.hostname);
  if (endpoint.username || endpoint.password || endpoint.search || endpoint.hash || endpoint.pathname !== '/'
      || (endpoint.protocol !== 'https:' && !(loopback && endpoint.protocol === 'http:'))) {
    throw new StaffingApiError('Invalid staffing backend configuration.', 503, 'BACKEND_CONFIGURATION');
  }
  const personas = personaModeEnabled();
  let authorization: string | null = null;
  if (personas || options.personaManagement) {
    requirePersonaMode(request);
    if (!loopback) throw new StaffingApiError('Profile selection requires the local backend.', 503, 'LOCAL_AUTH_RESTRICTED');
    if (options.personaManagement) {
      if (!((path === '/v1/local-personas' && method === 'GET')
          || (path === '/v1/local-personas/session' && method === 'POST'))) {
        throw new StaffingApiError('Unsupported profile operation.', 403, 'FORBIDDEN');
      }
      const control = process.env.STAFFING_BACKEND_LOCAL_TOKEN;
      if (!control || control.length < 32) throw new StaffingApiError('Local backend connection needs configuration.', 503, 'BACKEND_CONFIGURATION');
      authorization = `Bearer ${control}`;
    } else {
      const selected = request.cookies.get(PERSONA_COOKIE)?.value;
      if (!selected) throw new StaffingApiError('Choose a profile to enter the workspace.', 401, 'PERSONA_REQUIRED');
      if (request.headers.get(PERSONA_PAGE_HEADER) !== personaSessionKey(selected)) {
        throw new StaffingApiError('Your profile changed. Reload the workspace before continuing.', 409, 'PERSONA_CHANGED');
      }
      authorization = `Bearer ${selected}`;
    }
  } else {
    // Enterprise cookie is verified independently by Python. Browser role headers grant nothing.
    authorization = request.headers.get('authorization');
  }
  if (!personas && !authorization) {
    const token = request.cookies.get('staffing_access_token')?.value;
    if (token) authorization = `Bearer ${token}`;
  }
  if (!authorization && process.env.STAFFING_BACKEND_AUTH_MODE === 'local') {
    // Explicit development-only fixed identity. Never derives a subject from the preview role selector.
    if (process.env.NODE_ENV !== 'development' || !loopback
        || !LOOPBACK_HOSTS.includes(browserOrigin.hostname)) {
      throw new StaffingApiError('Local backend credentials are restricted to loopback development.', 503, 'LOCAL_AUTH_RESTRICTED');
    }
    const token = process.env.STAFFING_BACKEND_LOCAL_TOKEN;
    if (token && token.length >= 32) authorization = `Bearer ${token}`;
  }
  if (!authorization) throw new StaffingApiError('Sign in with your staffing identity.', 401, 'SIGN_IN_REQUIRED');
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    requireSameOrigin(request);
  }
  let response: Response;
  try {
    response = await fetch(new URL(path, endpoint), { method, cache: 'no-store', redirect: 'error',
      headers: { Authorization: authorization, 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(30000) });
  } catch {
    throw new StaffingApiError('Staffing backend could not be reached. Check the operation status before retrying a save.', 503, 'BACKEND_UNAVAILABLE');
  }
  const payload = await response.json().catch(() => null);
  if (!response.ok) throw new StaffingApiError(payload?.error?.message || 'The staffing operation could not be completed.', response.status, payload?.error?.code || 'BACKEND_ERROR');
  return payload;
}

export async function verifiedCaptain(request: NextRequest): Promise<BackendIdentity> {
  const identity = await staffingBackend(request, '/v1/me') as BackendIdentity;
  if (!identity.roles.includes('POD_CAPTAIN') || !identity.permissions.some(p => p.role === 'POD_CAPTAIN'
      && p.resource === 'REQUESTS' && p.scope !== 'LOCKED' && p.actions.includes('view') && p.actions.includes('create'))) {
    throw new StaffingApiError('A signed-in POD Captain with request permission is required.', 403, 'FORBIDDEN');
  }
  return identity;
}
