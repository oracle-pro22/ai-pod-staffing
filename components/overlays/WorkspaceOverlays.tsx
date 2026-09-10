'use client';

import { type FormEvent, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';

import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import { Drawer } from '@/components/ui/Drawer';
import { FormGroup, SelectField, TextField } from '@/components/ui/FormControls';
import { Modal } from '@/components/ui/Modal';
import { Notice } from '@/components/ui/Notice';
import { Pill } from '@/components/ui/Pill';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { canPerform } from '@/lib/role-policy';
import { selectIdentityPerson, selectVisiblePeople, selectVisibleRequests } from '@/lib/selectors';

export function WorkspaceOverlays() {
  return <><QuickAllocationDrawer /><AllocationGuardrailModal /><PersonDetailsDrawer /><AvailabilityDrawer /></>;
}

function QuickAllocationDrawer() {
  const { data, state, dispatch, notify } = useStaffingApp();
  const open = state.drawer?.id === 'quick-allocation' && canPerform(state.role, 'ALLOCATION_CALENDAR', 'canCreate', data.authorization);
  const people = useMemo(() => [...selectVisiblePeople(data, state.role)].sort((a, b) => b.allocationPct - a.allocationPct), [data, state.role]);
  const requests = selectVisibleRequests(data, state.role);
  const close = () => dispatch({ type: 'close-drawer' });

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const person = people.find((item) => item.id === form.get('personId'));
    const request = requests.find((item) => item.id === form.get('requestId'));
    const date = String(form.get('date') || '');
    const hours = Number(form.get('hours') || 0);
    if (!person || !request || !date || hours < 1 || hours > 8) { notify('Missing information', 'Select a person, request, date, and between 1 and 8 hours.'); return; }
    const hasConflict = person.availability.some((item) => date >= item.startsOn.slice(0, 10) && date <= item.endsOn.slice(0, 10));
    if (hasConflict) { notify('Allocation blocked', `${person.name} has a recorded availability conflict on this date.`); return; }
    close();
    notify('Feature in progress', 'This workflow will be available in a future release.');
  }

  return <Drawer open={open} title="Quick allocation" onClose={close} footer={<><Button type="button" onClick={close}>Cancel</Button><Button type="submit" form="quickAllocationForm" variant="primary">Save allocation</Button></>}><form id="quickAllocationForm" onSubmit={save}><div className="staffing-form-grid"><FormGroup label="Person" full><SelectField name="personId">{people.map((person) => <option key={person.id} value={person.id}>{person.name} • {person.allocationPct}%</option>)}</SelectField></FormGroup><FormGroup label="Request" full><SelectField name="requestId">{requests.map((request) => <option key={request.id} value={request.id}>{request.id} • {request.title}</option>)}</SelectField></FormGroup><FormGroup label="Date"><TextField type="date" name="date" defaultValue="2026-07-27" /></FormGroup><FormGroup label="Hours"><TextField type="number" name="hours" min="1" max="8" defaultValue="4" /></FormGroup></div><Notice icon="♢" title="Allocation workflow integration is in progress">Existing database availability remains visible while assignment persistence is being added.</Notice></form></Drawer>;
}

function AllocationGuardrailModal() {
  const { state, dispatch } = useStaffingApp();
  const open = state.modal?.id === 'allocation-guardrail';
  const payload = state.modal?.payload;
  const close = () => dispatch({ type: 'close-modal' });
  return <Modal open={open} title="Allocation guardrail" onClose={close} footer={<Button onClick={close}>Return to calendar</Button>}><Notice icon="!" title="Allocation blocked">{String(payload?.personName ?? 'This person')} would reach {String(payload?.projected ?? '')}% allocation. Consider {String(payload?.alternateName ?? 'an available alternate')} or adjust the requested hours.</Notice></Modal>;
}

