'use client';

import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { FormGroup, SelectField, TextArea } from '@/components/ui/FormControls';
import { Modal } from '@/components/ui/Modal';
import { PageHeader } from '@/components/ui/PageHeader';
import { Pill } from '@/components/ui/Pill';
import { ProgressBar } from '@/components/ui/ProgressBar';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { formatDate, requestEffortLabel, personAllocationLabel } from '@/lib/formatting';
import { allocationMetric, executionProgress, liveStatusLabel, savedFactorValue } from '@/lib/live-presentation';
import type { StaffingRequest } from '@/types/staffing';
import type { Tone } from '@/types/ui';
import type { Execution, Member, Pod, RequestRow } from './LiveStaffingReview';

const STAGES = [
  ['Validate request', 'Load project details and key deliverables'],
  ['Resolve required capabilities', 'Read mapped and request-specific capabilities'],
  ['Retrieve people', 'Load skills, strength, and evidence'],
  ['Apply availability', 'Check travel, commitments, and allocation'],
  ['Rank and explain', 'Compare validated teams and supporting evidence'],
  ['Ready for Captain review', 'Review the proposed POD before final assignment'],
];

type Props = {
  executionView: boolean; request?: RequestRow; requests: RequestRow[]; execution: Execution | null; proposal: Pod | null;
  loading: boolean; busy: boolean; running: boolean; error: string; canRun: boolean; canDecide: boolean;
  decision: 'APPROVED' | 'REJECTED' | null; reason: string;
  onRun: () => void; onRefresh: () => void; onSelect: (id: string) => void; onReason: (value: string) => void;
  onDecision: (action: 'APPROVED' | 'REJECTED') => void; onSaveDecision: () => void; onCancelDecision: () => void;
};

