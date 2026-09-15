import { WorkspaceRouter } from '@/components/screens/WorkspaceRouter';
import { AppShell } from '@/components/shell/AppShell';
import { StaffingAppProvider } from '@/context/StaffingAppProvider';
import { dataSource } from '@/lib/staffing-data-source';
import { agenticEnabled } from '@/backend/staffing/bridge';
import { authenticatedViewModel } from '@/backend/staffing/view-model';
import { headers } from 'next/headers';
import { NextRequest } from 'next/server';
import { workspaceError } from '@/backend/staffing/workspace-error';
import { PersonaEntry } from '@/components/entry/PersonaEntry';
import { PERSONA_COOKIE, PERSONA_PAGE_HEADER, personaModeEnabled, personaSessionKey, requirePersonaMode } from '@/backend/staffing/persona-mode';

export const dynamic = 'force-dynamic';

export default async function Home() {
  let data;
  if (agenticEnabled()) {
    const incoming = await headers();
    // Only the actual Host is used; do not trust arbitrary forwarded-host headers for local-token access.
    const origin = process.env.STAFFING_APP_ORIGIN || `http://${incoming.get('host') || 'invalid'}`;
    try {
      const request = new NextRequest(origin, { headers: incoming });
      if (personaModeEnabled()) {
        requirePersonaMode(request);
        const selected = request.cookies.get(PERSONA_COOKIE)?.value;
        if (!selected) return <PersonaEntry />;
        request.headers.set(PERSONA_PAGE_HEADER, personaSessionKey(selected));
      }
      data = await authenticatedViewModel(request);
    }
    catch (error) {
      if (process.env.STAFFING_DEMO_PERSONAS_ENABLED === 'true') {
        return <PersonaEntry initialError="Your workspace could not be loaded. Choose your profile again, or retry once the backend is available." />;
      }
      const failure = workspaceError(error, process.env.STAFFING_BACKEND_AUTH_MODE === 'local');
      return <main style={{ padding: 40 }}><h1>AI Pod Staffing</h1>
        <p role="alert">{failure.message}</p><p>Error code: <code>{failure.code}</code></p>
        {failure.showSignIn ? <a href="/api/auth/login">Sign in</a> : <a href="/">Try again</a>}
      </main>;
    }
  } else data = await dataSource.getViewModel();
  return (
    <StaffingAppProvider key={data.identity ? `${data.identity.personId}:${data.identity.role}:${data.identity.sessionKey ?? ''}` : 'preview'} data={data}>
      {data.identity?.sessionKey && <meta name="staffing-persona-session" content={data.identity.sessionKey} />}
      <AppShell>
        <WorkspaceRouter />
      </AppShell>
    </StaffingAppProvider>
  );
}
