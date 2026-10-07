'use client';

import { type ReactNode, useEffect, useState } from 'react';

import { AskAiPod } from '@/components/chat/AskAiPod';
import { AddPersonModal } from '@/components/overlays/AddPersonModal';
import { RequestOverlays } from '@/components/overlays/RequestOverlays';
import { WorkspaceOverlays } from '@/components/overlays/WorkspaceOverlays';
import { ChangePasswordModal } from '@/components/overlays/ChangePasswordModal';
import { ToastHost } from '@/components/ui/ToastHost';
import { useStaffingApp } from '@/context/StaffingAppProvider';

import { NotificationDrawer } from './NotificationDrawer';
import { Sidebar } from './Sidebar';
import { Topbar } from './Topbar';
import { PersonaSessionGuard } from './PersonaSession';

export function AppShell({ children }: { children: ReactNode }) {
  const { state } = useStaffingApp();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  useEffect(() => {
    try { setSidebarCollapsed(window.localStorage.getItem('staffing-sidebar-collapsed') === '1'); }
    catch { /* The sidebar remains usable when storage is unavailable. */ }
  }, []);

  function toggleSidebar() {
    const next = !sidebarCollapsed;
    setSidebarCollapsed(next);
    try { window.localStorage.setItem('staffing-sidebar-collapsed', next ? '1' : '0'); }
    catch { /* Keep the current tab's choice. */ }
  }

  useEffect(() => {
    if (!mobileNavOpen) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') setMobileNavOpen(false);
    }
    document.addEventListener('keydown', closeOnEscape);
    return () => document.removeEventListener('keydown', closeOnEscape);
  }, [mobileNavOpen]);

  return (
    <div className={`staffing-shell${sidebarCollapsed ? ' sidebar-collapsed' : ''}`}>
      <PersonaSessionGuard />
      <Sidebar mobileOpen={mobileNavOpen} collapsed={sidebarCollapsed} onToggle={toggleSidebar} onNavigate={() => setMobileNavOpen(false)} />
      {mobileNavOpen && <button type="button" className="staffing-nav-backdrop" aria-label="Close navigation" onClick={() => setMobileNavOpen(false)} />}
      <main className="staffing-main">
        <Topbar onMenu={() => setMobileNavOpen((value) => !value)} />
        <div className="staffing-content">{children}</div>
      </main>
      <AskAiPod key={`ask-ai-${state.role}`} />
      <NotificationDrawer />
      <RequestOverlays />
      <AddPersonModal key={`add-person-${state.role}`} />
      <WorkspaceOverlays key={`workspace-overlays-${state.role}`} />
      <ChangePasswordModal />
      <ToastHost />
    </div>
  );
}
