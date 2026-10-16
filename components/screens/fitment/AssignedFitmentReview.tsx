'use client';

import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { DropdownField } from '@/components/ui/DropdownField';
import { PageHeader } from '@/components/ui/PageHeader';
import { Pill } from '@/components/ui/Pill';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { formatDate } from '@/lib/formatting';
import { liveStatusLabel } from '@/lib/live-presentation';
import { CLOSED_EXPLANATION } from '@/lib/project-closure';
import { useLiveWorkspace } from '@/lib/use-live-workspace';
import type { LiveWorkspace } from '@/types/assignments';
import type { StaffingRequest } from '@/types/staffing';

/** Never loads proposal snapshots, alternatives, execution logs or mutation APIs. */
export function AssignedFitmentReview() {
  const { data, state, dispatch } = useStaffingApp();
  const { snapshot, error, refresh } = useLiveWorkspace('AI_FITMENT');
  return <AssignedFitmentPresentation snapshot={snapshot} error={error} onRefresh={refresh}
    activeRequestId={state.activeRequestId} personId={data.identity?.personId ?? ''}
    details={data.requests} onSelect={requestId => dispatch({ type: 'set-active-request', requestId })} />;
}

export function AssignedFitmentPresentation({ snapshot, error, onRefresh, activeRequestId, personId, details, onSelect }: {
  snapshot: LiveWorkspace | null; error: string; onRefresh: () => void; activeRequestId: string | null;
  personId: string; details: StaffingRequest[]; onSelect: (requestId: string) => void;
}) {
  // The server, not the active-request ID or a selected persona, defines membership.
  const requests = snapshot?.requests ?? [];
  const request = requests.find(row => row.request_id === activeRequestId) ?? requests[0];
  const detail = request ? details.find(row => row.id === request.request_id) : undefined;
  const members = request ? snapshot?.assignments.filter(row => row.request_id === request.request_id) ?? [] : [];
  const own = members.find(row => row.person_id === personId);
  const closed = request?.status === 'CLOSED';
  const methods = new Set(members.map(row => row.staffing_method).filter(Boolean));
  const method = methods.size === 1 && methods.has('MANUAL_OVERRIDE') ? 'Captain manual override'
    : methods.size === 1 && methods.has('AGENT_RECOMMENDATION') ? 'Agent recommendation approved by a Captain'
    : 'Approved staffing decision';

  return <section className="staffing-screen">
    <PageHeader title="AI fitment review" description="Read-only review of the approved PODs you belong to, including closed project history."
      actions={<>{requests.length > 0 && <label className="staffing-fitment-picker"><span>Your assigned request</span>
        <DropdownField aria-label="Your assigned request" value={request?.request_id ?? ''} onChange={onSelect}
          options={requests.map(row => ({ value: row.request_id, label: `${row.request_id} — ${row.title} • ${liveStatusLabel(row.status)}` }))} />
      </label>}<Button onClick={onRefresh}>Refresh</Button></>} />
    {error && <p role="alert">{error}</p>}
    {!snapshot && !error && <p role="status">Loading your assigned PODs…</p>}
    {snapshot && !request && <div className="staffing-empty">No approved PODs are assigned to you yet. Fitment reviews appear here after a Captain approves a POD that includes you.</div>}
    {request && <div className="staffing-fit-layout">
      <Card padded className="staffing-request-summary">
        <Pill tone={closed ? '' : 'teal'}>{liveStatusLabel(request.status)}</Pill>
        <h3 className="staffing-summary-title">{request.title}</h3>
        <p className="staffing-muted">{request.request_id}{detail?.projectType.name ? ` · ${detail.projectType.name}` : ''}</p>
        <dl className="staffing-summary-list">
          <div><dt>Your POD role</dt><dd>{own ? roleName(own.role_in_pod) : 'Not recorded'}</dd></div>
          {request.planned_start_on && <div><dt>Planned start</dt><dd>{formatDate(request.planned_start_on.slice(0, 10))}</dd></div>}
          {request.planned_end_on && <div><dt>Planned completion</dt><dd>{formatDate(request.planned_end_on.slice(0, 10))}</dd></div>}
          {detail?.deliverables.length ? <div><dt>Key deliverables</dt><dd>{detail.deliverables.map(item => item.name).join(', ')}</dd></div> : null}
          {detail?.requiredSkills.length ? <div><dt>Required capabilities</dt><dd><div className="staffing-tag-row">{detail.requiredSkills.map(item => <span key={item.id}>{item.name}</span>)}</div></dd></div> : null}
        </dl>
        {detail?.businessObjectives && <div className="staffing-fit-summary-note"><b>Business objectives</b><p>{detail.businessObjectives}</p></div>}
        {detail?.expectedOutcomes && <div className="staffing-fit-summary-note"><b>Expected outcomes</b><p>{detail.expectedOutcomes}</p></div>}
      </Card>
      <div>
        <Card padded>
          <h3>{closed ? 'Approved POD · Project closed' : 'Approved POD'}</h3>
          <p>{method}. This is the final assigned team, not a pending recommendation.</p>
          {closed && <p>{CLOSED_EXPLANATION}</p>}
          <p className="staffing-muted">Read-only. Individual hours, schedules and detailed responsibilities are shown only where your profile access allows. Private candidate rankings and alternative teams are not included.</p>
        </Card>
        <AssignedPeople title="POD Lead" people={members.filter(row => row.role_in_pod === 'POD_LEAD')} personId={personId} />
        <AssignedPeople title="POD Members" people={members.filter(row => row.role_in_pod === 'POD_MEMBER')} personId={personId} />
      </div>
    </div>}
  </section>;
}

function roleName(role: string) { return role === 'POD_LEAD' ? 'POD Lead' : 'POD Member'; }

function AssignedPeople({ title, people, personId }: { title: string; people: LiveWorkspace['assignments']; personId: string }) {
  return <Card className="staffing-candidate-section"><CardHeader><h3>{title}</h3><Pill>{people.length} assigned</Pill></CardHeader>
    <CardBody>{people.length ? people.map(person => <article className="staffing-candidate" key={person.assignment_id}>
      <div className="staffing-candidate-head">
        <Avatar initials={person.full_name.split(' ').map(part => part[0]).join('').slice(0, 2)} />
        <div className="staffing-candidate-main"><b>{person.full_name}</b><div className="staffing-candidate-meta">{roleName(person.role_in_pod)}</div></div>
        <Pill tone={person.person_id === personId ? 'teal' : ''}>{person.person_id === personId ? 'Your assignment' : person.status === 'CLOSED' ? 'Closed' : 'Assigned'}</Pill>
      </div>
      <p className="staffing-rationale">{person.responsibilities}</p>
      {(person.assigned_hours !== undefined || (person.starts_on && person.ends_on)) && <div className="staffing-candidate-foot">
        {person.assigned_hours !== undefined && <span>{person.assigned_hours} originally planned hours</span>}
        {person.starts_on && person.ends_on && <span>{formatDate(person.starts_on.slice(0, 10))} – {formatDate(person.ends_on.slice(0, 10))}</span>}
      </div>}
    </article>) : <p className="staffing-empty compact">{title === 'POD Members' ? 'No POD Members requested.' : 'No Lead assignment recorded.'}</p>}</CardBody>
  </Card>;
}
