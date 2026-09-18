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
import type { Execution, Member, Pod, Replacement, RequestRow } from './LiveStaffingReview';

const STAGES = [
  ['Load evidence', 'Load request, catalogue, roles and dated capacity'],
  ['Supervisor', 'Delegate evidence review and validate the next step'],
  ['Request / Evidence Analyst', 'Interpret scope and genuinely missing business inputs'],
  ['POD Planner and rules', 'Compare eligible teams, exact hours and schedules'],
  ['Supervisor review', 'Check completion and prepare distinct alternatives'],
  ['Captain review', 'Select a POD; approval makes the assignment final'],
];

type Props = {
  executionView: boolean; request?: RequestRow; requests: RequestRow[]; execution: Execution | null; proposal: Pod | null;
  loading: boolean; busy: boolean; running: boolean; error: string; canRun: boolean; canDecide: boolean;
  decision: 'APPROVED' | 'REJECTED' | null; reason: string;
  onRun: () => void; onRefresh: () => void; onSelect: (id: string) => void; onReason: (value: string) => void;
  onDecision: (action: 'APPROVED' | 'REJECTED') => void; onSaveDecision: () => void; onCancelDecision: () => void;
  onReplacement: (replacement: Replacement) => void; onRecalculate: () => void;
  canManual?: boolean; onManual?: () => void; onDiscardManual?: () => void;
};

