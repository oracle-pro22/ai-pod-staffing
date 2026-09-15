'use client';
import { staffingFetch } from '@/lib/staffing-fetch';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { PageHeader } from '@/components/ui/PageHeader';
import { canPerform } from '@/lib/role-policy';
import { downloadExcelWorkbook } from '@/lib/export-xlsx';
import { useLiveWorkspace } from '@/lib/use-live-workspace';
import { announceStaffingChange, CLOSURE_EXPLANATION, CLOSED_EXPLANATION, OVERDUE_EXPLANATION } from '@/lib/project-closure';

export function LiveAssignments({ view = 'projects' }: { view?: 'projects' | 'calendar' | 'reports' }) {
  const { data, state, dispatch, notify } = useStaffingApp();
  const router = useRouter();
  const [week, setWeek] = useState('');
  const [error, setError] = useState('');
  const [closing, setClosing] = useState<string | null>(null);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const resource = view === 'calendar' ? 'ALLOCATION_CALENDAR' : view === 'reports' ? 'REPORTS' : 'REQUESTS';
  const { snapshot, error: loadError, refresh } = useLiveWorkspace(resource, week);

  async function closeProject() {
    const request = snapshot?.requests.find(r => r.request_id === closing);
    if (!request || !reason.trim() || busy) return;
    setBusy(true); setError('');
    try {
      const response = await staffingFetch(`/api/agentic/requests/${request.request_id}/close`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request_revision: request.request_revision, reason: reason.trim() }) });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error?.message || 'Refresh project status before retrying.');
      setClosing(null); setReason(''); announceStaffingChange(); router.refresh();
      notify('Project closed', CLOSED_EXPLANATION);
    } catch (e) { setError(e instanceof Error ? e.message : 'Check project status before retrying.'); }
    finally { setBusy(false); }
  }

  async function exportExcel() {
    if (!snapshot?.can_export || busy) return;
    setBusy(true);
    try { await downloadExcelWorkbook({ fileName: `staffing-assignments-${snapshot.week_start}.xlsx`, sheetName: 'Final assignments',
      headers: ['Request', 'Title', 'Person', 'POD role', 'Status', 'Starts', 'Ends', 'Planned hours'],
      rows: snapshot.assignments.map(a => [a.request_id, snapshot.requests.find(r => r.request_id === a.request_id)?.title || '', a.full_name, a.role_in_pod, a.status, a.starts_on?.slice(0, 10) ?? '', a.ends_on?.slice(0, 10) ?? '', a.assigned_hours ?? '']) }); }
    catch { setError('Export could not be created. Try again.'); } finally { setBusy(false); }
  }

  const title = view === 'calendar' ? 'Allocation calendar' : view === 'reports' ? 'Staffing reports' : 'Staffing requests';
  return <section className="staffing-screen">
    <PageHeader title={title} description={view === 'projects' ? 'Review requests, final POD assignments, and project responsibilities.' : 'Confirmed assignments and current weekly capacity.'}
      actions={<><Button disabled={busy} onClick={() => { setError(''); refresh(); }}>Refresh</Button>
        {snapshot?.can_export && <Button disabled={busy} onClick={() => void exportExcel()}>Export Excel</Button>}
        {view === 'projects' && state.role === 'POD Captain' && canPerform(state.role, 'REQUESTS', 'canCreate', data.authorization) && <Button variant="primary" onClick={() => dispatch({ type: 'open-modal', modal: { id: 'create-request', title: 'Create staffing request' } })}>＋ New request</Button>}</>} />
    {(error || loadError) && <p role="alert">{error || loadError}</p>}
    {!snapshot && !loadError && <p role="status">Loading assignments…</p>}
    {snapshot && view !== 'projects' && <Card padded>
      {view === 'reports' && <p>Pending review: {snapshot.summary.pending_review} · Approved proposals: {snapshot.summary.approved} · Rejected proposals: {snapshot.summary.rejected}</p>}
      <label>Week containing <input type="date" value={week || snapshot.week_start} onChange={e => setWeek(e.target.value)} /></label>
      <p>{snapshot.week_start} – {snapshot.week_end} · {snapshot.timezone}. Pending proposals reserve no capacity.</p>
      <div className="staffing-table-wrap"><table><thead><tr><th>Person</th><th>Weekly allocation</th><th>Available hours</th><th>Committed hours</th><th>Active PODs today</th></tr></thead><tbody>
        {snapshot.people.map(p => <tr key={p.person_id}><td>{data.people.find(x => x.id === p.person_id)?.name || p.person_id}</td>
          <td>{p.capacity_status === 'CURRENT' ? p.allocation_pct === null ? 'No available hours' : `${p.allocation_pct}%` : 'Needs refresh'}</td>
          <td>{p.weeks?.[0]?.available_hours ?? '—'}</td><td>{p.weeks?.[0]?.committed_hours ?? '—'}</td><td>{p.active_pods}</td></tr>)}
      </tbody></table></div>
      {view === 'calendar' && <div className="staffing-table-wrap"><table><thead><tr><th>Date</th><th>Person</th><th>Request</th><th>Assigned hours</th></tr></thead><tbody>
        {snapshot.days.map(d => <tr key={`${d.assignment_id}:${d.work_date}`}><td>{d.work_date.slice(0, 10)}</td><td>{data.people.find(p => p.id === d.person_id)?.name || d.person_id}</td><td>{d.request_id}</td><td>{d.assigned_hours}</td></tr>)}
      </tbody></table>{!snapshot.days.length && <p>No confirmed work in this week.</p>}</div>}
    </Card>}
    {snapshot && view !== 'calendar' && snapshot.requests.map(request => {
      const members = snapshot.assignments.filter(a => a.request_id === request.request_id);
      const isLead = members.some(a => a.person_id === data.identity?.personId && a.role_in_pod === 'POD_LEAD' && a.status === 'CONFIRMED');
      return <Card key={request.request_id}><CardHeader><div><h3>{request.title}</h3><p>{request.request_id} · {request.status.replaceAll('_', ' ')}</p></div>
        {view === 'projects' && state.role === 'POD Captain' && <Button onClick={() => { dispatch({ type: 'set-active-request', requestId: request.request_id }); dispatch({ type: 'set-screen', screen: 'fitment' }); }}>Review fitment</Button>}
        {state.role === 'POD Lead' && request.status === 'STAFFED' && isLead && canPerform('POD Lead', 'REQUESTS', 'canUpdate', data.authorization) && <Button disabled={busy} onClick={() => { setClosing(request.request_id); setReason(''); }}>Close project</Button>}
      </CardHeader><CardBody>
        {request.past_planned_end && <p className="staffing-fit-summary-note">{OVERDUE_EXPLANATION}</p>}
        {request.status === 'CLOSED' && <p className="staffing-fit-summary-note">{CLOSED_EXPLANATION}</p>}
        {members.length ? <div className="staffing-table-wrap"><table><thead><tr><th>Person</th><th>POD role</th><th>Planned hours</th><th>Dates</th><th>Responsibilities</th><th>Status</th></tr></thead><tbody>
          {members.map(m => <tr key={m.assignment_id}><td>{m.full_name}</td><td>{m.role_in_pod === 'POD_LEAD' ? 'POD Lead' : 'POD Member'}</td><td>{m.assigned_hours ?? '—'}</td><td>{m.starts_on && m.ends_on ? `${m.starts_on.slice(0, 10)} – ${m.ends_on.slice(0, 10)}` : '—'}</td><td>{m.responsibilities}</td><td>{m.status}</td></tr>)}
        </tbody></table></div> : <p>No final assignment yet.</p>}
        {closing === request.request_id && request.status === 'STAFFED' && <div style={{ marginTop: 20 }}><p>{CLOSURE_EXPLANATION}</p><small>Dates follow the assignment’s staffing-policy timezone. This does not record actual hours worked.</small>
          <label>Closure note<textarea value={reason} maxLength={2000} disabled={busy} onChange={e => setReason(e.target.value)} style={{ display: 'block', width: '100%', minHeight: 90 }} /></label>
          <div className="staffing-toolbar"><Button variant="primary" disabled={busy || !reason.trim()} onClick={() => void closeProject()}>Confirm closure</Button><Button disabled={busy} onClick={() => setClosing(null)}>Cancel</Button></div></div>}
      </CardBody></Card>;
    })}
    {snapshot && !snapshot.requests.length && view === 'projects' && <p>No projects are assigned in your access scope.</p>}
  </section>;
}
