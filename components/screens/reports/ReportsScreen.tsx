'use client';

import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { KpiCard } from '@/components/ui/KpiCard';
import { PageHeader } from '@/components/ui/PageHeader';
import { Pill } from '@/components/ui/Pill';
import { ProgressBar } from '@/components/ui/ProgressBar';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { canPerform } from '@/lib/role-policy';
import { allocationTone } from '@/lib/formatting';
import { selectDashboardMetrics, selectVisiblePeople, selectVisibleRequests } from '@/lib/selectors';

const CHART_COLORS = ['#c74634', '#2b6f6d', '#315d84', '#b87b2c', '#66508c', '#8d5b00'];

export function ReportsScreen() {
  const { data, state } = useStaffingApp();
  const requests = selectVisibleRequests(data, state.role);
  const people = selectVisiblePeople(data, state.role);
  const metrics = selectDashboardMetrics(data, state.role);
  const projectCounts = data.catalog.projects.map((project) => ({ name: project.name, count: requests.filter((request) => request.projectType.id === project.id).length })).filter((item) => item.count > 0);
  const total = projectCounts.reduce((sum, item) => sum + item.count, 0) || 1;
  let cursor = 0;
  const gradient = projectCounts.map((item, index) => { const start = cursor; cursor += item.count / total * 100; return `${CHART_COLORS[index % CHART_COLORS.length]} ${start}% ${cursor}%`; }).join(', ');
  const recommendations = requests.flatMap((request) => request.recommendations);
  const pending = recommendations.filter((item) => /pending/i.test(item.decisionStatus)).length;
  const approved = recommendations.filter((item) => /approve|accept/i.test(item.decisionStatus)).length;
  const other = Math.max(0, recommendations.length - pending - approved);

  return <section className="staffing-screen"><PageHeader title="Staffing reports" description="Current database-backed demand, allocation, catalogue, and recommendation evidence." actions={<><Pill tone="teal">Database</Pill>{canPerform(state.role, 'REPORTS', 'canExport', data.authorization) ? <Button onClick={() => window.print()}>Print / PDF</Button> : null}</>} /><div className="staffing-grid staffing-kpi-grid"><KpiCard label="Open requests" value={metrics.openRequests} badge={`${metrics.highPriorityRequests} high priority`} tone="red" /><KpiCard label="Team allocation" value={`${metrics.averageAllocationPct}%`} badge={`${metrics.constrainedPeople} constrained`} tone="amber" /><KpiCard label="Staffing progress" value={`${metrics.staffingProgressPct}%`} badge={`${metrics.staffedRequests} staffed`} tone="teal" /><KpiCard label="Pending recommendations" value={metrics.pendingRecommendations} badge="Advisory" tone="purple" /></div><div className="staffing-grid staffing-kpi-grid"><KpiCard label="Customer project types" value={data.metrics.projectTypes} badge="Catalogue" tone="blue" /><KpiCard label="Mapped deliverables" value={data.metrics.deliverables} badge="Database" tone="teal" /><KpiCard label="Customer capabilities" value={data.metrics.skills} badge="Controlled" tone="purple" /><KpiCard label="People profiles" value={data.metrics.people} badge="Evidence" tone="green" /></div><div className="staffing-report-grid"><Card><CardHeader><div><h3>Demand by project type</h3><p>Current staffing requests in the database</p></div></CardHeader><CardBody><div className="staffing-donut-wrap"><div className="staffing-donut" style={{ background: gradient ? `conic-gradient(${gradient})` : '#ece8e1' }} /><div className="staffing-legend-list">{projectCounts.map((item, index) => <div key={item.name}><span><i style={{ background: CHART_COLORS[index % CHART_COLORS.length] }} />{item.name}</span><b>{Math.round(item.count / total * 100)}%</b></div>)}</div></div></CardBody></Card><Card><CardHeader><div><h3>Current team allocation</h3><p>{people.length} people in the current access scope</p></div></CardHeader><CardBody><div className="staffing-bar-chart">{people.map((person) => <div className="staffing-bar-wrap" key={person.id}><b>{person.allocationPct}%</b><i style={{ height: `${Math.max(5, person.allocationPct)}%` }} /><small>{person.initials}</small></div>)}</div></CardBody></Card><Card><CardHeader><div><h3>Recommendation outcomes</h3><p>Current decision status in the database</p></div></CardHeader><CardBody><Outcome label="Pending review" value={pending} total={recommendations.length} tone="amber" /><Outcome label="Approved" value={approved} total={recommendations.length} tone="teal" /><Outcome label="Other" value={other} total={recommendations.length} tone="blue" /></CardBody></Card><Card><CardHeader><div><h3>Leadership callouts</h3><p>Direct observations from current database data</p></div></CardHeader><CardBody><div className="staffing-callout"><b>{metrics.constrainedPeople} people require capacity attention</b><p>Allocation at or above 70% should be reviewed before confirming new work.</p></div><div className="staffing-callout"><b>{metrics.pendingRecommendations} recommendations await a person</b><p>Recommendations remain advisory until the human approval checkpoint.</p></div>{people.slice().sort((a, b) => b.allocationPct - a.allocationPct).slice(0, 3).map((person) => <div className="staffing-callout compact" key={person.id}><span>{person.name}</span><span>{person.allocationPct}%</span><ProgressBar value={person.allocationPct} tone={allocationTone(person.allocationPct)} /></div>)}</CardBody></Card></div></section>;
}

function Outcome({ label, value, total, tone }: { label: string; value: number; total: number; tone: 'amber' | 'teal' | 'blue' }) { const pct = total ? Math.round(value / total * 100) : 0; return <div className="staffing-outcome"><span>{label}</span><b>{value}</b><ProgressBar value={pct} tone={tone} /></div>; }
