'use client';
import { staffingFetch } from '@/lib/staffing-fetch';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { LiveFitmentPresentation } from './LiveFitmentPresentation';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { ManualPodEditor, type ManualSlot, type ManualPerson } from './ManualPodEditor';

export type RequestRow = { request_id: string; title: string; status: string; responsible_captain_id: string };
type Identity = { person_id: string; roles: string[]; permissions: { role: string; resource: string; scope: string; actions: string[] }[] };
export type Execution = { execution_id: string; request_id: string; status: string; last_error_code?: string; last_error_summary?: string;
  clarification_questions: string[]; events: { event_sequence: number; stage: string; status: string; summary: string }[];
  proposals: { proposal_id: string; status: string }[] };
export type Member = { person_id: string; full_name: string; role_in_pod: string; planned_hours: number; score: number | null;
  source?: 'RECOMMENDED' | 'ALTERNATIVE' | 'MANUAL';
  active_pods?: number | null; active_pods_as_of?: string | null;
  responsibilities: string; factors: { projected_allocation_pct?: string | null; factors?: Record<string, string>;
    scheduling_algorithm?: string; peak_week_start?: string;
    current_window_allocation_pct?: string | null; window_allocation_pct?: string | null;
    allocation_basis?: string; ignored_leave_hours?: number | string; ignored_external_hours?: number | string;
    reported_workload?: { window_allocation_pct: string | null; projected_allocation_pct: string | null; no_available_capacity?: boolean } } };
export type Pod = { proposal_id: string; request_id: string; proposal_version: number; status: string; stale: 'Y' | 'N';
  starts_on: string; ends_on: string; total_hours: number; lead_count: number; member_count: number;
  rationale: string; policy_version: string; members: Member[]; stale_reason?: string; selection_review?: SelectionReview; origin?: string };
export type Replacement = { replaces: string; role: string; member: Member };
export type SelectionReview = { revision: number; selection_id: string | null; members: Member[];
  original_members: Member[]; alternatives: Replacement[]; rationale: string; notes: string[];
  search_exhaustive: boolean; reserves_capacity: false };
export type ManualDraft = { draft_id: string; revision: number; request_id: string; request_revision: number;
  policy_version: string; source_proposal_id: string | null; slots: ManualSlot[]; starts_on: string; ends_on: string;
  lead_count: number; member_count: number; total_hours: number; members: Member[]; original_members: Member[]; rationale: string };
