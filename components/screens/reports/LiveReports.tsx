'use client';

import { useState } from 'react';
import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { KpiCard } from '@/components/ui/KpiCard';
import { PageHeader } from '@/components/ui/PageHeader';
import { Pill } from '@/components/ui/Pill';
import { ProgressBar } from '@/components/ui/ProgressBar';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { formatDate, statusTone } from '@/lib/formatting';
import { liveStatusLabel } from '@/lib/live-presentation';
import { useLiveWorkspace } from '@/lib/use-live-workspace';
import { staffingFetch } from '@/lib/staffing-fetch';
import { displayReportNumber as number, reportMetrics, reportExport, type ReportExportKind } from '@/lib/reports-model';
import type { LiveWorkspace } from '@/types/assignments';

const TABS = ['Overview', 'Capacity', 'Requests', 'Excel export'] as const;
const EXPORTS: { id: ReportExportKind; title: string; description: string }[] = [
  { id: 'summary', title: 'KPI summary', description: 'Headline metrics, reporting scope, and calculation definitions.' },
  { id: 'capacity', title: 'People & capacity', description: 'Weekly hours, utilization, headroom, and active POD counts.' },
  { id: 'requests', title: 'Request register', description: 'Current request status, planned end dates, and assigned team size.' },
  { id: 'assignments', title: 'Weekly assignment detail', description: 'Counted project hours by person and day, including retained closed-project history.' },
];

