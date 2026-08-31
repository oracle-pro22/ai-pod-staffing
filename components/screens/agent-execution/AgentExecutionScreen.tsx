'use client';

import { useEffect, useState } from 'react';

import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { PageHeader } from '@/components/ui/PageHeader';
import { Pill } from '@/components/ui/Pill';
import { SelectField } from '@/components/ui/FormControls';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { selectActiveRequest, selectVisibleRequests } from '@/lib/selectors';

const STAGES = [
  ['Validate request', 'Load project details and key deliverables'],
  ['Resolve required capabilities', 'Read mapped and request-specific capabilities'],
  ['Retrieve people', 'Load skills, strength, and evidence'],
  ['Apply availability', 'Check travel, commitments, and allocation'],
  ['Rank and explain', 'Use workbook recommendations and rationale'],
  ['Human review', 'Keep the recommendation advisory'],
] as const;

const LOGS = [
  'Request fields validated against the customer catalogue.',
  'Required capabilities resolved from deliverable mappings.',
  'People evidence and capability strength retrieved.',
  'Availability conflicts and current allocation checked.',
  'Workbook recommendation evidence ranked and explained.',
  'Recommendation paused for mandatory human review.',
] as const;

export function AgentExecutionScreen() {
  const { data, state, dispatch } = useStaffingApp();
  const requests = selectVisibleRequests(data, state.role, state.drafts);
  const request = selectActiveRequest(data, state.role, state.activeRequestId, state.drafts) ?? requests[0];
  const [activeStep, setActiveStep] = useState(-1);
  const [logs, setLogs] = useState<string[]>([]);
  const complete = activeStep >= STAGES.length;

  useEffect(() => {
    if (!state.agentRunning) return;
    setActiveStep(0); setLogs([]);
    let index = 0;
    const timer = window.setInterval(() => {
      setLogs((current) => [...current, LOGS[index]]);
      index += 1;
      setActiveStep(index);
      if (index >= STAGES.length) { window.clearInterval(timer); dispatch({ type: 'set-agent-running', running: false }); }
    }, 650);
    return () => window.clearInterval(timer);
  }, [state.agentRunning, dispatch]);

  return <section className="staffing-screen"><PageHeader title="Agent execution" description="Inspect each evidence and guardrail step before a recommendation is presented for human review." actions={<><SelectField value={request?.id ?? ''} onChange={(event) => dispatch({ type: 'set-active-request', requestId: event.target.value })}>{requests.map((item) => <option value={item.id} key={item.id}>{item.id} • {item.deliverable.name}</option>)}</SelectField><Button variant="primary" disabled={state.agentRunning || !request} onClick={() => dispatch({ type: 'set-agent-running', running: true })}>▶ {state.agentRunning ? 'Running…' : 'Run fitment'}</Button></>} /><div className="staffing-agent-shell"><Card padded><h3>Execution stages</h3><div className="staffing-pipeline">{STAGES.map(([title, description], index) => <div className={`staffing-step${index < activeStep ? ' done' : index === activeStep ? ' active' : ''}`} key={title}><div className="staffing-step-icon">{index < activeStep ? '✓' : index + 1}</div><div><div className="staffing-step-title">{title}</div><div className="staffing-step-desc">{description}</div></div></div>)}</div></Card><div className="staffing-grid"><Card><CardHeader><div><h3>Execution log</h3><p>Transparent signals and exclusions</p></div><Pill tone={state.agentRunning ? 'red' : complete ? 'green' : ''}>{state.agentRunning ? 'Running' : complete ? 'Complete' : 'Ready'}</Pill></CardHeader><CardBody><div className="staffing-console">{logs.length ? logs.map((log, index) => <div key={`${log}-${index}`}><span>[step {index + 1}]</span> <b className={index === logs.length - 1 && complete ? 'warn' : 'ok'}>{log}</b></div>) : <div><span>[ready]</span> Select a request and run the fitment agent.</div>}</div></CardBody></Card>{complete && request ? <Card><CardHeader><div><h3>Agent result</h3><p>Recommendation awaits human approval</p></div><Button size="small" onClick={() => dispatch({ type: 'set-screen', screen: 'fitment' })}>Open full review</Button></CardHeader><CardBody>{request.recommendations.length ? request.recommendations.slice(0, 3).map((item) => { const person = data.people.find((candidate) => candidate.id === item.personId); return <div className="staffing-agent-result" key={`${item.personId}-${item.roleInPod}`}><Avatar initials={person?.initials ?? 'AI'} /><div><b>{item.personName} • {item.roleInPod}</b><small>{item.rationale}</small></div><strong>{item.score}</strong></div>; }) : <div className="staffing-empty compact">No recommendation is recorded for this request.</div>}</CardBody></Card> : null}</div></div></section>;
}