export function LiveFitmentPresentation(p: Props) {
  const { data, dispatch } = useStaffingApp();
  const detail = data.requests.find(r => r.id === p.request?.request_id);
  const progress = executionProgress(p.execution?.status, p.execution?.events ?? []);
  const openDetails = () => detail && dispatch({ type: 'open-drawer', drawer: { id: 'request-details', title: detail.title, payload: { requestId: detail.id } } });
  const log = <ExecutionLog execution={p.execution} running={p.running} />;
  return <section className="staffing-screen staffing-live-review">
    <PageHeader title={p.executionView ? 'Agent execution' : 'AI fitment review'}
      description={p.executionView ? 'Inspect each evidence and guardrail step before a recommendation is presented for review.' : 'Review the proposed POD, capability match, and available capacity.'}
      actions={<div className={p.executionView ? 'staffing-execution-actions' : 'staffing-fit-review-actions'}>
        <label className="staffing-fitment-picker"><span>Staffing request</span><SelectField aria-label="Staffing request" value={p.request?.request_id ?? ''}
          disabled={p.busy || p.loading} onChange={e => p.onSelect(e.target.value)}>
          {!p.requests.length && <option value="">{p.loading ? 'Loading requests…' : 'No requests available'}</option>}
          {p.requests.map(r => <option key={r.request_id} value={r.request_id}>{r.request_id} — {r.title} • {liveStatusLabel(r.status)}</option>)}
        </SelectField></label><div className="staffing-inline-actions">
          {p.canRun && <Button variant={p.executionView ? 'primary' : undefined}
            disabled={p.busy || p.running || !p.request || ['STAFFED', 'CLOSED'].includes(p.request.status)} onClick={p.onRun}>
            {p.running ? 'Running…' : p.execution ? '↻ Re-run' : '▶ Run fitment'}</Button>}
          {!p.executionView && p.canDecide && <><Button variant="primary" disabled={p.busy} onClick={() => p.onDecision('APPROVED')}>Approve pod</Button>
            <Button disabled={p.busy} onClick={() => p.onDecision('REJECTED')}>Reject</Button></>}
          <Button size="small" disabled={p.busy} onClick={p.onRefresh}>Refresh</Button>
        </div></div>} />
    {p.error && <div className="staffing-empty compact" role="alert">{p.error}</div>}
    {p.loading && !p.request && <Card padded><p role="status">Loading requests…</p></Card>}
    {p.request && (p.executionView ? <div className="staffing-agent-shell">
      <Card padded><h3>Execution stages</h3><div className="staffing-pipeline" aria-label="Fitment execution progress">
        {STAGES.map(([title, description], i) => <div key={title}
          className={`staffing-step${i < progress ? ' done' : p.running && i === progress ? ' active' : ''}`}
          aria-current={p.running && i === progress ? 'step' : undefined}>
          <div className="staffing-step-icon">{i < progress ? '✓' : i + 1}</div>
          <div><div className="staffing-step-title">{title}</div><div className="staffing-step-desc">{description}</div></div>
        </div>)}
      </div></Card><div className="staffing-grid">{log}{p.proposal && <Card><CardHeader>
        <div><h3>Agent result</h3><p>{liveStatusLabel(p.proposal.status)} · {p.proposal.total_hours} planned hours</p></div>
        <Button size="small" onClick={() => dispatch({ type: 'set-screen', screen: 'fitment' })}>Open full review</Button>
      </CardHeader><CardBody>{p.proposal.members.map(m => <div className="staffing-agent-result" key={m.person_id}>
        <Avatar initials={initials(m.full_name)} /><div><b>{m.full_name} • {podRole(m.role_in_pod)}</b>
          <small>{m.responsibilities}</small><small>{m.planned_hours} planned hours</small></div><strong>{m.score}</strong>
      </div>)}</CardBody></Card>}</div>
    </div> : <div className="staffing-fit-layout">
      <Card padded className="staffing-request-summary"><div className="staffing-summary-head"><div>
        <Pill tone={/high|urgent/i.test(detail?.priority ?? '') ? 'red' : ''}>{detail?.priority ?? 'Request'}{detail ? ' priority' : ''}</Pill>
        <h3 className="staffing-summary-title">{p.request.title}</h3><p className="staffing-muted">{p.request.request_id} • {detail?.projectType.name}</p>
      </div><Button size="small" disabled={!detail} aria-label="Open request details" onClick={openDetails}>↗</Button></div>
      {detail && <><dl className="staffing-summary-list">
        <div><dt>Needed by date</dt><dd>{formatDate(detail.neededBy)}</dd></div>
        <div><dt>Key deliverables</dt><dd>{detail.deliverables.map(d => d.name).join(', ')}</dd></div>
        <div><dt>Estimated effort</dt><dd>{requestEffortLabel(detail)}</dd></div>
        <div><dt>Required capabilities</dt><dd><div className="staffing-tag-row">{detail.requiredSkills.map(s => <span key={s.id}>{s.name}</span>)}</div></dd></div>
        <div><dt>Status</dt><dd>{liveStatusLabel(p.request.status)}</dd></div>
      </dl><div className="staffing-fit-summary-note"><b>Business objectives</b><p>{detail.businessObjectives || detail.businessContext || 'No business objectives recorded.'}</p></div>
        <div className="staffing-fit-summary-note"><b>Expected outcomes</b><p>{detail.expectedOutcomes || 'No expected outcomes recorded.'}</p></div></>}
      {p.proposal && <div className="staffing-source-strip"><span>{formatDate(p.proposal.starts_on.slice(0, 10))} – {formatDate(p.proposal.ends_on.slice(0, 10))}</span><span>{p.proposal.policy_version}</span></div>}
      </Card><div>
        {p.proposal?.stale === 'Y' && <div className="staffing-fit-summary-note" role="alert">{p.proposal.stale_reason || 'Request changed. Run fitment again before approving.'}</div>}
        <SavedFactors proposal={p.proposal} />
        <SavedCandidates title="Recommended pod lead" subtitle="Proposed lead and supporting evidence" members={p.proposal?.members.filter(m => m.role_in_pod === 'POD_LEAD') ?? []}
          count={p.proposal?.lead_count ?? 1} request={detail} proposalStatus={p.proposal?.status} stale={p.proposal?.stale === 'Y'} />
        <SavedCandidates title="Recommended contributors" subtitle="Capability match, deliverable experience, and remaining capacity" members={p.proposal?.members.filter(m => m.role_in_pod !== 'POD_LEAD') ?? []}
          count={p.proposal?.member_count ?? Number(detail?.requestedPodSize?.match(/(\d+) contributor/)?.[1] ?? 2)} request={detail} proposalStatus={p.proposal?.status} stale={p.proposal?.stale === 'Y'} />
        {p.proposal && <Card padded className="staffing-candidate-section"><h3>Why this POD</h3><p className="staffing-muted">{p.proposal.rationale}</p></Card>}
        {(p.running || p.execution?.last_error_code) && <div className="staffing-section-gap">{log}</div>}
        <div className="staffing-source-strip"><span>{p.execution ? liveStatusLabel(p.execution.status) : 'Awaiting execution'}</span>
          <Button size="small" onClick={() => dispatch({ type: 'set-screen', screen: 'agent' })}>View execution</Button></div>
      </div>
    </div>)}
    {!p.request && !p.loading && !p.error && <Card padded><div className="staffing-empty">No requests are linked to your staffing identity.</div></Card>}
    <Modal open={Boolean(p.decision)} title={p.decision === 'REJECTED' ? 'Reject proposed pod' : 'Approve proposed pod'} onClose={p.onCancelDecision}
      footer={<><Button disabled={p.busy} onClick={p.onCancelDecision}>Cancel</Button>
        <Button variant="primary" disabled={p.busy || !p.canDecide || (p.decision === 'REJECTED' && !p.reason.trim())} onClick={p.onSaveDecision}>
          {p.busy ? 'Saving…' : p.decision === 'REJECTED' ? 'Confirm rejection' : 'Confirm final assignment'}</Button></>}>
      <div className="staffing-approval-summary"><b>{p.request?.title}</b><p>{p.proposal?.members.map(m => m.full_name).join(', ')}</p></div>
      <p>{p.decision === 'REJECTED' ? 'Your reason will be saved for the next recommendation.' : 'Approval makes these assignments final. No Lead or Member acceptance is required.'}</p>
      <FormGroup label={p.decision === 'REJECTED' ? 'Rejection reason (required)' : 'Approval note (optional)'}>
        <TextArea value={p.reason} maxLength={2000} disabled={p.busy} onChange={e => p.onReason(e.target.value)} />
      </FormGroup>
    </Modal>
  </section>;
}

