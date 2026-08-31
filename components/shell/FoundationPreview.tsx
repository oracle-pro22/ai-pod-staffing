'use client';

import { Card } from '@/components/ui/Card';
import { Pill } from '@/components/ui/Pill';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { screenLabel } from '@/lib/role-policy';
import { selectDashboardMetrics } from '@/lib/selectors';

export function FoundationPreview() {
  const { data, state } = useStaffingApp();
  const metrics = selectDashboardMetrics(data, state.role, state.drafts);
  const cards = [
    { label: 'Open requests', value: metrics.openRequests, badge: `${metrics.highPriorityRequests} high priority`, tone: 'red' as const },
    { label: 'Team allocation', value: `${metrics.averageAllocationPct}%`, badge: `${metrics.constrainedPeople} constrained`, tone: 'amber' as const },
    { label: 'Staffing progress', value: `${metrics.staffingProgressPct}%`, badge: `${metrics.staffedRequests} staffed`, tone: 'teal' as const },
    { label: 'Pending recommendations', value: metrics.pendingRecommendations, badge: 'Advisory', tone: 'purple' as const },
  ];

  return (
    <section className="staffing-foundation-preview">
      <div className="staffing-foundation-head">
        <div>
          <h2>{state.activeScreen === 'dashboard' ? 'Good morning, Indranie' : screenLabel(state.activeScreen)}</h2>
          <p>Review demand, capacity, and AI-assisted staffing decisions across the customer success team.</p>
        </div>
      </div>
      <div className="staffing-foundation-grid">
        {cards.map((card) => (
          <Card className="staffing-preview-kpi" key={card.label}>
            <div className="staffing-preview-kpi-top"><span>{card.label}</span><Pill tone={card.tone}>{card.badge}</Pill></div>
            <strong>{card.value}</strong>
          </Card>
        ))}
      </div>
    </section>
  );
}