type ManualState = { people: ManualPerson[]; request_revision: number; lead_count: number; member_count: number; latest_draft_id: string | null; draft: ManualDraft | null };

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
  const [manualState, setManualState] = useState<ManualState | null>(null);
  const [manualOpen, setManualOpen] = useState(false);
  const operationKeys = useRef(new Map<string, string>());
  const decisionTarget = useRef<string | null>(null);
  const mutation = useRef(0);
  const mutating = useRef(false);
  const selected = requests.find(r => r.request_id === state.activeRequestId) ?? requests[0];
  const requestId = selected?.request_id;
  const running = execution?.status === 'QUEUED' || execution?.status === 'RUNNING';
  const hasPermission = (resource: string, action: string) => state.role === 'POD Captain'
    && identity?.person_id === selected?.responsible_captain_id
    && identity?.permissions.some(p => p.role === 'POD_CAPTAIN' && p.resource === resource
      && p.scope !== 'LOCKED' && p.actions.includes('view') && p.actions.includes(action));
  const canManual = Boolean(hasPermission('AI_FITMENT', 'approve') && selected && ['NEEDS_RECOMMENDATION', 'IN_REVIEW'].includes(selected.status));
  const manualDraft = manualState?.draft;
  const manualPod: Pod | null = manualDraft ? { ...manualDraft, proposal_id: manualDraft.draft_id,
    proposal_version: manualDraft.revision, status: 'READY_FOR_REVIEW', stale: 'N', origin: 'MANUAL_DRAFT' } : null;
  const reviewedProposal = manualPod ?? proposal;

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
    [reviewedProposal?.proposal_id, reviewedProposal?.proposal_version, reviewedProposal?.status, reviewedProposal?.selection_review?.revision]);

  useEffect(() => {
    setExecution(null); setProposal(null); setDecision(null); setReason(''); setManualState(null); setManualOpen(false);
    if (!requestId) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      const generation = mutation.current;
      try {
        if (mutating.current) return;
        const current = await api<Execution | null>(`requests/${requestId}/execution`, undefined, controller.signal);
        const next = await api<Pod | null>(`requests/${requestId}/proposal`, undefined, controller.signal);
        const manual = canManual ? await api<ManualState>(`requests/${requestId}/manual`, undefined, controller.signal) : null;
        if (!controller.signal.aborted && generation === mutation.current && !mutating.current) { setExecution(current); setProposal(next); setManualState(manual); setError(''); }
      } catch (e) {
        if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'Unable to refresh staffing status.');
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(poll, 3000);
      }
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [requestId, refresh, canManual]);

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
    const proposal = reviewedProposal;
    if (!proposal || !decision || busy || (decision === 'REJECTED' && !reason.trim())) return;
    if (decisionTarget.current !== `${proposal.proposal_id}:${proposal.proposal_version}:${proposal.selection_review?.revision ?? 0}`) {
      setDecision(null); notify('Review changed', 'Review the current proposal before confirming.'); return;
    }
    const signature = `${proposal.proposal_id}:${proposal.proposal_version}:${proposal.selection_review?.selection_id ?? ''}:${decision}:${reason.trim()}`;
    setBusy(true);
    mutating.current = true; mutation.current++;
    try {
      if (manualDraft) await api(`requests/${requestId}/manual-decision`, { draft_id: manualDraft.draft_id,
        action: decision, reason: reason.trim(), idempotency_key: operationKey(signature) });
      else await api('decisions', { proposal_id: proposal.proposal_id, proposal_version: proposal.proposal_version,
        selection_id: proposal.selection_review?.selection_id ?? null,
        action: decision, reason: reason.trim(), idempotency_key: operationKey(signature) });
      operationKeys.current.delete(signature);
      notify(decision === 'APPROVED' ? 'POD approved' : 'POD rejected', decision === 'APPROVED'
        ? 'The assignments are final. No member acceptance is required.' : 'Your reason was saved for the next recommendation.');
      setDecision(null); setReason(''); setRefresh(v => v + 1); router.refresh();
    } catch (e) { notify('Decision not confirmed', e instanceof Error ? e.message : 'Refresh the review before retrying.'); }
    finally { setBusy(false); mutating.current = false; }
  }

  async function changeSelection(replacement?: Replacement) {
    if (!proposal?.selection_review || busy || !canDecide) return;
    const targetId = proposal.proposal_id;
    const revision = proposal.selection_review.revision;
    const change = replacement ? { person_id: replacement.member.person_id, replaces: replacement.replaces, role: replacement.role } : {};
    const signature = `selection:${targetId}:${revision}:${JSON.stringify(change)}`;
    setBusy(true); mutating.current = true; mutation.current++;
    setDecision(null);
    try {
      const review = await api<SelectionReview>(`proposals/${targetId}/selection`, {
        ...change, revision, idempotency_key: operationKey(signature),
      });
      operationKeys.current.delete(signature);
      setProposal(current => current?.proposal_id === targetId ? { ...current, selection_review: review } : current);
      setError('');
      notify('POD selection recalculated', 'Review the updated hours and allocations. Capacity is not reserved until approval.');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unable to recalculate selection. Refresh before retrying.');
    } finally { setBusy(false); mutating.current = false; }
  }

  function beginDecision(action: 'APPROVED' | 'REJECTED') {
    const proposal = reviewedProposal;
    if (!proposal) return;
    decisionTarget.current = `${proposal.proposal_id}:${proposal.proposal_version}:${proposal.selection_review?.revision ?? 0}`;
    setDecision(action);
  }

  async function previewManual(slots: ManualSlot[]) {
    if (!manualState || !requestId || busy || !canManual || running) return;
    const source = manualDraft?.source_proposal_id ?? (proposal?.status === 'READY_FOR_REVIEW' && proposal.stale === 'N' && proposal.selection_review ? proposal.proposal_id : null);
    const body = { request_revision: manualState.request_revision, previous_draft_id: manualState.latest_draft_id, source_proposal_id: source, slots };
    const signature = `manual:${requestId}:${JSON.stringify(body)}`;
    setBusy(true); mutating.current = true; mutation.current++; setDecision(null);
    try {
      const draft = await api<ManualDraft>(`requests/${requestId}/manual-preview`, { ...body, idempotency_key: operationKey(signature) });
      operationKeys.current.delete(signature);
      setManualState(current => current ? { ...current, latest_draft_id: draft.draft_id, draft } : current);
      setManualOpen(false); notify('Manual preview saved', 'Review the exact selected people, hours and both allocation figures before approval.');
    } catch (e) { notify('Manual preview not saved', e instanceof Error ? e.message : 'Refresh and retry.'); }
    finally { setBusy(false); mutating.current = false; }
  }

  async function discardManual() {
    if (!manualDraft || !canManual || busy) return;
    const signature = `discard:${manualDraft.draft_id}`;
    setBusy(true); mutating.current = true; mutation.current++; setDecision(null);
    try {
      await api(`requests/${requestId}/manual-decision`, { draft_id: manualDraft.draft_id, action: 'DISCARDED', idempotency_key: operationKey(signature) });
      operationKeys.current.delete(signature); setRefresh(n => n + 1);
      notify('Manual draft discarded', 'No assignments were created. Fitment can run again.');
    } catch (e) { notify('Draft not discarded', e instanceof Error ? e.message : 'Refresh and retry.'); }
    finally { setBusy(false); mutating.current = false; }
  }

  const canDecide = Boolean(hasPermission('AI_FITMENT', 'approve') && reviewedProposal?.status === 'READY_FOR_REVIEW'
    && reviewedProposal.request_id === requestId && reviewedProposal.stale === 'N' && !running);
  const initialMembers = manualDraft?.members ?? (proposal?.status === 'READY_FOR_REVIEW' && proposal.stale === 'N' && proposal.selection_review ? proposal.selection_review.members : []);
  return <><LiveFitmentPresentation executionView={executionView} request={selected}
    requests={requests} execution={execution?.request_id === requestId ? execution : null}
    proposal={(executionView ? proposal : reviewedProposal)?.request_id === requestId ? (executionView ? proposal : reviewedProposal) : null} loading={loading} busy={busy}
    running={running} error={error} canRun={Boolean(hasPermission('AGENT_EXECUTION', 'create')) && !manualDraft}
    canDecide={canDecide} decision={decision} reason={reason}
    onReason={setReason} onRun={run} onRefresh={() => setRefresh(n => n + 1)}
    onDecision={beginDecision} onSaveDecision={saveDecision}
    onReplacement={changeSelection} onRecalculate={() => manualDraft ? previewManual(manualDraft.slots) : changeSelection()}
    canManual={canManual && Boolean(manualState) && !running} onManual={() => setManualOpen(true)} onDiscardManual={discardManual}
    onCancelDecision={() => { if (!busy) { setDecision(null); setReason(''); } }}
    onSelect={requestId => dispatch({ type: 'set-active-request', requestId })} />
    {manualOpen && manualState && <ManualPodEditor key={manualDraft?.draft_id ?? requestId} people={manualState.people} selected={initialMembers}
      slots={manualDraft?.slots} leadCount={manualState.lead_count}
      memberCount={manualState.member_count}
      busy={busy} onClose={() => { if (!busy) setManualOpen(false); }} onPreview={previewManual} />}</>;
}
