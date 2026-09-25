'use client';
import { personAllocationLabel } from '@/lib/formatting';

import { useState } from 'react';
import { PersonCombobox } from '@/components/ui/PersonCombobox';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { Notice } from '@/components/ui/Notice';
import { PageHeader } from '@/components/ui/PageHeader';
import { Pill } from '@/components/ui/Pill';
import { ProgressBar } from '@/components/ui/ProgressBar';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { canPerform } from '@/lib/role-policy';
import { allocationTone, formatDate, formatShortDate } from '@/lib/formatting';
import { selectIdentityPerson, selectVisiblePeople } from '@/lib/selectors';
import { staffingFetch } from '@/lib/staffing-fetch';
import { requestBusinessDate } from '@/lib/request-date-policy';

export function AvailabilityScreen() {
  const { data, state, dispatch, notify } = useStaffingApp();
  const [personId, setPersonId] = useState('');
  const [confirmCancel, setConfirmCancel] = useState<number | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const isAdmin = state.role === 'Administrator';
  const people = selectVisiblePeople(data, state.role);
  const ownPerson = selectIdentityPerson(data, state.role);
  const person = isAdmin && personId ? people.find((item) => item.id === personId) : ownPerson;
  if (!person) return <section className="staffing-screen"><PageHeader title={isAdmin ? 'People availability' : 'My availability'}
    description={isAdmin ? 'Choose a person to inspect their recorded availability.' : 'View your recorded availability and current capacity.'}
    actions={isAdmin ? <PersonCombobox people={people} value="" onChange={id => setPersonId(id)} placeholder="Search people by name" /> : undefined} />
    <div className="staffing-empty">{isAdmin ? 'Select a person to view availability.' : 'No signed-in person is available.'}</div></section>;
  const events = person.availability.filter((event) => event.endsOn >= requestBusinessDate());
  const own = person.id === ownPerson?.id;
  async function cancelEvent(eventId: number) {
    if (confirmCancel !== eventId) { setConfirmCancel(eventId); return; }
    setBusy(eventId);
    try {
      const response = await staffingFetch(`/api/availability/${eventId}`, { method: 'DELETE', headers: { 'x-staffing-role': state.role } });
      const result = await response.json().catch(() => ({})) as { error?: string };
      if (!response.ok) { notify('Event not cancelled', result.error || 'The event could not be cancelled.'); return; }
      setConfirmCancel(null); notify('Availability cancelled', 'The event no longer affects future capacity.'); window.location.reload();
    } catch { notify('Cancellation status unknown', 'Refresh before trying again.'); }
    finally { setBusy(null); }
  }
  return <section className="staffing-screen">
    <PageHeader title={person.id === ownPerson?.id ? 'My availability' : 'People availability'}
      description={isAdmin ? 'Your availability opens first. You can also inspect other people’s recorded capacity.' : 'View your recorded availability and current capacity.'}
      actions={<>{isAdmin && <PersonCombobox people={people} value={person.id} onChange={id => { if (id) setPersonId(id); }} placeholder="Search people by name" />}
        {person.id === ownPerson?.id && canPerform(state.role, 'MY_AVAILABILITY', 'canCreate', data.authorization)
          && <Button variant="primary" onClick={() => dispatch({ type: 'open-drawer', drawer: { id: 'add-availability', title: 'Add availability event' } })}>＋ Add availability event</Button>}</>} />
    <div className="staffing-availability-layout">
      <Card><CardHeader><div><h3>Upcoming availability events</h3><p>Visible to staffing recommendations once saved</p></div><Pill tone="green">Profile current</Pill></CardHeader>
        <CardBody className="staffing-leave-list">{events.length ? events.map(event => <div className="staffing-leave" key={event.id}>
          <div className="staffing-date-tile"><strong>{formatShortDate(event.startsOn)}</strong><span>{event.eventType}</span></div>
          <div><b>{event.title || event.eventType}</b><div className="staffing-row-sub">{formatDate(event.startsOn)} to {formatDate(event.endsOn)} • {event.allocatedHours || 0} hours</div></div>
          <div className="staffing-inline-actions"><Pill tone={event.capacityKind === 'EXTERNAL_WORK' ? 'blue' : 'green'}>{event.capacityKind === 'EXTERNAL_WORK' ? 'External work' : 'Unavailable'}</Pill>
            {own && <><Button size="small" disabled={busy === event.id} onClick={() => dispatch({ type: 'open-drawer', drawer: { id: 'add-availability', title: 'Edit availability event', payload: { event } } })}>Edit</Button>
              <Button size="small" disabled={busy === event.id} onClick={() => void cancelEvent(event.id)}>{busy === event.id ? 'Cancelling…' : confirmCancel === event.id ? 'Confirm cancel' : 'Cancel event'}</Button></>}</div></div>) : <div className="staffing-empty compact">No upcoming availability events are recorded for this person.</div>}</CardBody>
      </Card>
      <Card padded><h3>{isAdmin ? `${person.name} — capacity` : 'My capacity'}</h3>
        <div className="staffing-capacity-heading"><span>{data.allocationPeriod ? 'This week’s planned allocation' : 'Current allocation'}</span><b>{personAllocationLabel(person)}</b></div>
        {data.allocationPeriod && <p className="staffing-muted">{formatDate(data.allocationPeriod.start)} – {formatDate(data.allocationPeriod.end)} · {data.allocationPeriod.timezone}</p>}
        <ProgressBar value={person.allocationPct} tone={allocationTone(person.allocationPct)} />
        <div className="staffing-reason-grid"><div><span>Active pods today</span><strong>{person.activePods}</strong></div><div><span>Recorded events</span><strong>{events.length}</strong></div><div><span>Mapped skills</span><strong>{person.skills.length}</strong></div></div>
        <Notice icon="ℹ" title="Planned workload">{data.allocationPeriod ? 'Includes dated project work and external commitments, using working capacity after leave. Closed projects retain hours through their closure day only.' : 'Capacity is based on the recorded profile.'}</Notice>
      </Card>
    </div>
  </section>;
}