export function LiveReports() {
  const { dispatch } = useStaffingApp();
  const [tab, setTab] = useState<typeof TABS[number]>('Overview');
  const [week, setWeek] = useState('');
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('ALL');
  const [exporting, setExporting] = useState<ReportExportKind | null>(null);
  const [exportError, setExportError] = useState('');
  const [exportSuccess, setExportSuccess] = useState('');
  const { snapshot, error, refresh } = useLiveWorkspace('REPORTS', week);
  const metrics = snapshot ? reportMetrics(snapshot) : null;
  const period = snapshot ? `${formatDate(snapshot.week_start)} – ${formatDate(snapshot.week_end)}` : 'Loading reporting week';

  function selectTab(value: typeof TABS[number]) { setTab(value); setSearch(''); setStatus('ALL'); }
  function changeWeek(days: number) {
    if (!snapshot) return;
    const value = new Date(`${snapshot.week_start.slice(0,10)}T12:00:00Z`);
    value.setUTCDate(value.getUTCDate()+days); setWeek(value.toISOString().slice(0,10));
  }
  async function exportReport(kind: ReportExportKind) {
    if (!snapshot?.can_export || exporting) return;
    setExporting(kind); setExportError(''); setExportSuccess('');
    try {
      // Fetch again so permission changes and selected-week data are checked on the server.
      const response = await staffingFetch(`/api/agentic/reports/export?week=${snapshot.week_start.slice(0,10)}`, { cache: 'no-store' });
      const payload = await response.json();
      if (!response.ok) throw new Error(typeof payload.error === 'string' ? payload.error : payload.error?.message || 'Unable to export report.');
      const fresh = payload.data as LiveWorkspace;
      if (!fresh.can_export) throw new Error('Your profile does not have report export permission.');
      const { downloadExcelWorkbook } = await import('@/lib/export-xlsx');
      await downloadExcelWorkbook(reportExport(fresh, kind));
      setExportSuccess(`${EXPORTS.find(item => item.id === kind)?.title} downloaded for ${formatDate(fresh.week_start)}.`);
    } catch (e) { setExportError(e instanceof Error ? e.message : 'Unable to download report.'); }
    finally { setExporting(null); }
  }
  const openRequest = (requestId: string) => dispatch({ type: 'open-drawer', drawer: { id: 'request-details', title: 'Request details', payload: { requestId } } });

  return <section className="staffing-screen staffing-reports">
    <PageHeader title="Staffing reports" description="A clear view of staffing demand, team capacity, and delivery progress." actions={<>
      <Button disabled={Boolean(exporting)} onClick={refresh}>Refresh</Button>
      <Button variant="primary" disabled={!snapshot?.can_export} onClick={() => selectTab('Excel export')}>Export to Excel</Button>
    </>} />
    <Card className="staffing-report-controls"><div><span className="staffing-report-eyebrow">Capacity reporting week</span><h3>{period}</h3>
      {snapshot && <p>{snapshot.timezone} · Request and POD status as of {formatDate(snapshot.as_of || snapshot.week_start)}</p>}</div>
      <div className="staffing-inline-actions"><Button aria-label="Previous reporting week" disabled={!snapshot || Boolean(exporting)} onClick={() => changeWeek(-7)}>←</Button>
        <label className="staffing-report-date"><span>Week containing</span><input className="staffing-field" aria-label="Week containing" type="date" value={week || snapshot?.week_start.slice(0,10) || ''} disabled={Boolean(exporting)} onChange={e => setWeek(e.target.value)} /></label>
        <Button aria-label="Next reporting week" disabled={!snapshot || Boolean(exporting)} onClick={() => changeWeek(7)}>→</Button>
        <Button disabled={Boolean(exporting)} onClick={() => setWeek('')}>This week</Button></div>
    </Card>
    {error && <Card padded><p role="alert">{error}</p><Button onClick={refresh}>Try again</Button></Card>}
    {!snapshot && !error && <Card padded><p role="status">Loading staffing reports…</p></Card>}
    {snapshot && metrics && <>
      <div className="staffing-grid staffing-kpi-grid">
        <KpiCard label="Staffed projects" value={metrics.staffed} badge={`${metrics.closed} closed`} tone="teal" detail={`${snapshot.request_scope || 'Visible requests'} · current status`} />
        <KpiCard label="Awaiting staffing" value={metrics.awaiting} badge={`${snapshot.summary.pending_review} ready for review`} tone="purple" detail="Requests not yet assigned a final POD" />
        <KpiCard label="Weekly utilization" value={number(metrics.utilization, '%')} badge={metrics.unknown ? `${metrics.unknown} need refresh` : `${metrics.known} people`} tone={metrics.unknown ? 'amber' : 'blue'} detail={`${number(metrics.committed)}h committed / ${number(metrics.available)}h available${metrics.unknown ? ' · known data only' : ''}`} />
        <KpiCard label={`Headroom to ${snapshot.maximum_allocation_pct ?? '—'}%`} value={number(metrics.headroom, 'h')} badge={`${metrics.aboveLimit} above limit`} tone={metrics.aboveLimit ? 'red' : 'green'} detail={`Weekly capacity below the limit${metrics.unknown ? ' · known data only' : ''}`} />
      </div>
      <div className="staffing-report-tabs" aria-label="Report views">{TABS.map(item => <button key={item} type="button" aria-pressed={tab === item} className={tab === item ? 'active' : ''} onClick={() => selectTab(item)}>{item}</button>)}</div>
      <div className="staffing-report-scope"><span>{snapshot.request_scope || 'Authorized requests'} · {snapshot.requests.length} total</span><span>Capacity: {snapshot.people.length} visible people · Planned hours, not timesheets</span></div>

      {tab === 'Overview' && <div className="staffing-grid staffing-two-col">
        <Card><CardHeader><div><h3>Staffing pipeline</h3><p>Current status of requests in your access scope</p></div><Pill tone="teal">{snapshot.requests.length} requests</Pill></CardHeader><CardBody>
          {!snapshot.requests.length ? <div className="staffing-empty compact">No requests in your access scope.</div> : [
            { label: 'Awaiting staffing', count: metrics.awaiting, tone: 'purple' as const },
            { label: 'Staffed', count: metrics.staffed, tone: 'teal' as const },
            { label: 'Closed', count: metrics.closed, tone: 'green' as const },
          ].map(item => <div className="staffing-report-pipeline" key={item.label}><div><span>{item.label}</span><strong>{item.count}</strong></div><ProgressBar value={item.count / snapshot.requests.length * 100} tone={item.tone} /></div>)}
          <div className="staffing-report-callouts"><div><b>{snapshot.summary.approved}</b><span>Approved proposals</span></div><div><b>{snapshot.summary.rejected}</b><span>Rejected proposals</span></div><div><b>{metrics.overdue}</b><span>Past planned end</span></div></div>
          <p className="staffing-muted">Proposal outcomes are historical totals for these requests; repeated runs are not additional projects.</p>
        </CardBody></Card>
        <Card><CardHeader><div><h3>Capacity watch</h3><p>Highest utilization in the selected week</p></div><Button size="small" onClick={() => selectTab('Capacity')}>View all</Button></CardHeader><CardBody>
          {[...metrics.people].sort((a,b) => (b.allocation ?? -1)-(a.allocation ?? -1)).slice(0,5).map(person => <div className="staffing-capacity-row" key={person.person_id}>
            <Avatar initials={person.name.split(' ').map(part => part[0]).slice(0,2).join('')} />
            <div><div className="staffing-cap-name"><b>{person.name}</b><span>{number(person.allocation,'%')}</span></div><ProgressBar value={person.allocation ?? 0} tone={person.over ? 'red' : person.headroom === 0 ? 'amber' : 'teal'} /></div>
            <Pill tone={person.over ? 'red' : 'teal'}>{person.status}</Pill>
          </div>)}
          {!metrics.people.length && <div className="staffing-empty compact">No people in your access scope.</div>}
          <p className="staffing-muted">Weekly headroom is not a staffing guarantee. The agent also checks daily availability, skills, and project dates.</p>
        </CardBody></Card>
      </div>}

      {tab === 'Capacity' && <Card><CardHeader><div><h3>People & capacity</h3><p>Confirmed project work and other commitments, after leave</p></div><input className="staffing-field staffing-report-search" aria-label="Search capacity by name" placeholder="Search people by name" value={search} onChange={e => setSearch(e.target.value)} /></CardHeader>
        <div className="staffing-report-table-wrap"><table className="staffing-report-table"><thead><tr><th>Person</th><th>Weekly allocation</th><th>Available</th><th>Committed</th><th>Headroom</th><th>Active PODs today</th><th>Capacity</th></tr></thead><tbody>
          {metrics.people.filter(p => p.name.toLowerCase().includes(search.trim().toLowerCase())).map(p => <tr key={p.person_id}><td><b>{p.name}</b><small>{p.person_id}</small></td><td><strong>{number(p.allocation,'%')}</strong><ProgressBar value={p.allocation ?? 0} tone={p.over ? 'red' : 'teal'} /></td><td>{number(p.available,'h')}</td><td>{number(p.committed,'h')}</td><td>{number(p.headroom,'h')}</td><td>{p.active_pods}</td><td><Pill tone={p.over ? 'red' : !p.known || p.headroom === 0 ? 'amber' : 'teal'}>{p.status}</Pill></td></tr>)}
          {!metrics.people.some(p => p.name.toLowerCase().includes(search.trim().toLowerCase())) && <tr><td colSpan={7}>No matching people.</td></tr>}
        </tbody></table></div>
        <CardBody><p className="staffing-muted">Unknown capacity stays blank and is excluded from totals. Active POD counts are for today, not the selected historical week.</p></CardBody>
      </Card>}

      {tab === 'Requests' && <Card><CardHeader><div><h3>Request register</h3><p>{snapshot.request_scope || 'Authorized requests'} · current status, independent of the capacity week</p></div><div className="staffing-inline-actions">
        <input className="staffing-field staffing-report-search" aria-label="Search requests" placeholder="Search title or request ID" value={search} onChange={e => setSearch(e.target.value)} />
        <select className="staffing-select" aria-label="Filter request status" value={status} onChange={e => setStatus(e.target.value)}><option value="ALL">All statuses</option>{[...new Set(snapshot.requests.map(r => r.status))].map(value => <option key={value} value={value}>{liveStatusLabel(value)}</option>)}</select></div></CardHeader>
        <div className="staffing-report-table-wrap"><table className="staffing-report-table"><thead><tr><th>Request</th><th>Status</th><th>POD team</th><th>Planned end</th><th>Delivery check</th><th><span className="staffing-muted">Details</span></th></tr></thead><tbody>
          {snapshot.requests.filter(r => (status === 'ALL' || r.status === status) && `${r.request_id} ${r.title}`.toLowerCase().includes(search.trim().toLowerCase())).map(r => <tr key={r.request_id}>
            <td><b>{r.title}</b><small>{r.request_id}</small></td><td><Pill tone={statusTone(liveStatusLabel(r.status))}>{liveStatusLabel(r.status)}</Pill></td>
            <td>{new Set(snapshot.assignments.filter(a => a.request_id === r.request_id).map(a => a.person_id)).size || '—'}</td><td>{r.planned_end_on ? formatDate(r.planned_end_on.slice(0,10)) : '—'}</td><td>{r.past_planned_end ? <Pill tone="amber">Past planned end</Pill> : '—'}</td><td><Button size="small" onClick={() => openRequest(r.request_id)}>Open</Button></td></tr>)}
          {!snapshot.requests.some(r => (status === 'ALL' || r.status === status) && `${r.request_id} ${r.title}`.toLowerCase().includes(search.trim().toLowerCase())) && <tr><td colSpan={6}>No matching requests.</td></tr>}
        </tbody></table></div>
      </Card>}

      {tab === 'Excel export' && <>
        <div className="staffing-report-export-intro"><h3>Download an Excel report</h3><p>Fresh, permission-checked data for {period}. Downloads include all rows in your access scope, not just search results.</p>
          {!snapshot.can_export && <p role="status">Your profile does not currently have Reports export permission.</p>}
          {exportError && <p role="alert">{exportError}</p>}{exportSuccess && <p role="status">{exportSuccess}</p>}</div>
        <div className="staffing-grid staffing-two-col">{EXPORTS.map(item => <Card padded className="staffing-report-export-card" key={item.id}><Pill tone="green">.xlsx</Pill><h3>{item.title}</h3><p>{item.description}</p><Button variant="primary" disabled={!snapshot.can_export || Boolean(exporting)} onClick={() => void exportReport(item.id)}>{exporting === item.id ? 'Preparing…' : 'Download Excel'}</Button></Card>)}</div>
      </>}
    </>}
  </section>;
}