export function LiveFitmentPresentation(p: Props) {
  const { data, dispatch } = useStaffingApp();
  const detail = data.requests.find(r => r.id === p.request?.request_id);
  const review = p.proposal?.selection_review;
  const displayed = p.proposal && review ? { ...p.proposal, members: review.members, rationale: review.rationale } : p.proposal;
  const manual = displayed?.members.some(m => m.source === 'MANUAL');
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
          {!p.executionView && p.canManual && <Button disabled={p.busy} onClick={p.onManual}>Manual override</Button>}
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
        <div><h3>{manual ? 'Captain-selected staffing result' : 'Agent result'}</h3><p>{liveStatusLabel(p.proposal.status)} · {p.proposal.total_hours} planned hours{manual ? ' · Manual decision, not an agent execution' : ''}</p></div>
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
      </Card><div className="staffing-fit-results">
        {p.proposal?.origin === 'MANUAL_DRAFT' && <Card padded className="staffing-candidate-section">
          <h3>Captain manual preview</h3><p className="staffing-muted">Saved draft—not an agent recommendation. No capacity is reserved until approval.</p>
          <p>Manual choices use a hard 100% cap: (existing POD hours + new POD hours) ÷ contracted working hours × 100. Leave and external commitments are ignored only for those choices; their records and normal workload reports remain unchanged.</p>
          {p.canManual && <div className="staffing-inline-actions"><Button disabled={p.busy} onClick={p.onRecalculate}>Recalculate selection</Button>
            <Button disabled={p.busy} onClick={p.onDiscardManual}>Discard manual draft</Button></div>}
        </Card>}
        {p.proposal?.stale === 'Y' && <div className="staffing-fit-summary-note" role="alert">{p.proposal.stale_reason || 'Request changed. Run fitment again before approving.'}</div>}
        {review && <Card padded className="staffing-selection-summary"><div className="staffing-selection-summary-head">
          <div><h3>{review.revision ? 'Captain selection' : 'Recommended POD selected'}</h3>
            <p>{review.revision ? `Saved selection ${review.revision}. ` : ''}No capacity is reserved until approval.</p></div>
          {p.canDecide && <Button size="small" disabled={p.busy} onClick={p.onRecalculate}>Recalculate selection</Button>}
        </div><p className="staffing-selection-original">Original recommendation: {review.original_members.map(m => `${m.full_name} (${podRole(m.role_in_pod)})`).join(' · ')}</p></Card>}
        <SavedFactors proposal={displayed} />
        <SavedCandidates title="Pod lead" subtitle={manual ? 'Selected Lead and recorded allocation exceptions' : 'Recommended Lead and eligible alternatives'} members={displayed?.members.filter(m => m.role_in_pod === 'POD_LEAD') ?? []}
          count={p.proposal?.lead_count ?? 1} request={detail} proposalStatus={p.proposal?.status} stale={p.proposal?.stale === 'Y'} />
        {review && <ReplacementChoices key={`lead-${p.proposal?.proposal_id}-${review.revision}`} role="POD_LEAD" options={review.alternatives}
          selected={review.members} disabled={!p.canDecide || p.busy} onChoose={p.onReplacement} />}
        <SavedCandidates title="Contributors" subtitle={manual ? 'Selected contributors, planned hours and any manual exceptions' : 'Capability match, deliverable experience, and remaining capacity'} members={displayed?.members.filter(m => m.role_in_pod !== 'POD_LEAD') ?? []}
          count={p.proposal?.member_count ?? Number(detail?.requestedPodSize?.match(/(\d+) contributor/)?.[1] ?? 2)} request={detail} proposalStatus={p.proposal?.status} stale={p.proposal?.stale === 'Y'} />
        {review && <ReplacementChoices key={`member-${p.proposal?.proposal_id}-${review.revision}`} role="POD_MEMBER" options={review.alternatives}
          selected={review.members} disabled={!p.canDecide || p.busy} onChoose={p.onReplacement} />}
        {review?.notes.map(note => <p className="staffing-muted" key={note}>{note}</p>)}
        {displayed && <Card padded className="staffing-candidate-section"><h3>Why this POD</h3><p className="staffing-muted">{displayed.rationale}</p></Card>}
        {(p.running || p.execution?.last_error_code) && <div className="staffing-section-gap">{log}</div>}
        <div className="staffing-source-strip"><span>{manual ? `Captain manual ${p.proposal?.origin === 'MANUAL_DRAFT' ? 'preview' : 'decision'} · ${liveStatusLabel(p.proposal?.status ?? '')}` : p.execution ? liveStatusLabel(p.execution.status) : 'Awaiting execution'}</span>
          {(!manual || p.execution) && <Button size="small" onClick={() => dispatch({ type: 'set-screen', screen: 'agent' })}>{manual ? 'View prior agent execution' : 'View execution'}</Button>}</div>
      </div>
    </div>)}
    {!p.request && !p.loading && !p.error && <Card padded><div className="staffing-empty">No requests are linked to your staffing identity.</div></Card>}
    <Modal open={Boolean(p.decision)} title={p.decision === 'REJECTED' ? 'Reject proposed pod' : 'Approve proposed pod'} onClose={p.onCancelDecision}
      footer={<><Button disabled={p.busy} onClick={p.onCancelDecision}>Cancel</Button>
        <Button variant="primary" disabled={p.busy || !p.canDecide || (p.decision === 'REJECTED' && !p.reason.trim())} onClick={p.onSaveDecision}>
          {p.busy ? 'Saving…' : p.decision === 'REJECTED' ? 'Confirm rejection' : 'Confirm final assignment'}</Button></>}>
      <div className="staffing-approval-summary"><b>{p.request?.title}</b><p>{displayed?.members.map(m => `${m.full_name} — ${m.planned_hours} hours`).join(', ')}</p>
        {displayed?.members.map(m => <div key={m.person_id}><p>{m.full_name}: {allocationMetric(m.factors.current_window_allocation_pct)} → {allocationMetric(m.factors.window_allocation_pct)} {m.source === 'MANUAL' ? 'POD-only utilization' : 'allocation'} in request period; {allocationMetric(m.factors.projected_allocation_pct)} peak week.</p>
          {m.source === 'MANUAL' && <ManualMetrics member={m} />}</div>)}</div>
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
  if (proposal?.members.some(m => m.source === 'MANUAL')) return <Card padded className="staffing-fit-factors">
    <h3>Captain-selected POD</h3><p className="staffing-muted">Manual choices are not AI-ranked and have no fit score. Review the selected people, recorded skills, scheduled hours and allocation exceptions below.</p></Card>;
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
      const podCount = m.active_pods !== null && m.active_pods !== undefined
        ? ` · ${m.active_pods} active pods as of ${formatDate(m.active_pods_as_of ?? '')}`
        : person ? ` · ${person.activePods} active pods today` : '';
      return <article className={`staffing-candidate selected${!m.source || m.source === 'RECOMMENDED' ? ' recommended' : ''}`} key={m.person_id}>
        {m.source && <div className="staffing-inline-actions"><Pill tone="teal">Selected</Pill>
          <Pill tone={m.source === 'RECOMMENDED' ? 'green' : 'amber'}>{m.source === 'MANUAL' ? 'Captain manual override' : m.source === 'RECOMMENDED' ? 'AI recommendation' : 'Captain-selected alternative'}</Pill></div>}
        <div className="staffing-candidate-head"><Avatar initials={person?.initials || initials(m.full_name)} /><div className="staffing-candidate-main">
          <div className="staffing-candidate-name">{m.full_name} • {podRole(m.role_in_pod)}</div>
          <div className="staffing-candidate-meta">{scheduled && before !== null
            ? `${before} ${m.source === 'MANUAL' ? 'POD-only utilization' : 'allocated'} in request period before this proposal${podCount}`
            : person ? `${personAllocationLabel(person)} current allocation · ${person.activePods} active pods` : m.person_id}</div>
        </div><div className="staffing-score" aria-label={m.score === null ? 'Not AI-ranked' : `Fit score ${m.score}`}>{m.score === null ? '—' : m.score}</div></div>
        <div className="staffing-tag-row">{skills.map(s => <span key={s.id}>{s.name}</span>)}</div>
        <div className="staffing-rationale">{m.responsibilities}</div>
        <div className="staffing-candidate-foot"><span>{m.planned_hours} planned hours</span>
          {scheduled && <span>{after === null ? 'Period allocation unavailable' : `${after} ${m.source === 'MANUAL' ? 'POD-only, max 100%' : 'projected'} for request period`}</span>}
          <span title={m.factors?.peak_week_start ? `Week of ${formatDate(m.factors.peak_week_start)}` : undefined}>
            {projected === null ? 'Projected capacity unavailable' : `${projected} peak weekly allocation`}</span>
          <span>{stale ? 'Re-run required' : liveStatusLabel(proposalStatus ?? 'READY_FOR_REVIEW')}</span></div>
        {m.source === 'MANUAL' && <ManualMetrics member={m} />}
      </article>;
    }) : <div className="staffing-empty compact">A validated recommendation will appear after fitment completes.</div>}</CardBody>
  </Card>;
}