function initials(name: string) { return name.split(' ').map(p => p[0]).join('').slice(0, 2); }
function podRole(role: string) { return role === 'POD_LEAD' ? 'POD Lead' : 'POD Member'; }

function ExecutionLog({ execution, running }: { execution: Execution | null; running: boolean }) {
  return <Card><CardHeader><div><h3>Execution log</h3><p>Transparent signals and exclusions</p></div>
    <Pill tone={running || execution?.status === 'FAILED' ? 'red' : execution?.status === 'READY_FOR_REVIEW' ? 'green' : ''}>
      {execution ? liveStatusLabel(execution.status) : 'Ready'}</Pill></CardHeader><CardBody>
    <div className="staffing-console staffing-live-console" aria-live="polite" aria-busy={running}>
      {execution?.events.length ? execution.events.map(e => <div key={e.event_sequence}>
        <span>[{e.stage}]</span>{' '}<b className={['FAILED', 'NEEDS_INFORMATION'].includes(e.status) ? 'warn' : 'ok'}>{e.summary}</b>
      </div>) : <div><span>[ready]</span> Select a request and run the fitment agent.</div>}
      {execution?.last_error_code && <div className="warn">{execution.last_error_summary} ({execution.last_error_code})</div>}
      {execution?.clarification_questions?.map(q => <div className="warn" key={q}>{q}</div>)}
    </div></CardBody></Card>;
}

