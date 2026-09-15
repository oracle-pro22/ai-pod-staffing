'use client';
import { formatDate, personAllocationLabel } from '@/lib/formatting';

import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { KpiCard } from '@/components/ui/KpiCard';
import { PageHeader } from '@/components/ui/PageHeader';
import { Pill } from '@/components/ui/Pill';
import { ProgressBar } from '@/components/ui/ProgressBar';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { allocationTone, formatShortDate, statusTone } from '@/lib/formatting';
import { canAccessScreen, canPerform } from '@/lib/role-policy';
import { selectDashboardMetrics, selectIdentityPerson, selectScopedRecommendations, selectVisiblePeople, selectVisibleRequests } from '@/lib/selectors';

export function CommandCenter() {
  const { data, state, dispatch } = useStaffingApp();
  const requests = selectVisibleRequests(data, state.role);
  const people = selectVisiblePeople(data, state.role);
  const identity = selectIdentityPerson(data, state.role);
  const metrics = selectDashboardMetrics(data, state.role);
  const isMember = state.role === 'POD Member';
  const greetingName = identity?.name.split(' ')[0] ?? 'there';
  const activeRequests = requests.filter((request) => request.status.toLowerCase() !== 'closed');
  const demand = activeRequests.slice(0, 5);
  const demandWeeks = buildDemandWeeks(activeRequests.map((request) => request.neededBy), Boolean(data.identity));
  const capacityPeople = [...people].sort((a, b) => b.allocationPct - a.allocationPct);

  function openRequest(requestId: string) {
    dispatch({ type: 'open-drawer', drawer: { id: 'request-details', title: 'Request details', payload: { requestId } } });
  }

  return (
    <section className="staffing-screen">
      <PageHeader
        title={`Good morning, ${greetingName}`}
        actions={canPerform(state.role, 'REQUESTS', 'canCreate', data.authorization) ? <Button variant="primary" onClick={() => dispatch({ type: 'open-modal', modal: { id: 'create-request', title: 'Create staffing request' } })}>＋ New request</Button> : undefined}
      />

      <div className="staffing-grid staffing-kpi-grid">
        <KpiCard label="Open requests" value={metrics.openRequests} badge={`${metrics.highPriorityRequests} high priority`} tone="red" />
        <KpiCard label="Team allocation" value={data.identity && !people.some(p => p.capacityStatus === 'CURRENT') ? 'Needs refresh' : `${metrics.averageAllocationPct}%`} badge={`${metrics.constrainedPeople} constrained`} tone="amber" />
        <KpiCard label="Staffing progress" value={`${metrics.staffingProgressPct}%`} badge={`${metrics.staffedRequests} of ${metrics.openRequests} staffed`} tone="teal" />
        <KpiCard label="Pending recommendations" value={metrics.pendingRecommendations} badge="Advisory" tone="purple" />
      </div>

      <div className="staffing-grid staffing-two-col">
        {isMember ? <MyFitmentPreview /> : (
          <Card>
            <CardHeader>
              <div><h3>Priority staffing queue</h3><p>Requests needing recommendation, review, or approval</p></div>
              <Button size="small" onClick={() => dispatch({ type: 'set-screen', screen: 'requests' })}>View all</Button>
            </CardHeader>
            <div className="staffing-list">
              {activeRequests.length === 0 ? <div className="staffing-empty compact">No active projects are assigned in this access scope.</div> : null}
              {activeRequests.slice(0, 5).map((request) => (
                <div className="staffing-list-row" key={request.id}>
                  <div className="staffing-list-request"><div className="staffing-row-title">{request.title}</div><div className="staffing-row-sub">{request.id} • {request.projectType.name} • {request.deliverable.name}</div></div>
                  <Pill className="staffing-list-status" tone={statusTone(request.status)}>{request.status}</Pill>
                  <div className="staffing-list-date"><b>{formatShortDate(request.neededBy)}</b><div className="staffing-row-sub">{request.priority}</div></div>
                  <Button size="small" onClick={() => openRequest(request.id)}>Review</Button>
                </div>
              ))}
            </div>
          </Card>
        )}

        <Card>
          <CardHeader>
            <div><h3>{isMember ? 'My Capacity' : 'Capacity watch'}</h3><p>{data.allocationPeriod ? `Planned allocation: ${formatDate(data.allocationPeriod.start)} – ${formatDate(data.allocationPeriod.end)}` : isMember ? 'Your current allocation and pod commitments' : data.identity ? 'Current weekly allocation and confirmed PODs' : 'Current allocation from People'}</p></div>
            <Pill tone="amber">Human approval</Pill>
          </CardHeader>
          <CardBody className="staffing-capacity-watch-body">
            {(isMember ? (identity ? [identity] : []) : capacityPeople).map((person) => (
              <div className="staffing-capacity-row" key={person.id}>
                <Avatar initials={person.initials} />
                <div>
                  <div className="staffing-cap-name"><b>{person.name}</b><span>{personAllocationLabel(person)}</span></div>
                  {data.identity && person.capacityStatus !== 'CURRENT' ? <div className="staffing-progress staffing-capacity-unknown" aria-label="Capacity needs refresh" /> : <ProgressBar value={person.allocationPct} tone={allocationTone(person.allocationPct)} />}
                </div>
                <Pill tone={allocationTone(person.allocationPct)}>{person.activePods} pods</Pill>
              </div>
            ))}
          </CardBody>
        </Card>
      </div>

      {!isMember ? (
        <div className="staffing-grid staffing-two-col staffing-section-gap">
          <Card>
            <CardHeader><div><h3>Upcoming demand</h3><p>Staffing requests by customer project type</p></div><select className="staffing-select" defaultValue="all"><option value="all">All project types</option>{data.catalog.projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></CardHeader>
            <CardBody>
              <div className="staffing-heat">{demandWeeks.map((week) => <span className={week.level} key={week.label} />)}</div>
              <div className="staffing-heat-labels">{demandWeeks.map((week) => <span key={week.label}>{week.label}</span>)}</div>
              <div className="staffing-demand-list">
                {demand.slice(0, 3).map((request) => <div key={request.id}><span><b>{request.deliverable.name}</b><small>{request.projectType.name} • {request.title}</small></span><span><b>{formatShortDate(request.neededBy)}</b><small>{request.estimatedHours}h</small></span></div>)}
              </div>
            </CardBody>
          </Card>
          {canAccessScreen(state.role, 'admin', data.authorization) ? <Card className="staffing-audit-card">
            <CardHeader><div><h3>Audit trail</h3><p>Stored recommendations awaiting review</p></div><Button size="small" onClick={() => dispatch({ type: 'set-screen', screen: 'admin' })}>Open audit trail</Button></CardHeader>
          </Card> : null}
        </div>
      ) : null}
    </section>
  );
}

function MyFitmentPreview() {
  const { data, state, dispatch } = useStaffingApp();
  const request = selectVisibleRequests(data, state.role).find((item) => selectScopedRecommendations(item, data, state.role).length > 0);
  const recommendation = request ? selectScopedRecommendations(request, data, state.role)[0] : null;
  return (
    <Card>
      <CardHeader><div><h3>My POD assignment</h3><p>Your approved team and project</p></div><Pill tone="teal">Database</Pill></CardHeader>
      <CardBody>
        {request && recommendation ? <>
          <div className="staffing-preview-score"><span><b>{request.title}</b><small>{request.id} • {recommendation.roleInPod}</small></span>{!data.identity && <strong>{recommendation.score}</strong>}</div>
          <p className="staffing-muted">{recommendation.rationale}</p>
          <Button size="small" onClick={() => { dispatch({ type: 'set-active-request', requestId: request.id }); dispatch({ type: 'open-drawer', drawer: { id: 'request-details', title: request.title, payload: { requestId: request.id } } }); }}>Open my project</Button>
        </> : <div className="staffing-empty compact">No assigned recommendation is available.</div>}
      </CardBody>
    </Card>
  );
}

function buildDemandWeeks(neededByDates: string[], live = false) {
  const base = live ? new Date() : new Date(Date.UTC(2026, 6, 20));
  if (live) base.setUTCDate(base.getUTCDate() - (base.getUTCDay() + 6) % 7);
  const weeks = Array.from({ length: 5 }, (_, index) => {
    const start = new Date(base);
    start.setUTCDate(base.getUTCDate() + index * 7);
    const end = new Date(start);
    end.setUTCDate(start.getUTCDate() + 6);
    const startKey = start.toISOString().slice(0, 10);
    const endKey = end.toISOString().slice(0, 10);
    const count = neededByDates.filter((date) => date >= startKey && date <= endKey).length;
    return {
      label: start.toLocaleDateString('en-US', { timeZone: 'UTC', month: 'short', day: 'numeric' }),
      count,
    };
  });
  const maximum = Math.max(...weeks.map((week) => week.count), 1);
  return weeks.map((week) => ({
    ...week,
    level: week.count === 0 ? '' : week.count === maximum ? 'v' : week.count / maximum >= 0.5 ? 'h' : 'm',
  }));
}
