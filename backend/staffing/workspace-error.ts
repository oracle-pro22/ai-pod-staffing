import 'server-only';
import { StaffingApiError } from '@/lib/errors/staffing-api-error';

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
