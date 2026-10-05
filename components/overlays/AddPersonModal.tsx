'use client';
import { staffingFetch } from '@/lib/staffing-fetch';

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
    && canPerform(state.role, 'TEAM_SKILLS', 'canCreate', data.authorization)
    && canPerform(state.role, 'ACCESS_MANAGEMENT', 'canAdminister', data.authorization);
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
      const response = await staffingFetch('/api/people', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'x-staffing-role': state.role },
        body: JSON.stringify({ fullName: form.get('fullName'), jobTitle: form.get('jobTitle'), location: form.get('location'),
          email: form.get('email'), roles: form.getAll('roles'), enabled: form.get('enabled') === 'on', staffingEligible: form.get('staffingEligible') === 'on' }),
      });
      const result = await response.json() as { data?: { personId: string; fullName: string; enabled: boolean }; error?: string };
      if (!response.ok || !result.data) { notify('Person not added', result.error || 'Please check the details and retry.'); return; }
      formElement.reset();
      setFullName('');
      dispatch({ type: 'close-modal' });
      router.refresh();
      notify('Employee added', `${result.data.fullName} (${result.data.personId}): ${result.data.enabled ? 'can sign in with the shared initial password and complete first-login setup.' : 'account created with login disabled until an administrator enables access.'}`);
    } catch {
      notify('Save status unknown', 'The response could not be received. Refresh the directory and check whether the person was added before retrying.');
    } finally { busy.current = false; setSaving(false); }
  }

  return <Modal open={open} title="Add person" onClose={close} footer={<>
    <Button onClick={close} disabled={saving}>Cancel</Button>
    <Button type="submit" form="addPersonForm" variant="primary" disabled={saving}>{saving ? 'Saving…' : 'Add person'}</Button>
  </>}>
    <form id="addPersonForm" onSubmit={save}>
      <p className="staffing-muted">Creates an employee, login account and selected roles together. The configured shared initial password is used. First-login setup collects their skills and commitments. Capacity starts at 8 hours/day and 40 hours/week; allocation and POD counts come from recorded work.</p>
      <div className="staffing-form-grid">
        <FormGroup label="Full name" full><TextField name="fullName" required maxLength={250} value={fullName} onChange={(event) => setFullName(event.target.value)} disabled={saving} /></FormGroup>
        {matchingName ? <p role="status">A person with this name already exists. Check their record before adding another person; use email to distinguish them.</p> : null}
        <FormGroup label="Job title"><TextField name="jobTitle" required maxLength={250} disabled={saving} /></FormGroup>
        <FormGroup label="Location"><TextField name="location" required maxLength={150} disabled={saving} /></FormGroup>
        <FormGroup label="Oracle email" full><TextField name="email" type="email" required maxLength={320} disabled={saving} /></FormGroup>
        <fieldset className="staffing-editor-box"><legend>Application roles — select at least one</legend>
          {([['POD_MEMBER', 'POD Member'], ['POD_LEAD', 'POD Lead'], ['POD_CAPTAIN', 'POD Captain'], ['SYSTEM_ADMINISTRATOR', 'Administrator']] as const).map(([code, label]) =>
            <label key={code} style={{ display: 'block', margin: '0.5rem 0' }}><input type="checkbox" name="roles" value={code} defaultChecked={code === 'POD_MEMBER'} disabled={saving} /> {label}</label>)}
        </fieldset>
        <fieldset className="staffing-editor-box"><legend>Access and staffing</legend>
          <label style={{ display: 'block', margin: '0.5rem 0' }}><input type="checkbox" name="enabled" defaultChecked disabled={saving} /> Enable login now</label>
          <label style={{ display: 'block', margin: '0.5rem 0' }}><input type="checkbox" name="staffingEligible" defaultChecked disabled={saving} /> Eligible for POD assignments after setup</label>
          <small>Uncheck staffing eligibility for an access-only employee. Uncheck login to keep the account pending.</small>
        </fieldset>
      </div>
    </form>
  </Modal>;
}
