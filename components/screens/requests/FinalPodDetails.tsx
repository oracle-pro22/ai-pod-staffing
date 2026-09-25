'use client';
import { staffingFetch } from '@/lib/staffing-fetch';
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import { FormGroup, TextArea } from '@/components/ui/FormControls';
import { Pill } from '@/components/ui/Pill';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { useLiveWorkspace } from '@/lib/use-live-workspace';
import { formatDate } from '@/lib/formatting';
import { liveStatusLabel } from '@/lib/live-presentation';
import { announceStaffingChange, CLOSURE_EXPLANATION, CLOSED_EXPLANATION, OVERDUE_EXPLANATION } from '@/lib/project-closure';

export function FinalPodDetails({ requestId }: { requestId: string }) {
  const { notify } = useStaffingApp();
  const { snapshot, error, refresh } = useLiveWorkspace('REQUESTS');
  const [closing, setClosing] = useState(false), [reason, setReason] = useState(''), [busy, setBusy] = useState(false);
  const router = useRouter();
  const request = snapshot?.requests.find(r => r.request_id === requestId);
  const members = snapshot?.assignments.filter(a => a.request_id === requestId) ?? [];
  const canClose = request?.status === 'STAFFED' && request.can_close === true;
  async function closeProject() {
    if (!request || !canClose || busy || !reason.trim()) return;
    setBusy(true);
    try {
      const r = await staffingFetch(`/api/agentic/requests/${requestId}/close`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request_revision: request.request_revision, reason: reason.trim() }) });
      const body = await r.json();
      if (!r.ok) throw new Error(typeof body.error === 'string' ? body.error : body.error?.message || 'Check project status before retrying.');
      setClosing(false); setReason(''); announceStaffingChange(); router.refresh(); notify('Project closed', CLOSED_EXPLANATION);
    } catch (e) { notify('Closure not confirmed', e instanceof Error ? e.message : 'Refresh project status before retrying.'); }
    finally { setBusy(false); }
  }
  return <section className="staffing-section-gap"><h3>Assigned POD</h3>
    {error && <p role="alert">{error} <Button onClick={refresh}>Refresh</Button></p>}{!snapshot && !error && <p role="status">Loading assignments…</p>}
    {request?.past_planned_end && <p className="staffing-fit-summary-note">{OVERDUE_EXPLANATION}</p>}
    {request?.status === 'CLOSED' && <p className="staffing-fit-summary-note">{CLOSED_EXPLANATION}</p>}
    {snapshot && !members.length && <p className="staffing-muted">No final assignment yet.</p>}
    {members.map(m => <article className="staffing-candidate recommended" key={m.assignment_id}>
      <div className="staffing-candidate-head"><Avatar initials={m.full_name.split(' ').map(p => p[0]).join('').slice(0, 2)} />
        <div className="staffing-candidate-main"><b>{m.full_name}</b><div className="staffing-candidate-meta">{m.role_in_pod === 'POD_LEAD' ? 'POD Lead' : 'POD Member'}{m.assigned_hours !== undefined && <> · {m.assigned_hours} originally planned hours</>}</div></div>
        <Pill tone="teal">{liveStatusLabel(m.status)}</Pill></div><div className="staffing-rationale">{m.responsibilities}</div>
        {m.starts_on && m.ends_on && <small>{formatDate(m.starts_on.slice(0, 10))} – {formatDate(m.ends_on.slice(0, 10))}</small>}
    </article>)}
    {canClose && !closing && <Button onClick={() => setClosing(true)}>Close project</Button>}
    {canClose && closing && <div className="staffing-fit-summary-note"><p>Close this project?</p><p>{CLOSURE_EXPLANATION}</p><small>Dates follow the assignment’s staffing-policy timezone. This does not record actual hours worked.</small>
      <FormGroup label="Closure note (required)"><TextArea value={reason} maxLength={2000} disabled={busy} onChange={e => setReason(e.target.value)} /></FormGroup>
      <div className="staffing-inline-actions"><Button variant="primary" disabled={busy || !reason.trim()} onClick={() => void closeProject()}>{busy ? 'Closing…' : 'Confirm closure'}</Button>
        <Button disabled={busy} onClick={() => setClosing(false)}>Cancel</Button></div></div>}
  </section>;
}
