import 'server-only';
import { StaffingApiError } from '@/lib/errors/staffing-api-error';
import { configuredPasswordOrigin } from './password-mode';

/** Explain password-entry failures without exposing raw backend errors or credentials. */
export function passwordWorkspaceError(error: unknown): { message: string; applicationUrl?: string } {
  if (error instanceof StaffingApiError) {
    if (error.code === 'ORIGIN_REJECTED') {
      try {
        return {
          message: 'This address does not match the configured application address. Open the application using the link below to sign in.',
          applicationUrl: configuredPasswordOrigin().origin,
        };
      } catch {
        return { message: 'The application sign-in address is not configured correctly. Contact your administrator.' };
      }
    }
    if (error.status === 401) return { message: 'Your session has expired or is no longer valid. Sign in again.' };
    if (error.status === 403) return { message: 'Your account does not have access to this workspace. Contact your administrator.' };
    if (['LOGIN_CONFIGURATION', 'BACKEND_CONFIGURATION', 'AGENTIC_CONFIGURATION'].includes(error.code)) {
      return { message: 'The application sign-in connection is not configured correctly. Contact your administrator.' };
    }
    if (error.code === 'BACKEND_UNAVAILABLE') {
      return { message: 'The staffing service could not be reached. Please try again shortly.' };
    }
  }
  return { message: 'Your workspace could not be loaded. Please retry or contact your administrator.' };
}

export function workspaceError(error: unknown, local: boolean) {
  const known = error instanceof StaffingApiError;
  const showSignIn = !local && known && error.status === 401;
  const code = known && /^[A-Z][A-Z0-9_]{0,79}$/.test(error.code) ? error.code : 'WORKSPACE_UNAVAILABLE';
  return {
    code,
    showSignIn,
    message: showSignIn ? 'Sign in to continue.' : local
      ? 'Unable to load the local workspace. No organization sign-in is needed. Check the Python backend and database configuration.'
      : 'Unable to load the workspace. Check your access, backend connection, and database configuration.',
  };
}
