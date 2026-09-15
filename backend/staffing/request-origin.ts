import 'server-only';
import type { NextRequest } from 'next/server';
import { StaffingApiError } from '@/lib/errors/staffing-api-error';

export const LOOPBACK_HOSTS = ['127.0.0.1', 'localhost', '[::1]'];

export function browserRequestOrigin(request: NextRequest): URL {
  // NextURL normalizes loopback IPs to localhost; preserve the actual HTTP Host.
  const origin = new URL(request.nextUrl.origin);
  const host = request.headers.get('host');
  if (!host) return origin;
  if (!/^(?:\[[0-9a-f:]+\]|[a-z0-9.-]+)(?::[0-9]{1,5})?$/i.test(host)) {
    throw new StaffingApiError('Invalid request host.', 403, 'ORIGIN_REJECTED');
  }
  return new URL(`${origin.protocol}//${host}`);
}

export function requireSameOrigin(request: NextRequest, strict = false) {
  const origin = request.headers.get('origin');
  if ((strict || origin) && origin !== browserRequestOrigin(request).origin
      || request.headers.get('sec-fetch-site') === 'cross-site') {
    throw new StaffingApiError('Cross-origin operation rejected.', 403, 'ORIGIN_REJECTED');
  }
}
