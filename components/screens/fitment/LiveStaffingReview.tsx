'use client';
import { staffingFetch } from '@/lib/staffing-fetch';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { LiveFitmentPresentation } from './LiveFitmentPresentation';
import { useStaffingApp } from '@/context/StaffingAppProvider';

export type RequestRow = { request_id: string; title: string; status: string; responsible_captain_id: string };
type Identity = { person_id: string; roles: string[]; permissions: { role: string; resource: string; scope: string; actions: string[] }[] };
export type Execution = { execution_id: string; request_id: string; status: string; last_error_code?: string; last_error_summary?: string;
  clarification_questions: string[]; events: { event_sequence: number; stage: string; status: string; summary: string }[];
  proposals: { proposal_id: string; status: string }[] };
export type Member = { person_id: string; full_name: string; role_in_pod: string; planned_hours: number; score: number;
  responsibilities: string; factors: { projected_allocation_pct?: string | null; factors?: Record<string, string>;
    scheduling_algorithm?: string; peak_week_start?: string;
    current_window_allocation_pct?: string | null; window_allocation_pct?: string | null } };
export type Pod = { proposal_id: string; request_id: string; proposal_version: number; status: string; stale: 'Y' | 'N';
  starts_on: string; ends_on: string; total_hours: number; lead_count: number; member_count: number;
  rationale: string; policy_version: string; members: Member[]; stale_reason?: string };

async function api<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await staffingFetch(`/api/agentic/${path}`, { method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body), cache: 'no-store', signal });
  const payload = await response.json();
  if (!response.ok) throw new Error(typeof payload.error === 'string' ? payload.error : payload.error?.message || 'Staffing operation could not be completed.');
  return payload.data as T;
}


export function LiveStaffingReview({ executionView = false }: { executionView?: boolean }) {
  const { data, state, dispatch, notify } = useStaffingApp();
  const router = useRouter();
  const [requests, setRequests] = useState<RequestRow[]>([]);
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [execution, setExecution] = useState<Execution | null>(null);
  const [proposal, setProposal] = useState<Pod | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [decision, setDecision] = useState<'APPROVED' | 'REJECTED' | null>(null);
  const [reason, setReason] = useState('');
  const operationKeys = useRef(new Map<string, string>());
  const decisionTarget = useRef<string | null>(null);
  const selected = requests.find(r => r.request_id === state.activeRequestId) ?? requests[0];
  const requestId = selected?.request_id;
  const running = execution?.status === 'QUEUED' || execution?.status === 'RUNNING';
  const hasPermission = (resource: string, action: string) => state.role === 'POD Captain'
    && identity?.person_id === selected?.responsible_captain_id
    && identity?.permissions.some(p => p.role === 'POD_CAPTAIN' && p.resource === resource
      && p.scope !== 'LOCKED' && p.actions.includes('view') && p.actions.includes(action));

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(''); setRequests([]); setIdentity(null);
    Promise.all([api<RequestRow[]>('requests', undefined, controller.signal), api<Identity>('me', undefined, controller.signal)])
      .then(([rows, actor]) => { if (!controller.signal.aborted) { setRequests(rows); setIdentity(actor); } })
      .catch(e => { if (!controller.signal.aborted) setError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [state.role, state.activeRequestId, refresh]);

  useEffect(() => { setDecision(null); setReason(''); decisionTarget.current = null; },
    [proposal?.proposal_id, proposal?.proposal_version, proposal?.status]);

  useEffect(() => {
    setExecution(null); setProposal(null); setDecision(null); setReason('');
    if (!requestId) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const current = await api<Execution | null>(`requests/${requestId}/execution`, undefined, controller.signal);
        const proposalId = current?.proposals.at(-1)?.proposal_id;
        const next = proposalId ? await api<Pod>(`proposals/${proposalId}`, undefined, controller.signal) : null;
        if (!controller.signal.aborted) { setExecution(current); setProposal(next); setError(''); }
      } catch (e) {
        if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'Unable to refresh staffing status.');
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(poll, 3000);
      }
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [requestId, refresh]);

  function operationKey(signature: string) {
    if (!operationKeys.current.has(signature)) operationKeys.current.set(signature, crypto.randomUUID());
    return operationKeys.current.get(signature)!;
  }

  async function run() {
    if (!requestId || busy || running) return;
    setBusy(true);
    const signature = `run:${requestId}`;
    try {
      await api(`requests/${requestId}/executions`, { idempotency_key: operationKey(signature) });
      operationKeys.current.delete(signature);
      notify('Staffing started', `${requestId} is queued for fitment.`);
      setRefresh(v => v + 1);
    } catch (e) { notify('Unable to start staffing', e instanceof Error ? e.message : 'Check execution status before retrying.'); }
    finally { setBusy(false); }
  }

  async function saveDecision() {
    if (!proposal || !decision || busy || (decision === 'REJECTED' && !reason.trim())) return;
    if (decisionTarget.current !== `${proposal.proposal_id}:${proposal.proposal_version}`) {
      setDecision(null); notify('Review changed', 'Review the current proposal before confirming.'); return;
    }
    const signature = `${proposal.proposal_id}:${proposal.proposal_version}:${decision}:${reason.trim()}`;
    setBusy(true);
    try {
      await api('decisions', { proposal_id: proposal.proposal_id, proposal_version: proposal.proposal_version,
        action: decision, reason: reason.trim(), idempotency_key: operationKey(signature) });
      operationKeys.current.delete(signature);
      notify(decision === 'APPROVED' ? 'POD approved' : 'POD rejected', decision === 'APPROVED'
        ? 'The assignments are final. No member acceptance is required.' : 'Your reason was saved for the next recommendation.');
      setDecision(null); setReason(''); setRefresh(v => v + 1); router.refresh();
    } catch (e) { notify('Decision not confirmed', e instanceof Error ? e.message : 'Refresh the review before retrying.'); }
    finally { setBusy(false); }
  }

  function beginDecision(action: 'APPROVED' | 'REJECTED') {
    if (!proposal) return;
    decisionTarget.current = `${proposal.proposal_id}:${proposal.proposal_version}`;
    setDecision(action);
  }

  const canDecide = Boolean(hasPermission('AI_FITMENT', 'approve') && proposal?.status === 'READY_FOR_REVIEW'
    && proposal.request_id === requestId && proposal.stale === 'N' && !running);
  return <LiveFitmentPresentation executionView={executionView} request={selected}
    requests={requests} execution={execution?.request_id === requestId ? execution : null}
    proposal={proposal?.request_id === requestId ? proposal : null} loading={loading} busy={busy}
    running={running} error={error} canRun={Boolean(hasPermission('AGENT_EXECUTION', 'create'))}
    canDecide={canDecide} decision={decision} reason={reason}
    onReason={setReason} onRun={run} onRefresh={() => setRefresh(n => n + 1)}
    onDecision={beginDecision} onSaveDecision={saveDecision}
    onCancelDecision={() => { if (!busy) { setDecision(null); setReason(''); } }}
    onSelect={requestId => dispatch({ type: 'set-active-request', requestId })} />;
}
