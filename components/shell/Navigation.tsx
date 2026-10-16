'use client';

import { Icon } from '@/components/ui/Icon';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { canAccessScreen, NAVIGATION_ITEMS } from '@/lib/role-policy';

export function Navigation({ onNavigate, collapsed = false }: { onNavigate?: () => void; collapsed?: boolean }) {
  const { data, state, dispatch } = useStaffingApp();

  return (
    <nav className="staffing-nav" aria-label="Workspace navigation">
      {NAVIGATION_ITEMS.filter((item) => canAccessScreen(state.role, item.id, data.authorization)).map((item) => {
        const active = state.activeScreen === item.id;
        return (
          <button
            type="button"
            key={item.id}
            className={active ? 'active' : ''}
            aria-label={item.label}
            aria-current={active ? 'page' : undefined}
            title={collapsed ? item.label : undefined}
            onClick={() => {
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
