'use client';
import { useState, type FormEvent } from 'react';
import { Button } from '@/components/ui/Button';
import { requestBusinessDate } from '@/lib/request-date-policy';
import { staffingFetch } from '@/lib/staffing-fetch';
import type { RequestRow } from './LiveStaffingReview';

export function RescheduleRequest({ request, disabled, onSaved }: { request: RequestRow; disabled: boolean; onSaved: () => void }) {
  const [busy, setBusy] = useState(false), [message, setMessage] = useState('');
  async function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); if (busy || disabled) return;
    const form = new FormData(e.currentTarget);
    setBusy(true); setMessage('');
    try {
      const response = await staffingFetch(`/api/agentic/requests/${request.request_id}/reschedule`, { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ revision: request.request_revision,
          starts_on: form.get('start'), ends_on: form.get('end'), needed_by: form.get('needed'), total_hours: Number(form.get('hours')) }) });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.error === 'string' ? result.error : result.error?.message || 'Dates could not be updated.');
      setMessage('Dates saved. Previous recommendations are invalid. Run fitment again and review the new schedule.'); onSaved();
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Refresh to check the save status.'); }
    finally { setBusy(false); }
  }
  return <section className="staffing-card" style={{ padding: '1.25rem', marginBottom: '1rem' }}>
    <h3>Update dates and remaining effort</h3>
    <p>This unstaffed request starts in the past. Choose the remaining work period. Earlier dates will not receive new assignments.</p>
    <form onSubmit={save} className="staffing-form-grid">
      <label>Start date<input className="staffing-field" name="start" type="date" min={requestBusinessDate()} defaultValue={requestBusinessDate()} required disabled={busy || disabled} /></label>
      <label>Completion date<input className="staffing-field" name="end" type="date" min={requestBusinessDate()} defaultValue={request.ends_on && request.ends_on >= requestBusinessDate() ? request.ends_on : ''} required disabled={busy || disabled} /></label>
      <label>Needed by<input className="staffing-field" name="needed" type="date" min={requestBusinessDate()} defaultValue={request.needed_by && request.needed_by >= requestBusinessDate() ? request.needed_by : ''} required disabled={busy || disabled} /></label>
      <label>Remaining effort (total hours)<input className="staffing-field" name="hours" type="number" min="0.01" max="100000" step="0.01" defaultValue={request.total_hours} required disabled={busy || disabled} /></label>
      <p>Review the hours explicitly. Changing dates does not automatically reduce the work or reserve capacity.</p>
      <Button type="submit" disabled={busy || disabled}>{busy ? 'Saving…' : 'Save dates — rerun required'}</Button>
      {message && <p role="status">{message}</p>}
    </form>
  </section>;
}