function SavedFactors({ proposal }: { proposal: Pod | null }) {
  const labels: [string, string, Tone][] = [['skill', 'Skill strength', 'teal'], ['deliverable', 'Deliverable experience', 'blue'], ['capacity', 'Available capacity', 'teal'], ['interest', 'Interest preference', 'amber']];
  const weighted = proposal?.members.length && proposal.members.every(m => m.factors?.scheduling_algorithm === 'available-days-v2');
  return <Card padded className="staffing-fit-factors"><div className="staffing-explain-title"><span className="staffing-spark">✦</span>
    <span><b>How the recommendation was formed</b><small>{weighted ? 'Effort-weighted' : 'Average'} score contribution from the saved proposal</small></span></div>
    {proposal?.members.length ? labels.map(([code, label, tone]) => {
      const value = savedFactorValue(proposal.members, code);
      return <div className="staffing-factor" key={code}><span>{label}</span><ProgressBar value={value ?? 0} tone={tone} aria-label={label} />
        <strong>{value === null ? '—' : `${Number(value.toFixed(2))} pts`}</strong></div>;
    }) : <div className="staffing-empty compact">Recommendation evidence will appear when fitment completes.</div>}
  </Card>;
}

function SavedCandidates({ title, subtitle, members, count, request, proposalStatus, stale }: {
  title: string; subtitle: string; members: Member[]; count: number; request?: StaffingRequest; proposalStatus?: string; stale?: boolean;
}) {
  const { data } = useStaffingApp();
  return <Card className="staffing-candidate-section"><CardHeader><div><h3>{title}</h3><p>{subtitle}</p></div><Pill tone="green">{count} required</Pill></CardHeader>
    <CardBody>{members.length ? members.map(m => {
      const person = data.people.find(p => p.id === m.person_id);
      const skills = person?.skills.filter(s => request?.requiredSkills.some(r => r.id === s.id)) ?? [];
      const projected = allocationMetric(m.factors?.projected_allocation_pct);
      const scheduled = m.factors?.scheduling_algorithm === 'available-days-v2';
      const before = allocationMetric(m.factors?.current_window_allocation_pct);
      const after = allocationMetric(m.factors?.window_allocation_pct);
      return <article className="staffing-candidate recommended" key={m.person_id}>
        <div className="staffing-candidate-head"><Avatar initials={person?.initials || initials(m.full_name)} /><div className="staffing-candidate-main">
          <div className="staffing-candidate-name">{m.full_name} • {podRole(m.role_in_pod)}</div>
          <div className="staffing-candidate-meta">{scheduled && before !== null
            ? `${before} allocated in request period before this proposal${person ? ` · ${person.activePods} active pods today` : ''}`
            : person ? `${personAllocationLabel(person)} current allocation · ${person.activePods} active pods` : m.person_id}</div>
        </div><div className="staffing-score" aria-label={`Fit score ${m.score}`}>{m.score}</div></div>
        <div className="staffing-tag-row">{skills.map(s => <span key={s.id}>{s.name}</span>)}</div>
        <div className="staffing-rationale">{m.responsibilities}</div>
        <div className="staffing-candidate-foot"><span>{m.planned_hours} planned hours</span>
          {scheduled && <span>{after === null ? 'Period allocation unavailable' : `${after} projected for request period`}</span>}
          <span title={m.factors?.peak_week_start ? `Week of ${formatDate(m.factors.peak_week_start)}` : undefined}>
            {projected === null ? 'Projected capacity unavailable' : `${projected} peak weekly allocation`}</span>
          <span>{stale ? 'Re-run required' : liveStatusLabel(proposalStatus ?? 'READY_FOR_REVIEW')}</span></div>
      </article>;
    }) : <div className="staffing-empty compact">A validated recommendation will appear after fitment completes.</div>}</CardBody>
  </Card>;
}
