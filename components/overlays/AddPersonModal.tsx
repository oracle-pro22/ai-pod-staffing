'use client';

import { type FormEvent, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/Button';
import { FormGroup, TextField } from '@/components/ui/FormControls';
import { Modal } from '@/components/ui/Modal';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { canPerform } from '@/lib/role-policy';

export function AddPersonModal() {
  const { data, state, dispatch, notify } = useStaffingApp();
  const router = useRouter();
  const busy = useRef(false);
  const [saving, setSaving] = useState(false);
  const [fullName, setFullName] = useState('');
  const open = state.modal?.id === 'add-person' && state.role === 'Administrator'
    && canPerform(state.role, 'TEAM_SKILLS', 'canCreate', data.authorization);
  const close = () => { if (!busy.current) { setFullName(''); dispatch({ type: 'close-modal' }); } };
  const matchingName = data.people.some((person) => person.name.trim().toLowerCase() === fullName.trim().toLowerCase());

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!open || busy.current) return;
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    busy.current = true;
    setSaving(true);
    try {
      const response = await fetch('/api/people', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'x-staffing-role': state.role },
        body: JSON.stringify({ fullName: form.get('fullName'), jobTitle: form.get('jobTitle'), location: form.get('location'),
          email: form.get('email'), allocationPct: Number(form.get('allocationPct')), activePods: Number(form.get('activePods')) }),
      });
      const result = await response.json() as { data?: { personId: string; fullName: string }; error?: string };
      if (!response.ok || !result.data) { notify('Person not added', result.error || 'Please check the details and retry.'); return; }
      formElement.reset();
      setFullName('');
      dispatch({ type: 'close-modal' });
      router.refresh();
      notify('Person added', `${result.data.fullName} (${result.data.personId}) is now available in Request source.`);
    } catch {
      notify('Save status unknown', 'The response could not be received. Refresh the directory and check whether the person was added before retrying.');
    } finally { busy.current = false; setSaving(false); }
  }

  return <Modal open={open} title="Add person" onClose={close} footer={<>
    <Button onClick={close} disabled={saving}>Cancel</Button>
    <Button type="submit" form="addPersonForm" variant="primary" disabled={saving}>{saving ? 'Saving…' : 'Add person'}</Button>
  </>}>
    <form id="addPersonForm" onSubmit={save}>
      <p className="staffing-muted">Creates an active person in Oracle. Person ID and initials are generated automatically. This does not grant login access or assign an application role.</p>
      <div className="staffing-form-grid">
        <FormGroup label="Full name" full><TextField name="fullName" required maxLength={250} value={fullName} onChange={(event) => setFullName(event.target.value)} disabled={saving} /></FormGroup>
        {matchingName ? <p role="status">A person with this name already exists. Check their record before adding another person; use email to distinguish them.</p> : null}
        <FormGroup label="Job title"><TextField name="jobTitle" required maxLength={250} disabled={saving} /></FormGroup>
        <FormGroup label="Location"><TextField name="location" required maxLength={150} disabled={saving} /></FormGroup>
        <FormGroup label="Email (recommended)" full><TextField name="email" type="email" maxLength={320} disabled={saving} /></FormGroup>
        <FormGroup label="Current allocation (%)"><TextField name="allocationPct" type="number" required min="0" max="100" step="0.01" placeholder="Enter 0 if unallocated" disabled={saving} /></FormGroup>
        <FormGroup label="Active PODs"><TextField name="activePods" type="number" required min="0" max="99999" step="1" placeholder="Enter 0 if none" disabled={saving} /></FormGroup>
      </div>
    </form>
  </Modal>;
}
