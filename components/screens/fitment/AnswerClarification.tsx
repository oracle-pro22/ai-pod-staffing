'use client';
import { useState, useRef, type FormEvent } from 'react';
import { Button } from '@/components/ui/Button';
import { FormGroup, TextArea } from '@/components/ui/FormControls';
import { staffingFetch } from '@/lib/staffing-fetch';

type Field = 'business_objectives' | 'expected_outcomes' | 'project_description';
type Clarification = { revision: number; execution_id: string; fields: Field[]; questions: string[] } & Record<Field, string>;
const labels: Record<Field, string> = { business_objectives: 'Business objectives and audience', expected_outcomes: 'Expected outcomes and success measures', project_description: 'Project scope' };

export function AnswerClarification({ requestId, disabled, onSaved }: { requestId: string; disabled: boolean; onSaved: (message: string) => void }) {
  const [details, setDetails] = useState<Clarification | null>(null);
  const [busy, setBusy] = useState(false), [message, setMessage] = useState('');
  const saving = useRef(false);
  async function load() {
    if (saving.current || disabled) return;
    saving.current = true; setBusy(true); setMessage('');
    try {
      const response = await staffingFetch(`/api/agentic/requests/${requestId}/clarification`, { cache: 'no-store' });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error?.message || result.error || 'Could not load the current questions.');
      setDetails(result.data);
    } catch (e) { setMessage(e instanceof Error ? e.message : 'Refresh and retry.'); }
    finally { saving.current = false; setBusy(false); }
  }
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!details || disabled || saving.current) return;
    const form = new FormData(event.currentTarget);
    saving.current = true; setBusy(true); setMessage('');
    try {
      const response = await staffingFetch(`/api/agentic/requests/${requestId}/clarification`, { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ revision: details.revision, execution_id: details.execution_id,
          business_objectives: form.get('business_objectives'), expected_outcomes: form.get('expected_outcomes'), project_description: form.get('project_description') }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error?.message || result.error || 'Could not save the answers.');
      onSaved(result.data.status === 'QUEUED' ? 'Answers saved as a new revision. The agent rerun is queued; its recommendation will appear here.'
        : 'Answers saved as a new revision—agent run pending. Enable agents and start the worker to process it.');
    } catch (e) { setMessage(e instanceof Error ? e.message : 'Save status unknown. Refresh before retrying.'); }
    finally { saving.current = false; setBusy(false); }
  }
  return <section className="staffing-card" style={{ padding: '1.25rem', marginBottom: '1rem' }}>
    <h3>Answer clarification</h3>
    <p>Update the request details below. Saving creates a new revision and reruns fitment; previous recommendations cannot be approved for the updated request.</p>
    {!details ? <Button onClick={load} disabled={busy || disabled}>{busy ? 'Loading…' : 'Answer clarification'}</Button> : <form onSubmit={save}>
      <ul>{details.questions.map(question => <li key={question}>{question}</li>)}</ul>
      {(Object.keys(labels) as Field[]).map(field => <FormGroup key={field} label={`${labels[field]}${details.fields.includes(field) ? ' — answer required' : ''}`} full>
        <TextArea name={field} defaultValue={details[field]} required={field !== 'expected_outcomes' || details.fields.includes(field)}
          maxLength={field === 'project_description' ? 4000 : 32000} disabled={busy || disabled} />
      </FormGroup>)}
      <Button type="submit" variant="primary" disabled={busy || disabled}>{busy ? 'Saving…' : 'Save answers and rerun'}</Button>
    </form>}
    {message && <p role="alert">{message}</p>}
  </section>;
}
