'use client';

import { type ReactNode, useEffect, useState } from 'react';

import { AskAiPod } from '@/components/chat/AskAiPod';
import { RequestOverlays } from '@/components/overlays/RequestOverlays';
import { WorkspaceOverlays } from '@/components/overlays/WorkspaceOverlays';
import { ToastHost } from '@/components/ui/ToastHost';
import { useStaffingApp } from '@/context/StaffingAppProvider';

import { NotificationDrawer } from './NotificationDrawer';
import { Sidebar } from './Sidebar';
import { Topbar } from './Topbar';

export function AppShell({ children }: { children: ReactNode }) {
  const { state } = useStaffingApp();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  useEffect(() => {
    if (!mobileNavOpen) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') setMobileNavOpen(false);
    }
    document.addEventListener('keydown', closeOnEscape);
    return () => document.removeEventListener('keydown', closeOnEscape);
  }, [mobileNavOpen]);

  return (
    <div className="staffing-shell">
      <Sidebar mobileOpen={mobileNavOpen} onNavigate={() => setMobileNavOpen(false)} />
      {mobileNavOpen && <button type="button" className="staffing-nav-backdrop" aria-label="Close navigation" onClick={() => setMobileNavOpen(false)} />}
      <main className="staffing-main">
        <Topbar onMenu={() => setMobileNavOpen((value) => !value)} />
        <div className="staffing-content">{children}</div>
      </main>
      <AskAiPod key={state.role} />
      <NotificationDrawer />
      <RequestOverlays />
      <WorkspaceOverlays />
      <ToastHost />
    </div>
  );
}
