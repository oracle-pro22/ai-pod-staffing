import type { LiveWorkspace } from '@/types/assignments';
import { liveStatusLabel } from '@/lib/live-presentation';

export function reportNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '' || typeof value === 'boolean') return null;
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 ? number : null;
}

export function capacityRows(snapshot: LiveWorkspace) {
  const limit = reportNumber(snapshot.maximum_allocation_pct);
  return snapshot.people.map(person => {
    const week = person.weeks?.[0];
    const available = reportNumber(week?.available_hours), committed = reportNumber(week?.committed_hours);
    const known = person.capacity_status === 'CURRENT' && available !== null && committed !== null;
    const allocation = known && available > 0 ? committed / available * 100 : null;
    const headroom = known && limit !== null ? Math.max(0, available * limit / 100 - committed) : null;
    const over = known && limit !== null && committed > available * limit / 100 + 0.0000001;
    const at = known && limit !== null && !over && available > 0 && Math.abs(committed - available * limit / 100) < 0.0000001;
    return { ...person, name: person.full_name || person.person_id, available: known ? available : null,
      committed: known ? committed : null, known, allocation, headroom, over,
      status: !known ? 'Needs refresh' : available === 0 && !over ? 'No working capacity' : over ? 'Above limit' : at ? 'At limit' : 'Within limit' };
  }).sort((a, b) => a.name.localeCompare(b.name));
}

export function reportMetrics(snapshot: LiveWorkspace) {
  const people = capacityRows(snapshot), known = people.filter(p => p.known);
  const available = known.reduce((sum, p) => sum + p.available!, 0);
  const committed = known.reduce((sum, p) => sum + p.committed!, 0);
  return { people, known: known.length, unknown: people.length - known.length, available, committed,
    utilization: available > 0 ? committed / available * 100 : null,
    headroom: known.length && reportNumber(snapshot.maximum_allocation_pct) !== null ? known.reduce((sum, p) => sum + (p.headroom ?? 0), 0) : null,
    aboveLimit: people.filter(p => p.over).length,
    staffed: snapshot.requests.filter(r => r.status === 'STAFFED').length,
    awaiting: snapshot.requests.filter(r => ['NEEDS_RECOMMENDATION', 'IN_REVIEW'].includes(r.status)).length,
    closed: snapshot.requests.filter(r => r.status === 'CLOSED').length,
    overdue: snapshot.requests.filter(r => r.status === 'STAFFED' && r.past_planned_end).length };
}

export const displayReportNumber = (value: number | null, suffix = '') => value === null ? '—' : `${Number(value.toFixed(2))}${suffix}`;
export type ReportExportKind = 'summary' | 'capacity' | 'requests' | 'assignments';

export function reportExport(snapshot: LiveWorkspace, kind: ReportExportKind) {
  const metrics = reportMetrics(snapshot);
  const context = [snapshot.week_start.slice(0,10), snapshot.week_end.slice(0,10), snapshot.timezone, snapshot.as_of?.slice(0,10) ?? '', snapshot.request_scope ?? 'Authorized requests'];
  const contextHeaders = ['Week start', 'Week end', 'Timezone', 'Status as of', 'Request scope'];
  let headers: string[], rows: (string | number | null)[][];
  if (kind === 'summary') {
    headers = [...contextHeaders, 'Metric', 'Value', 'Definition'];
    rows = [
      ['Staffed projects', metrics.staffed, 'Currently staffed requests in request scope; not filtered by selected week'],
      ['Awaiting staffing', metrics.awaiting, 'Currently unstaffed requests in request scope'],
      ['Ready for Captain review', snapshot.summary.pending_review, 'Current-revision proposals using the current policy'],
      ['Closed projects', metrics.closed, 'Current closed request count'],
      ['Past planned end', metrics.overdue, 'Staffed projects past their planned end date'],
      ['Weekly utilization (%)', metrics.utilization, 'Sum of known commitments / sum of known available hours x 100'],
      ['Available hours', metrics.available, 'Known working capacity after leave'],
      ['Committed hours', metrics.committed, 'Known counted assignments plus external work; includes retained closed history'],
      ['Weekly headroom (hours)', metrics.headroom, 'Sum of positive per-person headroom to the limit; daily feasibility still applies'],
      ['Maximum utilization (%)', reportNumber(snapshot.maximum_allocation_pct), 'Current Administrator setting'],
      ['People with known capacity', metrics.known, 'Profiles with complete selected-week capacity'],
      ['People needing refresh', metrics.unknown, 'Excluded from capacity calculations, not treated as zero'],
    ].map(row => [...context, ...row] as (string | number | null)[]);
  } else if (kind === 'capacity') {
    headers = [...contextHeaders, 'Person ID', 'Name', 'Weekly allocation (%)', 'Available hours', 'Committed hours', 'Weekly headroom (hours)', 'Maximum utilization (%)', 'Active PODs as of status date', 'Capacity status'];
    rows = metrics.people.map(p => [...context, p.person_id, p.name, p.allocation, p.available, p.committed, p.headroom,
      reportNumber(snapshot.maximum_allocation_pct), p.active_pods, p.status]);
  } else if (kind === 'requests') {
    headers = [...contextHeaders, 'Request ID', 'Title', 'Current status', 'Planned end', 'Past planned end', 'Assigned people'];
    rows = snapshot.requests.map(r => [...context, r.request_id, r.title, liveStatusLabel(r.status), r.planned_end_on?.slice(0,10) ?? '',
      r.past_planned_end ? 'Yes' : 'No', new Set(snapshot.assignments.filter(a => a.request_id === r.request_id).map(a => a.person_id)).size]);
  } else {
    headers = [...contextHeaders, 'Date', 'Request ID', 'Assignment ID', 'Person ID', 'Name', 'POD role', 'Counted planned hours', 'Assignment status'];
    rows = snapshot.days.map(d => {
      const assignment = snapshot.assignments.find(a => a.assignment_id === d.assignment_id);
      return [...context, d.work_date.slice(0,10), d.request_id, d.assignment_id, d.person_id, assignment?.full_name || d.person_id,
        assignment?.role_in_pod === 'POD_LEAD' ? 'POD Lead' : 'POD Member', d.assigned_hours, assignment?.status ?? ''];
    });
  }
  return { fileName: `staffing-${kind}-${snapshot.week_start.slice(0,10)}.xlsx`, sheetName: kind[0].toUpperCase()+kind.slice(1), headers, rows };
}
