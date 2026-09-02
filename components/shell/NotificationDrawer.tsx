'use client';

import { Button } from '@/components/ui/Button';
import { Drawer } from '@/components/ui/Drawer';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { selectScopedRecommendations, selectVisiblePeople, selectVisibleRequests } from '@/lib/selectors';

export function NotificationDrawer() {
  const { data, state, dispatch } = useStaffingApp();
  const open = state.drawer?.id === 'notifications';
  const requests = selectVisibleRequests(data, state.role);
  const pending = requests.flatMap((request) => selectScopedRecommendations(request, data, state.role))
    .filter((item) => /pending/i.test(item.decisionStatus));
  const constrained = selectVisiblePeople(data, state.role)
    .filter((person) => person.allocationPct >= 70);
  const close = () => dispatch({ type: 'close-drawer' });

  return (
    <Drawer open={open} title="Notifications" onClose={close} footer={<Button onClick={close}>Close</Button>}>
      <div className="staffing-audit-item">
        <i className="staffing-audit-dot" />
        <div><b>{pending.length} recommendations await review</b><div className="staffing-row-sub">Current {state.role} access scope</div></div>
      </div>
      <div className="staffing-audit-item">
        <i className="staffing-audit-dot" />
        <div><b>{constrained.length} people are at or above 70%</b><div className="staffing-row-sub">{constrained.map((person) => person.name).join(', ') || 'No constrained people'}</div></div>
      </div>
      <div className="staffing-audit-item">
        <i className="staffing-audit-dot" />
        <div><b>Customer mapping {data.source.version}</b><div className="staffing-row-sub">{data.metrics.projectTypes} projects • {data.metrics.deliverables} deliverables • {data.metrics.skills} skills</div></div>
      </div>
    </Drawer>
  );
}
