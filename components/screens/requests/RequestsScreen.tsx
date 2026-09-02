'use client';

import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { PageHeader } from '@/components/ui/PageHeader';
import { Pill } from '@/components/ui/Pill';
import { SelectField, TextField } from '@/components/ui/FormControls';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { formatDate, statusTone, unique } from '@/lib/formatting';
import { selectVisibleRequests } from '@/lib/selectors';

export function RequestsScreen() {
  const { data, state, dispatch, notify } = useStaffingApp();
  const requests = selectVisibleRequests(data, state.role);
  const filters = state.requestFilters;
  const isMember = state.role === 'POD Member';
  const canCreateRequest = data.authorization.roles
    .find((role) => role.name === state.role && role.active)
    ?.permissions.find((permission) => permission.resourceCode === 'REQUESTS')?.canCreate ?? false;
  const statuses = unique(requests.map((request) => request.status).concat('Closed'));
  const priorities = unique(requests.map((request) => request.priority));
  const filtered = requests.filter((request) => {
    const query = filters.search.toLowerCase();
    return (!query || [request.id, request.title, request.projectType.name, ...request.deliverables.map((item) => item.name), ...request.requiredSkills.map((item) => item.name)].join(' ').toLowerCase().includes(query))
      && (!filters.status || request.status === filters.status)
      && (!filters.priority || request.priority === filters.priority)
      && (!filters.projectTypeId || request.projectType.id === filters.projectTypeId)
      && (!filters.deliverableId || request.deliverables.some((item) => item.id === filters.deliverableId));
  });

  function exportCsv() {
    const headers = ['ID', 'Title', 'Project Type', 'Deliverables', 'Required Capabilities', 'Request Source', 'Status', 'Priority', 'Needed By'];
    const rows = filtered.map((request) => [request.id, request.title, request.projectType.name, request.deliverables.map((item) => item.name).join('; '), request.requiredSkills.map((item) => item.name).join('; '), request.requestSource, request.status, request.priority, request.neededBy]);
    const csv = [headers, ...rows].map((row) => row.map((value) => `"${String(value).replace(/"/g, '""')}"`).join(',')).join('\n');
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
    link.download = 'ai-pod-staffing-requests.csv';
    link.click();
    URL.revokeObjectURL(link.href);
    notify('Export created', `${rows.length} scoped request${rows.length === 1 ? '' : 's'} exported.`);
  }

  return (
    <section className="staffing-screen">
      <PageHeader title="Staffing requests" description="Customer project types, key deliverables, and required capabilities from the staffing catalogue." actions={<><SelectField value={filters.status} onChange={(event) => dispatch({ type: 'set-request-filter', key: 'status', value: event.target.value })}><option value="">All status</option>{statuses.map((status) => <option key={status}>{status}</option>)}</SelectField>{canCreateRequest ? <Button variant="primary" onClick={() => dispatch({ type: 'open-modal', modal: { id: 'create-request', title: 'Create staffing request' } })}>＋ New request</Button> : null}</>} />
      <Card>
        <div className="staffing-card-head staffing-request-toolbar">
          <div className="staffing-toolbar">
            <TextField value={filters.search} onChange={(event) => dispatch({ type: 'set-request-filter', key: 'search', value: event.target.value })} placeholder="Search requests, deliverables, or capabilities" />
            <SelectField value={filters.priority} onChange={(event) => dispatch({ type: 'set-request-filter', key: 'priority', value: event.target.value })}><option value="">All priorities</option>{priorities.map((value) => <option key={value}>{value}</option>)}</SelectField>
            <SelectField value={filters.projectTypeId} onChange={(event) => dispatch({ type: 'set-request-filter', key: 'projectTypeId', value: event.target.value })}><option value="">All project types</option>{data.catalog.projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</SelectField>
            <SelectField value={filters.deliverableId} onChange={(event) => dispatch({ type: 'set-request-filter', key: 'deliverableId', value: event.target.value })}><option value="">All deliverables</option>{data.catalog.projects.flatMap((project) => project.deliverables).map((deliverable) => <option key={deliverable.id} value={deliverable.id}>{deliverable.name}</option>)}</SelectField>
          </div>
          {!isMember ? <Button size="small" onClick={exportCsv}>Export CSV</Button> : null}
        </div>
        <div className="staffing-table-wrap"><table className="staffing-request-table"><thead><tr><th>Request</th><th>Project type</th><th>Key deliverables / required capabilities</th><th>Request source</th><th>Status</th><th>Needed by date</th><th /></tr></thead><tbody>{filtered.map((request) => <tr key={request.id}><td><b>{request.title}</b><small>{request.id} • {request.estimatedHours} hours</small></td><td>{request.projectType.name}</td><td><b>{request.deliverables.map((item) => item.name).join(', ')}</b><div className="staffing-tag-row">{request.requiredSkills.map((skill) => <span key={skill.id}>{skill.name}</span>)}</div></td><td>{request.requestSource}</td><td><Pill tone={statusTone(request.status)}>{request.status}</Pill></td><td>{formatDate(request.neededBy)}</td><td><Button size="small" onClick={() => dispatch({ type: 'open-drawer', drawer: { id: 'request-details', title: request.title, payload: { requestId: request.id } } })}>Open</Button></td></tr>)}</tbody></table>{filtered.length === 0 ? <div className="staffing-empty">No requests match the selected filters.</div> : null}</div>
      </Card>
    </section>
  );
}
