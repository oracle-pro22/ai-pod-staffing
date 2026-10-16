import { Card } from '@/components/ui/Card';
import { formatDate } from '@/lib/formatting';
import { allocationMetric } from '@/lib/live-presentation';
import type { Pod } from './LiveStaffingReview';

function names(values: string[]) {
  return values.length < 3 ? values.join(' and ') : `${values.slice(0, -1).join(', ')} and ${values.at(-1)}`;
}

function hours(value: number) {
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 ? `${Number(number.toFixed(2))}h` : 'Not recorded';
}

export function WhyThisPod({ proposal }: { proposal: Pod }) {
  const people = proposal.members;
  const leads = names(people.filter(m => m.role_in_pod === 'POD_LEAD').map(m => m.full_name));
  const members = names(people.filter(m => m.role_in_pod !== 'POD_LEAD').map(m => m.full_name));
  const support = members ? `, supported by ${members}` : '';
  const workSupport = members ? `, with support from ${members}` : '';
  const copy = proposal.explanation_copy;
  // Only approved phrase IDs are used. All names, dates and metrics below are
  // from the saved, validated proposal—not parsed from model-generated prose.
  const intro = !leads ? 'The saved plan lists the team and its contributions below.'
    : copy?.opening === 'work_first' ? `The work will be led by ${leads}${workSupport}.`
    : `${leads} will lead the work${support}.`;
  const equalHours = people.length > 1 && people.every(m => Number(m.planned_hours) === Number(people[0].planned_hours));
  const effort = copy?.effort === 'people_first'
    ? `The ${people.length}-person team is scheduled for ${hours(proposal.total_hours)} in total.`
    : equalHours ? `The ${hours(proposal.total_hours)} of planned work is split equally across the team.`
    : `The plan assigns ${hours(proposal.total_hours)} across ${people.length} ${people.length === 1 ? 'person' : 'people'}.`;
  const manual = ['MANUAL', 'MANUAL_DRAFT', 'CAPTAIN_MANUAL'].includes(proposal.origin ?? '') || people.some(m => m.source === 'MANUAL');
  const approved = proposal.status === 'APPROVED';

  return <Card padded className="staffing-pod-explanation">
    <h3>Why this POD</h3>
    <p className="staffing-pod-explanation-intro">{intro} {effort}</p>
    <dl className="staffing-pod-explanation-facts">
      <div><dt>Schedule</dt><dd>{formatDate(proposal.starts_on.slice(0, 10))} – {formatDate(proposal.ends_on.slice(0, 10))}</dd></div>
      <div><dt>Total planned effort</dt><dd>{hours(proposal.total_hours)}</dd></div>
      <div><dt>Team</dt><dd>{people.length} {people.length === 1 ? 'person' : 'people'}</dd></div>
    </dl>
    <div className="staffing-pod-explanation-table"><table aria-label="Planned team contributions">
      <thead><tr><th scope="col">Team member</th><th scope="col">Planned effort</th><th scope="col">Projected allocation</th></tr></thead>
      <tbody>{people.map(m => {
        const period = allocationMetric(m.factors?.window_allocation_pct);
        const peak = allocationMetric(m.factors?.projected_allocation_pct);
        const podOnly = m.source === 'MANUAL';
        return <tr key={m.person_id}><td><b>{m.full_name}</b><small>{m.role_in_pod === 'POD_LEAD' ? 'POD Lead' : 'POD Member'}</small></td>
          <td>{hours(m.planned_hours)}</td><td><b>{period ?? 'Not recorded'}</b><small>{podOnly ? 'POD-only utilization' : 'For the request period'}</small>
            {peak !== null && peak !== period && <small>{peak} busiest-week {podOnly ? 'POD-only utilization' : 'allocation'}</small>}</td></tr>;
      })}</tbody>
    </table></div>
    <p className="staffing-pod-explanation-check">{manual
      ? 'Captain-selected plan. Manual choices bypass skill matching and use a POD-only capacity check that ignores leave and external commitments.'
      : 'This saved plan passed the staffing checks when it was created, accounting for recorded skills, leave and existing commitments.'}</p>
    <p className="staffing-pod-explanation-note">{approved ? 'These assignments are approved.'
      : proposal.status === 'REJECTED' ? 'This proposal was rejected. It does not reserve capacity.'
      : 'Capacity is reserved only after approval.'}</p>
  </Card>;
}
