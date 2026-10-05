'use client';
import { useEffect, useState, type FormEvent } from 'react';
import { Button } from '@/components/ui/Button';
import { DropdownField } from '@/components/ui/DropdownField';
import { FormGroup, TextField } from '@/components/ui/FormControls';
import { staffingFetch } from '@/lib/staffing-fetch';

type Kind = 'events' | 'decisions' | 'assignments';
type Filters = { kind: Kind; from_date: string; to_date: string; request_id: string; actor: string; action: string };
type RecordRow = { record_id: string; occurred_at: string; action: string; actor_name: string; actor_subject: string;
  request_id: string | null; entity_type: string; entity_id: string; reason: string | null;
  policy_version?: string; person_id?: string; person_name?: string; role_in_pod?: string;
  starts_on?: string; ends_on?: string; assigned_hours?: number; closed_at?: string; proposal_id?: string; decision_id?: string };
type Page = { records: RecordRow[]; next_cursor: string | null; read_only: boolean };
const initial: Filters = { kind: 'events', from_date: '', to_date: '', request_id: '', actor: '', action: '' };

export function AuditHistory() {
  const [draft, setDraft] = useState(initial), [filters, setFilters] = useState(initial);
  const [cursors, setCursors] = useState(['']);
  const [page, setPage] = useState<Page | null>(null), [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const cursor = cursors[cursors.length - 1];
  useEffect(() => {
    const controller = new AbortController();
    setPage(null); setError('');
    const query = new URLSearchParams({ limit: '50' });
    for (const [key, value] of Object.entries({ ...filters, cursor })) if (value) query.set(key, value);
    staffingFetch(`/api/agentic/admin/audit?${query}`, { cache: 'no-store', signal: controller.signal })
      .then(async response => {
        const payload = await response.json();
        if (!response.ok) throw new Error(typeof payload.error === 'string' ? payload.error : payload.error?.message || 'History could not be loaded.');
        if (!controller.signal.aborted) setPage(payload.data);
      }).catch(e => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'History could not be loaded.'); });
    return () => controller.abort();
  }, [filters, cursor, revision]);
  function apply(event: FormEvent) { event.preventDefault(); setFilters({ ...draft }); setCursors(['']); }
  function refresh() { setCursors(['']); setRevision(n => n + 1); }
  return <div>
    <h3>Audit trail and saved staffing history</h3>
    <p>Read-only records from Oracle. Audit events, approval decisions and final assignments are stored separately. Historical decisions retain their original policy. Date filters and timestamps use UTC.</p>
    <form onSubmit={apply} className="staffing-form-grid">
      <FormGroup label="Record type"><DropdownField value={draft.kind} onChange={kind => setDraft({ ...draft, kind: kind as Kind })}
        options={[{ value: 'events', label: 'Audit events' }, { value: 'decisions', label: 'Approval / rejection decisions' }, { value: 'assignments', label: 'Final assignments' }]} /></FormGroup>
      <FormGroup label="Request ID"><TextField value={draft.request_id} maxLength={30} placeholder="REQ-1055" onChange={e => setDraft({ ...draft, request_id: e.target.value.trim() })} /></FormGroup>
      <FormGroup label="From date (UTC)"><TextField type="date" value={draft.from_date} onChange={e => setDraft({ ...draft, from_date: e.target.value })} /></FormGroup>
      <FormGroup label="Through date (UTC)"><TextField type="date" min={draft.from_date || undefined} value={draft.to_date} onChange={e => setDraft({ ...draft, to_date: e.target.value })} /></FormGroup>
      <FormGroup label="Actor name or identity"><TextField maxLength={255} value={draft.actor} onChange={e => setDraft({ ...draft, actor: e.target.value })} /></FormGroup>
      <FormGroup label="Action / status (exact)"><TextField maxLength={60} placeholder="APPROVED, CONFIRMED…" value={draft.action} onChange={e => setDraft({ ...draft, action: e.target.value })} /></FormGroup>
      <div><Button type="submit" variant="primary">Apply filters</Button> <Button type="button" onClick={() => { setDraft(initial); setFilters(initial); refresh(); }}>Clear</Button> <Button type="button" onClick={refresh}>Refresh</Button></div>
    </form>
    {error && <p role="alert">{error} <Button onClick={refresh}>Try again</Button></p>}
    {!page && !error && <p role="status">Loading saved history…</p>}
    {page && <>
      <p role="status">Page {cursors.length} · {page.records.length} records · Read only</p>
      {!page.records.length ? <p>No saved records match these filters.</p> : <div style={{ overflowX: 'auto' }}><table className="staffing-role-table">
        <thead><tr><th>Recorded (UTC)</th><th>Action / status</th><th>Actor</th><th>Request / record</th><th>Details</th></tr></thead>
        <tbody>{page.records.map(row => <tr key={row.record_id}>
          <td>{row.occurred_at.replace('T', ' ')} UTC</td><td>{row.action}</td><td>{row.actor_name}<small style={{ display: 'block' }}>{row.actor_subject}</small></td>
          <td>{row.request_id || 'Not request-specific'}<small style={{ display: 'block' }}>{row.entity_type} · {row.entity_id}</small></td>
          <td><details><summary>View record</summary><p>Record ID: {row.record_id}</p><p>{row.reason || 'No note recorded.'}</p>
            {row.policy_version && <p>Recorded policy: {row.policy_version}</p>}
            {row.person_id && <><p>{row.person_name} ({row.person_id}) · {row.role_in_pod}</p><p>{row.starts_on} – {row.ends_on} · {row.assigned_hours} hours</p>
              <p>Proposal: {row.proposal_id} · Decision: {row.decision_id}</p>{row.closed_at && <p>Closed: {row.closed_at} UTC</p>}</>}
          </details></td>
        </tr>)}</tbody></table></div>}
      <div className="staffing-inline-actions"><Button disabled={cursors.length === 1} onClick={() => setCursors(value => value.slice(0, -1))}>Previous</Button>
        <Button disabled={!page.next_cursor} onClick={() => page.next_cursor && setCursors(value => [...value, page.next_cursor!])}>Next</Button></div>
    </>}
  </div>;
}
