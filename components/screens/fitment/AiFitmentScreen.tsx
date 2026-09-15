'use client';

import { useEffect, useRef, useState } from 'react';

import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { PageHeader } from '@/components/ui/PageHeader';
import { Pill } from '@/components/ui/Pill';
import { ProgressBar } from '@/components/ui/ProgressBar';
import { SelectField } from '@/components/ui/FormControls';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { resolveFitmentRecommendations } from '@/lib/demo-fitment';
import { formatDate, requestEffortLabel } from '@/lib/formatting';
import { canPerform } from '@/lib/role-policy';
import {
  selectActiveRequest,
  selectScopedRecommendations,
  selectVisiblePeople,
  selectVisibleRequests,
} from '@/lib/selectors';
import type { StaffingRecommendation } from '@/types/staffing';
import type { Tone } from '@/types/ui';
import { LiveStaffingReview } from './LiveStaffingReview';
import { RequestsScreen } from '../requests/RequestsScreen';

const FACTOR_TONES: Tone[] = ['teal', 'blue', 'teal', 'amber', 'red'];

export function AiFitmentScreen() {
  const { data } = useStaffingApp();
  if (data.identity && ['POD Lead', 'POD Member'].includes(data.identity.role)) return <RequestsScreen />;
  return process.env.NEXT_PUBLIC_STAFFING_AGENTIC_ENABLED === 'true' ? <LiveStaffingReview /> : <PreviewFitmentScreen />;
}

function PreviewFitmentScreen() {
  const { data, state, dispatch, notify } = useStaffingApp();
  const requests = selectVisibleRequests(data, state.role);
  const request = selectActiveRequest(data, state.role, state.activeRequestId);
  const people = selectVisiblePeople(data, state.role);
  const storedRecommendations = selectScopedRecommendations(request, data, state.role);
  const { recommendations, isDemo } = resolveFitmentRecommendations(request, storedRecommendations, people);
  const isMember = state.role === 'POD Member';
  const canRerun = canPerform(state.role, 'AI_FITMENT', 'canCreate', data.authorization);
  const canApprove = canPerform(state.role, 'AI_FITMENT', 'canApprove', data.authorization);
  const leads = recommendations.filter((item) => /lead/i.test(item.roleInPod));
  const contributors = recommendations.filter((item) => !/lead/i.test(item.roleInPod));
  const recommendationFactors = (leads[0] ?? contributors[0])?.factors ?? [];
  const [rerunning, setRerunning] = useState(false);
  const rerunTimer = useRef<number | null>(null);

  useEffect(() => {
    if (rerunTimer.current !== null) window.clearTimeout(rerunTimer.current);
    setRerunning(false);
    return () => {
      if (rerunTimer.current !== null) window.clearTimeout(rerunTimer.current);
    };
  }, [request?.id, state.role]);

  function rerunFitment() {
    if (!request || rerunning || !canRerun) return;
    setRerunning(true);
    rerunTimer.current = window.setTimeout(() => {
      setRerunning(false);
      rerunTimer.current = null;
      notify(
        isDemo ? 'Demo fitment refreshed' : 'Fitment evidence refreshed',
        isDemo
          ? `Simulated suggestions for ${request.id} are ready for demonstration.`
          : `Stored recommendations for ${request.id} are ready for review.`,
      );
    }, 900);
  }

  return (
    <section className="staffing-screen">
      <PageHeader title="AI fitment review" description="Evidence-based recommendations remain advisory until a person approves them." actions={<><label className="staffing-fitment-picker"><span>Staffing request</span><SelectField value={request?.id ?? ''} onChange={(event) => dispatch({ type: 'set-active-request', requestId: event.target.value })}>{requests.map((item) => <option key={item.id} value={item.id}>{item.id} — {item.title} • {item.status}</option>)}</SelectField></label>{canRerun ? <Button disabled={rerunning || !request} onClick={rerunFitment}>↻ {rerunning ? 'Re-running…' : 'Re-run'}</Button> : null}{canApprove ? <Button variant="primary" onClick={() => request && dispatch({ type: 'open-modal', modal: { id: 'approve-pod', title: 'Approve proposed pod', payload: { requestId: request.id } } })}>Approve pod</Button> : null}</>} />
      {request ? <div className="staffing-fit-layout">
        <Card padded className="staffing-request-summary">
          <div className="staffing-summary-head"><div><Pill tone={/high|urgent/i.test(request.priority) ? 'red' : ''}>{request.priority} priority</Pill><h3 className="staffing-summary-title">{request.title}</h3><p className="staffing-muted">{request.id} • {request.projectType.name}</p></div><Button size="small" aria-label={`Open details for ${request.id}`} onClick={() => dispatch({ type: 'open-drawer', drawer: { id: 'request-details', title: request.title, payload: { requestId: request.id } } })}>↗</Button></div>
          <dl className="staffing-summary-list">
            <div><dt>Needed by date</dt><dd>{formatDate(request.neededBy)}</dd></div>
            <div><dt>Key deliverables</dt><dd>{request.deliverables.map((item) => item.name).join(', ')}</dd></div>
            <div><dt>Estimated effort</dt><dd>{requestEffortLabel(request)}</dd></div>
            <div><dt>Required capabilities</dt><dd><div className="staffing-tag-row">{request.requiredSkills.map((skill) => <span key={skill.id}>{skill.name}</span>)}</div></dd></div>
            <div><dt>Status</dt><dd>{request.status}</dd></div>
          </dl>
          <div className="staffing-fit-summary-note"><b>Business objectives</b><p>{request.businessObjectives || request.businessContext || 'No business objectives recorded'}</p></div>
          <div className="staffing-fit-summary-note"><b>Expected outcomes</b><p>{request.expectedOutcomes || 'No expected outcomes recorded'}</p></div>
          <div className="staffing-source-strip"><span>Mapping {request.mappingVersion}</span><span>•</span><span>Human approval required</span></div>
        </Card>
        <div>
          <Card padded className="staffing-fit-factors">
            <div className="staffing-explain-title"><span className="staffing-spark">✦</span><span><b>How the recommendation was formed</b><small>{isDemo ? 'Simulated from current profile and request data' : 'Inputs preserved for governance review'}</small></span>{isDemo ? <Pill tone="purple">Demo data</Pill> : null}</div>
            {recommendationFactors.length ? recommendationFactors.map((factor, index) => <div className="staffing-factor" key={factor.code || factor.name}><span>{factor.name}</span><ProgressBar value={factor.evidenceScore} tone={FACTOR_TONES[index % FACTOR_TONES.length]} /><strong>{factor.weightPct}%</strong></div>) : <div className="staffing-empty compact">No recommendation-factor evidence is recorded for this request.</div>}
          </Card>
          <CandidateSection title={isMember ? 'My proposed assignment' : 'Recommended pod lead'} subtitle={isMember ? 'Recommendation evidence in your access scope' : canApprove ? 'Choose a candidate to update the proposed pod' : 'Approved POD lead for this project'} badge={isMember ? 'Advisory' : '1 required'} recommendations={isMember ? recommendations : leads} requestId={request.id} />
          {!isMember ? <CandidateSection title="Recommended contributors" subtitle="Multi-interest fit, strength, and remaining capacity" badge="2 required" recommendations={contributors} requestId={request.id} /> : null}
        </div>
      </div> : <div className="staffing-empty">No staffing request is available in this access scope.</div>}
    </section>
  );
}

