'use client';

import { capacityAttention } from '@/lib/allocation-policy';
import { Button } from '@/components/ui/Button';
import { Drawer } from '@/components/ui/Drawer';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { selectDashboardMetrics, selectVisiblePeople } from '@/lib/selectors';

export function NotificationDrawer() {
  const { data, state, dispatch } = useStaffingApp();
  const open = state.drawer?.id === 'notifications';
  const pending = selectDashboardMetrics(data, state.role).pendingRecommendations;
  const constrained = selectVisiblePeople(data, state.role)
    .filter(person => capacityAttention(person, data.allocationPolicy?.maximumAllocationPct));
  const close = () => dispatch({ type: 'close-drawer' });

  return (
    <Drawer open={open} title="Notifications" onClose={close} footer={<Button onClick={close}>Close</Button>}>
      <div className="staffing-audit-item">
        <i className="staffing-audit-dot" />
        <div><b>{pending} recommendation{pending === 1 ? '' : 's'} await review</b><div className="staffing-row-sub">Current {state.role} access scope</div></div>
      </div>
      <div className="staffing-audit-item">
        <i className="staffing-audit-dot" />
        <div><b>{data.allocationPolicy ? `${constrained.length} people are at or above ${data.allocationPolicy.maximumAllocationPct}%` : 'Allocation policy unavailable'}</b><div className="staffing-row-sub">{constrained.map((person) => person.name).join(', ') || 'No constrained people'}</div></div>
      </div>
      <div className="staffing-audit-item">
        <i className="staffing-audit-dot" />
        <div><b>Customer mapping {data.source.version}</b><div className="staffing-row-sub">{data.metrics.projectTypes} projects • {data.metrics.deliverables} deliverables • {data.metrics.skills} skills</div></div>
      </div>
    </Drawer>
  );
}
