'use client';

import { Icon } from '@/components/ui/Icon';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { canAccessScreen, NAVIGATION_ITEMS } from '@/lib/role-policy';

export function Navigation({ onNavigate }: { onNavigate?: () => void }) {
  const { data, state, dispatch, notify } = useStaffingApp();

  return (
    <nav className="staffing-nav" aria-label="Workspace navigation">
      {NAVIGATION_ITEMS.map((item) => {
        const accessible = canAccessScreen(state.role, item.id, data.authorization);
        const active = state.activeScreen === item.id;
        return (
          <button
            type="button"
            key={item.id}
            className={`${active ? 'active' : ''}${accessible ? '' : ' locked'}`}
            aria-current={active ? 'page' : undefined}
            aria-disabled={!accessible}
            onClick={() => {
              if (!accessible) {
                notify('Access restricted', `${item.label} is not available to ${state.role}s.`);
                return;
              }
              dispatch({ type: 'set-screen', screen: item.id });
              onNavigate?.();
            }}
          >
            <Icon name={item.icon} />
            <span>{item.label}</span>
          </button>
        );
      })}
    </nav>
  );
}