function CandidateSection({ title, subtitle, badge, recommendations, requestId }: { title: string; subtitle: string; badge: string; recommendations: StaffingRecommendation[]; requestId: string }) {
  const { data, state, dispatch } = useStaffingApp();
  const selected = state.selectedCandidatesByRequest[requestId] ?? [];
  const canSelect = canPerform(state.role, 'AI_FITMENT', 'canUpdate', data.authorization);
  return <Card className="staffing-candidate-section"><CardHeader><div><h3>{title}</h3><p>{subtitle}</p></div><Pill tone="green">{badge}</Pill></CardHeader><CardBody>{recommendations.length ? recommendations.map((item, index) => {
    const person = data.people.find((candidate) => candidate.id === item.personId);
    const isSelected = selected.includes(item.personId) || (!canSelect && item.selected === true);
    const availabilityCount = person?.availability.length ?? 0;
    return <button type="button" aria-disabled={!canSelect} className={`staffing-candidate${index === 0 ? ' recommended' : ''}${isSelected ? ' selected' : ''}`} key={`${item.personId}-${item.roleInPod}`} onClick={() => canSelect && dispatch({ type: 'toggle-candidate', requestId, personId: item.personId })}><div className="staffing-candidate-head"><Avatar initials={person?.initials ?? item.personName.split(' ').map((part) => part[0]).join('')} /><div className="staffing-candidate-main"><div className="staffing-candidate-name">{item.personName} • {item.roleInPod}</div><div className="staffing-candidate-meta">{person?.allocationPct ?? 0}% allocated • {person?.activePods ?? 0} active pods</div></div><div className="staffing-score">{item.score}</div></div><div className="staffing-tag-row">{item.matchingSkills.map((skill) => <span key={skill}>{skill}</span>)}</div><div className="staffing-rationale">{item.rationale}</div><div className="staffing-candidate-foot">{item.decisionStatus}　•　{availabilityCount} availability event{availabilityCount === 1 ? '' : 's'}　•　{item.source}</div></button>;
  }) : <div className="staffing-empty compact">No candidates are available in this scope.</div>}</CardBody></Card>;
}
