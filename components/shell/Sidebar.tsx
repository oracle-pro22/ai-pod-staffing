'use client';

import { Avatar } from '@/components/ui/Avatar';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { selectIdentityPerson } from '@/lib/selectors';

import { Brand } from './Brand';
import { Navigation } from './Navigation';

export function Sidebar({ mobileOpen, onNavigate }: { mobileOpen: boolean; onNavigate: () => void }) {
  const { data, state } = useStaffingApp();
  const scopedIdentity = selectIdentityPerson(data, state.role);
  const isScoped = state.role === 'Pod Lead' || state.role === 'POD Member';
  const displayName = isScoped ? scopedIdentity?.name ?? 'Team member' : 'Indranie B.';
  const initials = isScoped ? scopedIdentity?.initials ?? 'TM' : 'IB';

  return (
    <aside className={`staffing-sidebar${mobileOpen ? ' open' : ''}`}>
      <Brand />
      <div className="staffing-nav-title">Workspace</div>
      <Navigation onNavigate={onNavigate} />
      <div className="staffing-side-footer">
        <div className="staffing-mini-user">
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
