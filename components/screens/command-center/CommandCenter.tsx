'use client';
import { useEffect, useState } from 'react';
import { DropdownField } from '@/components/ui/DropdownField';
import { staffingQueues, projectDemand, buildDemandWeeks } from '@/lib/dashboard-demand';
import { requestBusinessDate } from '@/lib/request-date-policy';
import { personAllocationLabel } from '@/lib/formatting';

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
import { timeOfDayGreeting } from '@/lib/time-greeting';

export function CommandCenter() {
  const { data, state, dispatch } = useStaffingApp();
  const [projectType, setProjectType] = useState('');
  const [requestGroup, setRequestGroup] = useState<'pending' | 'staffed' | null>(null);
  const limit = data.allocationPolicy?.maximumAllocationPct;
  const requests = selectVisibleRequests(data, state.role);
  const people = selectVisiblePeople(data, state.role);
  const identity = selectIdentityPerson(data, state.role);
  const metrics = selectDashboardMetrics(data, state.role);
  const isMember = state.role === 'POD Member';
  const greetingName = identity?.name.split(' ')[0] ?? 'there';
  const [greeting, setGreeting] = useState(() => timeOfDayGreeting());
  const queues = staffingQueues(requests);
  const activeGroup = requestGroup ?? (queues.pending.length || !queues.ongoing.length ? 'pending' : 'staffed');
  const displayedRequests = activeGroup === 'pending' ? queues.pending : queues.ongoing;
  const demand = projectDemand(requests, projectType);
  const demandWeeks = buildDemandWeeks(demand.map(request => request.neededBy), data.allocationPeriod?.start ?? requestBusinessDate());
  const capacityPeople = people.filter(person => person.staffingEligible !== false).sort((a, b) => {
    const aCurrent = !a.capacityStatus || a.capacityStatus === 'CURRENT';
    const bCurrent = !b.capacityStatus || b.capacityStatus === 'CURRENT';
    return Number(bCurrent) - Number(aCurrent) || b.allocationPct - a.allocationPct;
  });
  const watchedPeople = isMember ? (identity && identity.staffingEligible !== false ? [identity] : []) : capacityPeople.slice(0, 5);

  useEffect(() => {
    const updateGreeting = () => setGreeting(timeOfDayGreeting());
    updateGreeting();
    const timer = window.setInterval(updateGreeting, 60_000);
    return () => window.clearInterval(timer);
  }, []);

  function openRequest(requestId: string) {
    dispatch({ type: 'open-drawer', drawer: { id: 'request-details', title: 'Request details', payload: { requestId } } });
  }

  return (
    <section className="staffing-screen staffing-dashboard">
      <PageHeader
        title={`${greeting}, ${greetingName}`}
        actions={canPerform(state.role, 'REQUESTS', 'canCreate', data.authorization) ? <Button variant="primary" onClick={() => dispatch({ type: 'open-modal', modal: { id: 'create-request', title: 'Create staffing request' } })}>＋ New request</Button> : undefined}
      />

      <div className="staffing-grid staffing-kpi-grid">
        <KpiCard label="Open requests" value={metrics.openRequests} badge={`${metrics.highPriorityRequests} high priority`} tone="red" />
        <KpiCard label="Team allocation" value={data.identity && !people.some(p => p.capacityStatus === 'CURRENT') ? 'Needs refresh' : `${metrics.averageAllocationPct}%`} badge={`${metrics.constrainedPeople} constrained`} tone={allocationTone(metrics.averageAllocationPct, limit, people.some(p => p.staffingEligible !== false && (!p.capacityStatus || p.capacityStatus === 'CURRENT')))} />
        <KpiCard label="Staffing progress" value={`${metrics.staffingProgressPct}%`} badge={`${metrics.staffedRequests} of ${metrics.openRequests} staffed`} tone="teal" />
        <KpiCard label="Pending recommendations" value={metrics.pendingRecommendations} badge="Advisory" tone="purple" />
      </div>

      <div className="staffing-grid staffing-two-col">
        {isMember ? <MyFitmentPreview /> : (
          <Card>
            <CardHeader>
              <div><h3>Staffing requests</h3><p>{activeGroup === 'pending' ? 'Requests needing recommendation, review, or approval' : 'Approved projects · no staffing action needed'}</p></div>
              <Button size="small" onClick={() => dispatch({ type: 'set-screen', screen: 'requests' })}>View all</Button>
            </CardHeader>
            <div className="staffing-dashboard-tabs" role="group" aria-label="Staffing request group">
              <button type="button" aria-pressed={activeGroup === 'pending'} onClick={() => setRequestGroup('pending')}>Pending staffing ({queues.pending.length})</button>
              <button type="button" aria-pressed={activeGroup === 'staffed'} onClick={() => setRequestGroup('staffed')}>Staffed projects ({queues.ongoing.length})</button>
            </div>
            <div className="staffing-list" aria-label={activeGroup === 'pending' ? 'Pending staffing requests' : 'Ongoing staffed projects'}>
              {!displayedRequests.length ? <div className="staffing-empty">{activeGroup === 'pending' ? 'No requests are waiting for staffing in this access scope.' : 'No ongoing staffed projects in this access scope.'}</div> : null}
              {displayedRequests.slice(0, 5).map((request) => (
                <div className="staffing-list-row" key={request.id}>
                  <div className="staffing-list-request"><div className="staffing-row-title">{request.title}</div><div className="staffing-row-sub">{request.id} • {request.projectType.name} • {request.deliverable.name}</div></div>
                  <Pill className="staffing-list-status" tone={statusTone(request.status)}>{activeGroup === 'staffed' ? 'Staffed' : request.status}</Pill>
                  <div className="staffing-list-date"><b>{formatShortDate(request.neededBy)}</b><div className="staffing-row-sub">{activeGroup === 'pending' ? request.priority : 'Planned end'}</div></div>
                  <Button size="small" onClick={() => openRequest(request.id)}>{activeGroup === 'pending' ? 'Review' : 'Open'}</Button>
                </div>
              ))}
            </div>
          </Card>
        )}

        <Card>
          <CardHeader>
            <div><h3>{isMember ? 'My Capacity' : 'Capacity watch'}</h3><p>{data.allocationPeriod ? `This week · ${formatShortDate(data.allocationPeriod.start)} – ${formatShortDate(data.allocationPeriod.end)}` : isMember ? 'Your current allocation and pod commitments' : data.identity ? 'Current weekly allocation and confirmed PODs' : 'Current allocation from People'}</p></div>
            <Pill tone={limit === undefined ? 'neutral' : 'teal'}>{limit === undefined ? 'Policy unavailable' : `${limit}% limit`}</Pill>
          </CardHeader>
          <CardBody className="staffing-capacity-watch-body">
            {!watchedPeople.length && <div className="staffing-empty compact">No staffing-eligible people in this access scope.</div>}
            {watchedPeople.map((person) => (
              <div className="staffing-capacity-row" key={person.id}>
                <Avatar initials={person.initials} />
                <div>
                  <div className="staffing-cap-name"><b title={person.name}>{person.name}</b><span>{personAllocationLabel(person)}</span></div>
                  {data.identity && person.capacityStatus !== 'CURRENT' ? <div className="staffing-progress staffing-capacity-unknown" aria-label="Capacity needs refresh" /> : <ProgressBar value={person.allocationPct} tone={allocationTone(person.allocationPct, limit, person.staffingEligible !== false)} />}
                </div>
                <Pill tone={allocationTone(person.allocationPct, limit, person.staffingEligible !== false && (!person.capacityStatus || person.capacityStatus === 'CURRENT'))}>{person.activePods} pods</Pill>
              </div>
            ))}
            {!isMember && capacityPeople.length > 5 && <div className="staffing-dashboard-capacity-footer"><span>Top 5 of {capacityPeople.length} people</span>{canAccessScreen(state.role, 'interests', data.authorization) && <Button size="small" onClick={() => dispatch({ type: 'set-screen', screen: 'interests' })}>View team</Button>}</div>}
            {limit === undefined && <p className="staffing-muted">Allocation policy unavailable; colours are neutral.</p>}
          </CardBody>
        </Card>
      </div>

      {!isMember ? (
        <div className="staffing-grid staffing-two-col staffing-section-gap">
          <Card>
            <CardHeader className="staffing-dashboard-demand-head"><div><h3>Upcoming demand</h3><p>{demand.length} pending requests · next five weeks</p></div><div className="staffing-dashboard-demand-filter"><DropdownField aria-label="Filter demand by project type" value={projectType} onChange={setProjectType} options={[{ value: '', label: 'All project types' }, ...data.catalog.projects.map(project => ({ value: project.id, label: project.name }))]} /></div></CardHeader>
            <CardBody>
              <div className="staffing-heat">{demandWeeks.map((week) => <span className={week.level} key={week.label} title={`${week.label}: ${week.count} requests`} aria-label={`${week.label}: ${week.count} requests`}>{week.count}</span>)}</div>
              <div className="staffing-heat-labels">{demandWeeks.map((week) => <span key={week.label}>{week.label}</span>)}</div>
              <div className="staffing-demand-list">
                {!demand.length && <p>No pending staffing requests match this project type.</p>}
                {demand.slice(0, 3).map((request) => <div key={request.id}><span><b>{request.deliverable.name}</b><small>{request.projectType.name} • {request.title}</small></span><span><b>{formatShortDate(request.neededBy)}</b><small>{request.estimatedHours}h</small></span></div>)}
              </div>
            </CardBody>
          </Card>
          {canAccessScreen(state.role, 'admin', data.authorization) ? <Card className="staffing-audit-card">
            <CardHeader><div><h3>Audit trail</h3><p>Recorded changes, decisions and final assignments</p></div><Button size="small" onClick={() => { dispatch({ type: 'set-admin-tab', tab: 'audit' }); dispatch({ type: 'set-screen', screen: 'admin' }); }}>Open audit trail</Button></CardHeader>
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
