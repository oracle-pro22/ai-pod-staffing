'use client';

import { useEffect, useMemo, useState } from 'react';

import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { SelectField } from '@/components/ui/FormControls';
import { PageHeader } from '@/components/ui/PageHeader';
import { Pill } from '@/components/ui/Pill';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { resolveFitmentRecommendations } from '@/lib/demo-fitment';
import {
  selectActiveRequest,
  selectScopedRecommendations,
  selectVisiblePeople,
  selectVisibleRequests,
} from '@/lib/selectors';

const STAGES = [
  ['Validate request', 'Load project details and key deliverables'],
  ['Resolve required capabilities', 'Read mapped and request-specific capabilities'],
  ['Retrieve people', 'Load skills, strength, and evidence'],
  ['Apply availability', 'Check travel, commitments, and allocation'],
  ['Rank and explain', 'Use recommendation evidence and rationale'],
  ['Human review', 'Keep the recommendation advisory'],
] as const;

const STEP_DELAY_MS = 650;

export function AgentExecutionScreen() {
  const { data, state, dispatch, notify } = useStaffingApp();
  const requests = selectVisibleRequests(data, state.role);
  const request = selectActiveRequest(data, state.role, state.activeRequestId) ?? requests[0];
  const people = selectVisiblePeople(data, state.role);
  const storedRecommendations = selectScopedRecommendations(request, data, state.role);
  const { recommendations, isDemo: usingDemoRecommendations } = resolveFitmentRecommendations(
    request,
    storedRecommendations,
    people,
  );
  const peopleCount = people.length;
  const availabilityEventCount = people.reduce((total, person) => total + person.availability.length, 0);
  const recommendationCount = recommendations.length;
  const [activeStep, setActiveStep] = useState(-1);
  const [logs, setLogs] = useState<string[]>([]);
  const [completedRequestId, setCompletedRequestId] = useState<string | null>(null);
  const complete = Boolean(request && completedRequestId === request.id && activeStep >= STAGES.length);

  const runLogs = useMemo(() => {
    if (!request) return [];
    const deliverables = request.deliverables.map((item) => item.name).join(', ') || 'no deliverables recorded';
    const capabilities = request.requiredSkills.map((item) => item.name).join(', ') || 'none recorded';
    return [
      `Validated ${request.id}: ${request.projectType.name} / ${deliverables}.`,
      `Resolved ${request.requiredSkills.length} required capabilities: ${capabilities}.`,
      `Retrieved ${peopleCount} people in the ${state.role} access scope.`,
      `Checked ${availabilityEventCount} availability events and current allocation.`,
      usingDemoRecommendations
        ? `Generated ${recommendationCount} simulated demo recommendation${recommendationCount === 1 ? '' : 's'} because no stored recommendation exists.`
        : `Loaded ${recommendationCount} stored recommendation${recommendationCount === 1 ? '' : 's'} with supporting rationale.`,
      'Recommendation remains advisory and awaits mandatory human review.',
    ];
  }, [availabilityEventCount, peopleCount, recommendationCount, request, state.role, usingDemoRecommendations]);

  useEffect(() => {
    if (!state.agentRunning || !request) return;

    setActiveStep(0);
    setLogs([]);
    setCompletedRequestId(null);

    let index = 0;
    const timer = window.setInterval(() => {
      const currentLog = runLogs[index];
      setLogs((current) => [...current, currentLog]);
      index += 1;
      setActiveStep(index);

      if (index >= STAGES.length) {
        window.clearInterval(timer);
        setCompletedRequestId(request.id);
        dispatch({ type: 'set-agent-running', running: false });
        notify(
          usingDemoRecommendations ? 'Demo fitment ready' : 'Fitment evidence loaded',
          usingDemoRecommendations
            ? `Simulated suggestions for ${request.id} are ready for demonstration.`
            : `Stored recommendations for ${request.id} are ready for human review.`,
        );
      }
    }, STEP_DELAY_MS);

    return () => window.clearInterval(timer);
  }, [dispatch, notify, request, runLogs, state.agentRunning, usingDemoRecommendations]);

  useEffect(() => () => {
    dispatch({ type: 'set-agent-running', running: false });
  }, [dispatch]);

  function selectRequest(requestId: string) {
    dispatch({ type: 'set-agent-running', running: false });
    dispatch({ type: 'set-active-request', requestId });
    setActiveStep(-1);
    setLogs([]);
    setCompletedRequestId(null);
  }

  function runFitment() {
    if (!request || state.agentRunning) return;
    dispatch({ type: 'set-active-request', requestId: request.id });
    dispatch({ type: 'set-agent-running', running: true });
  }

  return (
    <section className="staffing-screen">
      <PageHeader
        title="Agent execution"
        description="Inspect each evidence and guardrail step before a recommendation is presented for human review."
        actions={(
          <>
            <SelectField
              value={request?.id ?? ''}
              disabled={state.agentRunning}
              onChange={(event) => selectRequest(event.target.value)}
            >
              {requests.map((item) => (
                <option value={item.id} key={item.id}>{item.id} • {item.deliverable.name}</option>
              ))}
            </SelectField>
            <Button
              variant="primary"
              disabled={state.agentRunning || !request}
              onClick={runFitment}
            >
              ▶ {state.agentRunning ? 'Running…' : 'Run fitment'}
            </Button>
          </>
        )}
      />

      <div className="staffing-agent-shell">
        <Card padded>
          <h3>Execution stages</h3>
          <div className="staffing-pipeline" aria-label="Fitment execution progress">
            {STAGES.map(([title, description], index) => {
              const done = index < activeStep;
              const active = index === activeStep;
              return (
                <div
                  className={`staffing-step${done ? ' done' : active ? ' active' : ''}`}
                  key={title}
                  aria-current={active ? 'step' : undefined}
                >
                  <div className="staffing-step-icon">{done ? '✓' : index + 1}</div>
                  <div>
                    <div className="staffing-step-title">{title}</div>
                    <div className="staffing-step-desc">{description}</div>
                  </div>
                </div>
              );
            })}
          </div>
        </Card>

        <div className="staffing-grid">
          <Card>
            <CardHeader>
              <div>
                <h3>Execution log</h3>
                <p>Transparent signals and exclusions</p>
              </div>
              <Pill tone={state.agentRunning ? 'red' : complete ? 'green' : ''} aria-live="polite">
                {state.agentRunning ? 'Running' : complete ? 'Complete' : 'Ready'}
              </Pill>
            </CardHeader>
            <CardBody>
              <div className="staffing-console" aria-live="polite" aria-busy={state.agentRunning}>
                {logs.length ? logs.map((log, index) => (
                  <div key={`${log}-${index}`}>
                    <span>[step {index + 1}]</span>{' '}
                    <b className={index === logs.length - 1 && complete ? 'warn' : 'ok'}>{log}</b>
                  </div>
                )) : (
                  <div><span>[ready]</span> Select a request and run the fitment agent.</div>
                )}
              </div>
            </CardBody>
          </Card>

          {complete && request ? (
            <Card>
              <CardHeader>
                <div>
                  <h3>Agent result</h3>
                  <p>{usingDemoRecommendations
                    ? 'Simulated recommendations for demonstration only'
                    : 'Recommendation awaits human approval'}</p>
                </div>
                <div className="staffing-inline-actions">
                  {usingDemoRecommendations ? <Pill tone="purple">Demo data</Pill> : null}
                  <Button
                    size="small"
                    onClick={() => dispatch({ type: 'set-screen', screen: 'fitment' })}
                  >
                    Open full review
                  </Button>
                </div>
              </CardHeader>
              <CardBody>
                {recommendations.length ? recommendations.slice(0, 3).map((item) => {
                  const person = data.people.find((candidate) => candidate.id === item.personId);
                  return (
                    <div className="staffing-agent-result" key={`${item.personId}-${item.roleInPod}`}>
                      <Avatar initials={person?.initials ?? 'AI'} />
                      <div>
                        <b>{item.personName} • {item.roleInPod}</b>
                        <small>{item.rationale}</small>
                        <small>{item.source}</small>
                      </div>
                      <strong>{item.score}</strong>
                    </div>
                  );
                }) : (
                  <div className="staffing-empty compact">
                    No stored recommendations are available for this request.
                  </div>
                )}
              </CardBody>
            </Card>
          ) : null}
        </div>
      </div>
    </section>
  );
}
