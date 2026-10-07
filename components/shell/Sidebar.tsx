'use client';

import { Avatar } from '@/components/ui/Avatar';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { selectIdentityPerson } from '@/lib/selectors';

import { Brand } from './Brand';
import { Navigation } from './Navigation';

export function Sidebar({ mobileOpen, collapsed, onToggle, onNavigate }: { mobileOpen: boolean; collapsed: boolean; onToggle: () => void; onNavigate: () => void }) {
  const { data, state } = useStaffingApp();
  const scopedIdentity = selectIdentityPerson(data, state.role);
  const displayName = data.identity?.fullName ?? scopedIdentity?.name ?? (data.identity ? state.role : `${state.role} preview`);
  const initials = scopedIdentity?.initials ?? (state.role === 'Administrator' ? 'AD' : displayName.split(' ').map(p => p[0]).join('').slice(0, 2));

  return (
    <aside id="staffing-sidebar" className={`staffing-sidebar${mobileOpen ? ' open' : ''}`}>
      <Brand />
      <div className="staffing-nav-heading">
        <div className="staffing-nav-title">Workspace</div>
        <button type="button" className="staffing-sidebar-toggle" aria-controls="staffing-sidebar"
          aria-expanded={!collapsed} aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} onClick={onToggle}>
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <rect x="3" y="3" width="18" height="18" rx="2" />
            <path d="M9 3v18" />
            <path d={collapsed ? 'm14 9 3 3-3 3' : 'm17 9-3 3 3 3'} />
          </svg>
        </button>
      </div>
      <Navigation collapsed={collapsed} onNavigate={onNavigate} />
      <div className="staffing-side-footer">
        <div className="staffing-mini-user" title={`${displayName} · ${state.role}`}>
          <Avatar initials={initials} />
          <div>
            <strong>{displayName}</strong>
            <span>{state.role}</span>
          </div>
        </div>
      </div>
    </aside>
  );
}
