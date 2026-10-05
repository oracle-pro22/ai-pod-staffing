'use client';

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
import { allocationTone, availabilityEventLabel, formatDate, formatShortDate, personAllocationLabel } from '@/lib/formatting';
import { selectIdentityPerson, selectVisiblePeople } from '@/lib/selectors';
import { staffingFetch } from '@/lib/staffing-fetch';
import { requestBusinessDate } from '@/lib/request-date-policy';
import { availabilityRemainingHours } from '@/lib/live-presentation';

export function AvailabilityScreen() {
  const { data, state, dispatch, notify } = useStaffingApp();
  const [personId, setPersonId] = useState('');
  const [confirmCancel, setConfirmCancel] = useState<number | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [effectiveOn, setEffectiveOn] = useState(requestBusinessDate);
  const [showHistory, setShowHistory] = useState(false);
  const isAdmin = state.role === 'Administrator';
  const people = selectVisiblePeople(data, state.role);
  const ownPerson = selectIdentityPerson(data, state.role);
  const person = isAdmin && personId ? people.find((item) => item.id === personId) : ownPerson;
  if (!person) return <section className="staffing-screen"><PageHeader title={isAdmin ? 'People availability' : 'My availability'}
    description={isAdmin ? 'Choose a person to inspect their recorded availability.' : 'View your recorded availability and current capacity.'}
    actions={isAdmin ? <PersonCombobox people={people} value="" onChange={id => setPersonId(id)} placeholder="Search people by name" /> : undefined} />
    <div className="staffing-empty">{isAdmin ? 'Select a person to view availability.' : 'No signed-in person is available.'}</div></section>;
  const events = person.availability.filter((event) => showHistory || (event.status !== 'CANCELLED' && (event.effectiveUntil ?? event.endsOn) >= requestBusinessDate()));
  const own = person.id === ownPerson?.id;
  async function cancelEvent(eventId: number) {
    if (confirmCancel !== eventId) { setConfirmCancel(eventId); setEffectiveOn(requestBusinessDate()); return; }
    const event = person?.availability.find(e => e.id === eventId);
    if (!event) return;
    setBusy(eventId);
    try {
      const response = await staffingFetch(`/api/availability/${eventId}`, { method: 'DELETE', headers: { 'x-staffing-role': state.role, 'Content-Type': 'application/json' },
        body: JSON.stringify({ revision: event.revision, effectiveOn }) });
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
      <Card><CardHeader><div><h3>{showHistory ? 'Availability and history' : 'Upcoming availability events'}</h3><p>Visible to staffing recommendations once saved</p><Button size="small" onClick={() => setShowHistory(value => !value)}>{showHistory ? 'Hide history' : 'Show history'}</Button></div></CardHeader>
        <CardBody className="staffing-leave-list">{events.length ? events.map(event => <div className="staffing-leave" key={event.id}>
          <div className="staffing-date-tile"><strong>{formatShortDate(event.startsOn)}</strong><span>{availabilityEventLabel(event.eventType)}</span></div>
          <div><b>{availabilityEventLabel(event.title || event.eventType)}</b><div className="staffing-row-sub">{formatDate(event.startsOn)} to {formatDate(event.status === 'CANCELLED' ? event.endsOn : event.effectiveUntil ?? event.endsOn)} • {availabilityRemainingHours(event, event.startsOn)} hours{event.status === 'CANCELLED' ? ' • Cancelled' : event.effectiveUntil ? ' • Ended early (history retained)' : ''}</div></div>
          <div className="staffing-inline-actions"><Pill tone={event.capacityKind === 'EXTERNAL_WORK' ? 'blue' : 'green'}>{event.capacityKind === 'EXTERNAL_WORK' ? 'External work' : 'Unavailable'}</Pill>
            {own && event.status !== 'CANCELLED' && canPerform(state.role, 'MY_AVAILABILITY', 'canUpdate', data.authorization) && (event.effectiveUntil ?? event.endsOn) >= requestBusinessDate() && <><Button size="small" disabled={busy === event.id} onClick={() => dispatch({ type: 'open-drawer', drawer: { id: 'add-availability', title: 'Edit availability event', payload: { event } } })}>{event.startsOn < requestBusinessDate() ? 'Adjust remaining' : 'Edit'}</Button>
              {confirmCancel === event.id && <label>Stop counting from<input aria-label="Stop counting from" type="date" min={requestBusinessDate()} max={event.effectiveUntil ?? event.endsOn} value={effectiveOn} onChange={e => setEffectiveOn(e.target.value)} /><small>{availabilityRemainingHours(event, effectiveOn)} future hours will be removed. Earlier days stay unchanged.</small></label>}
              <Button size="small" disabled={busy === event.id} onClick={() => void cancelEvent(event.id)}>{busy === event.id ? 'Saving…' : confirmCancel === event.id ? 'Confirm end / cancel' : 'End / cancel'}</Button></>}</div></div>) : <div className="staffing-empty compact">No availability events are recorded for this view.</div>}</CardBody>
      </Card>
      <Card padded><h3>{isAdmin ? `${person.name} — capacity` : 'My capacity'}</h3>
        <div className="staffing-capacity-heading"><span>{data.allocationPeriod ? 'This week’s planned allocation' : 'Current allocation'}</span><b>{personAllocationLabel(person)}</b></div>
        {data.allocationPeriod && <p className="staffing-muted">{formatDate(data.allocationPeriod.start)} – {formatDate(data.allocationPeriod.end)} · {data.allocationPeriod.timezone}</p>}
        <ProgressBar value={person.allocationPct} tone={allocationTone(person.allocationPct, data.allocationPolicy?.maximumAllocationPct, person.staffingEligible !== false && (!person.capacityStatus || person.capacityStatus === 'CURRENT'))} />
        <p className="staffing-muted">{data.allocationPolicy ? `Current allocation limit: ${data.allocationPolicy.maximumAllocationPct}%` : 'Policy unavailable; allocation colours cannot be evaluated.'}</p>
        <div className="staffing-reason-grid"><div><span>Active pods today</span><strong>{person.activePods}</strong></div><div><span>Recorded events</span><strong>{events.length}</strong></div><div><span>Mapped skills</span><strong>{person.skills.length}</strong></div></div>
        <Notice icon="ℹ" title="Planned workload">{data.allocationPeriod ? 'Includes this week’s project work and external commitments. Leave reduces available hours.' : 'Capacity is based on the recorded profile.'}</Notice>
      </Card>
    </div>
  </section>;
}
