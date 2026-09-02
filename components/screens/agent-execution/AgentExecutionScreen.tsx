'use client';

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
  ['Rank and explain', 'Use stored recommendations and rationale'],
  ['Human review', 'Keep the recommendation advisory'],
] as const;

export function AgentExecutionScreen() {
  const { data, state, dispatch, notify } = useStaffingApp();
  const requests = selectVisibleRequests(data, state.role);
  const request = selectActiveRequest(data, state.role, state.activeRequestId) ?? requests[0];
  return <section className="staffing-screen"><PageHeader title="Agent execution" description="Inspect each evidence and guardrail step before a recommendation is presented for human review." actions={<><SelectField value={request?.id ?? ''} onChange={(event) => dispatch({ type: 'set-active-request', requestId: event.target.value })}>{requests.map((item) => <option value={item.id} key={item.id}>{item.id} • {item.deliverable.name}</option>)}</SelectField><Button variant="primary" disabled={!request} onClick={() => notify('Integration in progress', 'This workflow will be available in a future release.')}>▶ Run fitment</Button></>} /><div className="staffing-agent-shell"><Card padded><h3>Execution stages</h3><div className="staffing-pipeline">{STAGES.map(([title, description], index) => <div className="staffing-step" key={title}><div className="staffing-step-icon">{index + 1}</div><div><div className="staffing-step-title">{title}</div><div className="staffing-step-desc">{description}</div></div></div>)}</div></Card><div className="staffing-grid"><Card><CardHeader><div><h3>Execution log</h3><p>Transparent signals and exclusions</p></div><Pill>Ready</Pill></CardHeader><CardBody><div className="staffing-console"><div><span>[ready]</span> Select a request and run the fitment agent.</div></div></CardBody></Card></div></div></section>;
}