function PersonDetailsDrawer() {
  const { data, state, dispatch } = useStaffingApp();
  const open = state.drawer?.id === 'person-details';
  const personId = typeof state.drawer?.payload?.personId === 'string' ? state.drawer.payload.personId : null;
  const visible = selectVisiblePeople(data, state.role);
  const person = visible.find((item) => item.id === personId);
  const close = () => dispatch({ type: 'close-drawer' });
  return <Drawer open={open} title={person?.name ?? 'Person details'} onClose={close}>{person ? <><div className="staffing-person-drawer-head"><Avatar initials={person.initials} /><div><h3>{person.name}</h3><p>{person.jobTitle} • {person.location}</p></div></div><div className="staffing-reason-grid"><div><span>Allocation</span><strong>{person.allocationPct}%</strong></div><div><span>Active pods</span><strong>{person.activePods}</strong></div><div><span>Mapped skills</span><strong>{person.skills.length}</strong></div></div><h4>Capabilities and evidence</h4>{person.skills.map((skill) => <div className="staffing-person-skill" key={skill.id}><div><b>{skill.name}</b><small>{skill.category}</small></div><span className="staffing-stars">{'★'.repeat(skill.strength)}{'☆'.repeat(5 - skill.strength)}</span><p>{skill.evidence || 'No evidence note recorded'}</p></div>)}</> : <div className="staffing-empty">Person unavailable in the current access scope.</div>}</Drawer>;
}

function AvailabilityDrawer() {
  const { data, state, dispatch, notify } = useStaffingApp();
  const router = useRouter();
  const [saving, setSaving] = useState(false);
  const open = state.drawer?.id === 'add-availability' && canPerform(state.role, 'MY_AVAILABILITY', 'canCreate', data.authorization);
  const person = selectIdentityPerson(data, state.role);
  const close = () => dispatch({ type: 'close-drawer' });
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!person) return;
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const startsOn = String(form.get('startsOn') || '');
    const endsOn = String(form.get('endsOn') || '');
    if (!startsOn || !endsOn || endsOn < startsOn) { notify('Dates need attention', 'Choose a valid start and end date.'); return; }
    setSaving(true);
    try {
      const response = await fetch('/api/availability', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-staffing-role': state.role,
        },
        body: JSON.stringify({
          personId: person.id,
          eventType: String(form.get('eventType') || ''),
          startsOn,
          endsOn,
          title: String(form.get('title') || ''),
          allocatedHours: Number(form.get('hours') || 0),
        }),
      });
      const result = await response.json().catch(() => ({})) as { data?: unknown; error?: string };
      if (!response.ok || !result.data) {
        notify('Event not saved', result.error || 'The availability event could not be saved. Please try again.');
        return;
      }
      formElement.reset();
      close();
      router.refresh();
      notify('Availability saved', 'The event is now available to staffing recommendations.');
    } catch {
      notify('Event not saved', 'The database could not be reached. Please try again.');
    } finally {
      setSaving(false);
    }
  }
  return <Drawer open={open} title="Add availability event" onClose={close} footer={<><Button type="button" onClick={close} disabled={saving}>Cancel</Button><Button type="submit" form="availabilityForm" variant="primary" disabled={saving}>{saving ? 'Saving…' : 'Save event'}</Button></>}><form id="availabilityForm" onSubmit={save}><div className="staffing-readonly-note">Saved events are used when staffing recommendations evaluate capacity.</div><div className="staffing-form-grid staffing-section-gap"><FormGroup label="Event type" full><SelectField name="eventType"><option>OOO</option><option>Leave</option><option>Travel</option><option>Training</option><option>Reduced hours</option></SelectField></FormGroup><FormGroup label="Start date"><TextField required type="date" name="startsOn" defaultValue="2026-08-17" /></FormGroup><FormGroup label="End date"><TextField required type="date" name="endsOn" defaultValue="2026-08-18" /></FormGroup><FormGroup label="Title" full><TextField name="title" placeholder="What should schedulers see?" /></FormGroup><FormGroup label="Allocated hours" full><TextField type="number" min="0" name="hours" defaultValue="8" /></FormGroup></div></form></Drawer>;
}
