/** Bind browser operations to the workspace that actually rendered this tab. */
export async function staffingFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const session = typeof document === 'undefined' ? null
    : document.querySelector<HTMLMetaElement>('meta[name="staffing-persona-session"]')?.content;
  let requestInit = init;
  if (session && typeof window !== 'undefined') {
    const target = new URL(input, window.location.origin);
    if (target.origin === window.location.origin && target.pathname.startsWith('/api/')) {
      headers.set('x-staffing-persona-session', session);
      requestInit = { ...init, headers };
    }
  }
  const response = await fetch(input, requestInit);
  if (session && [401, 403, 409].includes(response.status)) {
    const error = await response.clone().json().catch(() => null);
    const code = error?.code ?? error?.error?.code;
    if (['SIGN_IN_REQUIRED', 'PERSONA_CHANGED', 'PERSONA_REQUIRED', 'UNAUTHENTICATED', 'IDENTITY_NOT_LINKED', 'PERSONA_MAPPING_CHANGED', 'PERSONA_NOT_AVAILABLE'].includes(code)) {
      window.location.assign('/');
    }
  }
  return response;
}

export function announcePersonaChange() {
  if (typeof BroadcastChannel === 'undefined') return;
  try {
    const channel = new BroadcastChannel('staffing-persona');
    channel.postMessage('changed');
    channel.close();
  } catch {
    // Focus checks and request binding still protect browsers without channels.
  }
}