function ManualMetrics({ member: m }: { member: Member }) {
  const reported = m.factors.reported_workload;
  return <div className="staffing-fit-summary-note"><b>Manual exceptions recorded</b>
    <p>Skills/experience and the normal ceiling are bypassed. Ignored in this request period: {m.factors.ignored_leave_hours ?? 0} leave hours and {m.factors.ignored_external_hours ?? 0} external-work hours.</p>
    <p>Overall planned workload, including those records: {allocationMetric(reported?.window_allocation_pct) ?? 'No available capacity'} in the request period; {allocationMetric(reported?.projected_allocation_pct) ?? 'No available capacity'} peak week. This may exceed 100%; the manual limit applies to POD hours against contracted capacity.</p>
  </div>;
}

function ReplacementChoices({ role, options, selected, disabled, onChoose }: {
  role: string; options: Replacement[]; selected: Member[]; disabled: boolean; onChoose: (r: Replacement) => void;
}) {
  const groups = new Map<string, Replacement[]>();
  for (const option of options.filter(r => r.role === role)) groups.set(option.member.person_id, [...(groups.get(option.member.person_id) ?? []), option]);
  if (!groups.size) return null;
  return <Card className="staffing-candidate-section"><CardHeader><div><h3>Alternative {role === 'POD_LEAD' ? 'Leads' : 'contributors'}</h3>
    <p>Selecting an option uses its strongest valid replacement and recalculates the whole POD.</p></div><Pill>{groups.size} options</Pill></CardHeader>
    <CardBody>{[...groups].map(([id, replacements]) => <ReplacementCard key={id} replacements={replacements} selected={selected} disabled={disabled} onChoose={onChoose} />)}</CardBody></Card>;
}

function ReplacementCard({ replacements, selected, disabled, onChoose }: {
  replacements: Replacement[]; selected: Member[]; disabled: boolean; onChoose: (r: Replacement) => void;
}) {
  // The backend orders a person's viable replacements by whole-POD score.
  // Use the strongest valid combination without exposing an implementation-level slot picker.
  const option = replacements[0];
  const m = option.member;
  const replacedName = selected.find(person => person.person_id === option.replaces)?.full_name ?? 'the selected person';
  return <article className="staffing-candidate">
    <div className="staffing-candidate-head"><Avatar initials={initials(m.full_name)} /><div className="staffing-candidate-main">
      <div className="staffing-candidate-name">{m.full_name} • {podRole(m.role_in_pod)}</div><Pill>Alternative</Pill></div>
      <div className="staffing-score" aria-label={`Fit score ${m.score}`}>{m.score}</div></div>
    <p className="staffing-muted">{m.responsibilities}</p>
    <div className="staffing-candidate-foot"><span>{m.planned_hours} planned hours</span>
      <span>{allocationMetric(m.factors.current_window_allocation_pct)} → {allocationMetric(m.factors.window_allocation_pct)} in request period</span>
      <span>{allocationMetric(m.factors.projected_allocation_pct)} peak weekly allocation</span></div>
    {m.active_pods !== null && m.active_pods !== undefined && <p className="staffing-muted">{m.active_pods} active pods as of {formatDate(m.active_pods_as_of ?? '')}</p>}
    <div className="staffing-candidate-choice"><span>Replaces {replacedName}; allocation is recalculated before approval.</span>
      <Button size="small" aria-label={`Select ${m.full_name}`} disabled={disabled} onClick={() => onChoose(option)}>Select</Button></div>
  </article>;
}
