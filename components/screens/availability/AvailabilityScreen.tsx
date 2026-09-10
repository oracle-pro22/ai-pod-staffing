'use client';

import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Notice } from '@/components/ui/Notice';
import { PageHeader } from '@/components/ui/PageHeader';
import { Pill } from '@/components/ui/Pill';
import { ProgressBar } from '@/components/ui/ProgressBar';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { canPerform } from '@/lib/role-policy';
import { allocationTone, formatDate, formatShortDate } from '@/lib/formatting';
import { selectIdentityPerson } from '@/lib/selectors';

export function AvailabilityScreen() {
  const { data, state, dispatch } = useStaffingApp();
  const person = selectIdentityPerson(data, state.role);
  if (!person) return <div className="staffing-empty">No signed-in person is available.</div>;
  const events = person.availability.map((event) => ({ ...event, id: `${person.id}-${event.startsOn}-${event.endsOn}-${event.eventType}`, personId: person.id }));
  return <section className="staffing-screen"><PageHeader title="My availability" description="View your recorded availability and current capacity." actions={canPerform(state.role, 'MY_AVAILABILITY', 'canCreate', data.authorization) ? <Button variant="primary" onClick={() => dispatch({ type: 'open-drawer', drawer: { id: 'add-availability', title: 'Add availability event' } })}>＋ Add availability event</Button> : undefined} /><div className="staffing-availability-layout"><Card><CardHeader><div><h3>Upcoming availability events</h3><p>Visible to staffing recommendations once saved</p></div><Pill tone="green">Profile current</Pill></CardHeader><CardBody className="staffing-leave-list">{events.length ? events.map((event) => <div className="staffing-leave" key={event.id}><div className="staffing-date-tile"><strong>{formatShortDate(event.startsOn)}</strong><span>{event.eventType}</span></div><div><b>{event.title || event.eventType}</b><div className="staffing-row-sub">{formatDate(event.startsOn)} to {formatDate(event.endsOn)} • {event.allocatedHours || 0} hours</div></div><Pill tone="green">Database</Pill></div>) : <div className="staffing-empty compact">No availability events are recorded for this person.</div>}</CardBody></Card><Card padded><h3>My capacity</h3><div className="staffing-capacity-heading"><span>Current allocation</span><b>{person.allocationPct}%</b></div><ProgressBar value={person.allocationPct} tone={allocationTone(person.allocationPct)} /><div className="staffing-reason-grid"><div><span>Active pods</span><strong>{person.activePods}</strong></div><div><span>Recorded events</span><strong>{events.length}</strong></div><div><span>Mapped skills</span><strong>{person.skills.length}</strong></div></div><Notice icon="ℹ" title="Database-backed snapshot">Future capacity will combine assignments and approved availability.</Notice></Card></div></section>;
}
