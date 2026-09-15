'use client';

import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { staffingFetch } from '@/lib/staffing-fetch';

type Policy = { version: string; maximum_allocation_pct: string | number; approved_by: string };

export function UtilizationSettings() {
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [limit, setLimit] = useState('');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setPolicy(null); setError('');
    staffingFetch('/api/agentic/admin/utilization', { cache: 'no-store', signal: controller.signal })
      .then(async response => {
        const payload = await response.json();
        if (!response.ok) throw new Error(typeof payload.error === 'string' ? payload.error : payload.error?.message || 'Unable to load utilization settings.');
        if (!controller.signal.aborted) { setPolicy(payload.data); setLimit(String(payload.data.maximum_allocation_pct)); }
      }).catch(e => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [refresh]);
  const valid = /^\d+(\.\d{1,2})?$/.test(limit) && Number(limit) > 0 && Number(limit) <= 100;
  async function save() {
    if (!policy || busy || !valid || !reason.trim()) return;
    setBusy(true); setError(''); setMessage('');
    try {
      const response = await staffingFetch('/api/agentic/admin/utilization', { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
          maximum_allocation_pct: limit, expected_policy_version: policy.version, reason: reason.trim(),
        }) });
      const payload = await response.json();
      if (!response.ok) throw new Error(typeof payload.error === 'string' ? payload.error : payload.error?.message || 'Unable to save utilization settings.');
      setPolicy(payload.data); setLimit(String(payload.data.maximum_allocation_pct)); setReason('');
      setMessage('Limit saved. New runs use this policy immediately. Re-run pending proposals before approving them.');
    } catch (e) { setError(e instanceof Error ? e.message : 'Save failed. Refresh to check the current setting before retrying.'); }
    finally { setBusy(false); }
  }
  return <div style={{ maxWidth: 680 }}>
    <h3>Maximum utilization</h3>
    <p className="staffing-muted">Maximum planned workload after a new assignment, including existing projects and other commitments. Applied to each day, the request period, and complete weeks, after leave.</p>
    {error && <p role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}
    {!policy && !error && <p role="status">Loading current limit…</p>}
    {policy && <form onSubmit={event => { event.preventDefault(); void save(); }}>
      <label style={{ display: 'block', marginBottom: 16 }} htmlFor="utilization-limit">Maximum utilization (%)
        <input id="utilization-limit" className="staffing-field" type="number" min="0.01" max="100" step="0.01"
          required value={limit} disabled={busy} onChange={event => setLimit(event.target.value)} />
      </label>
      <label style={{ display: 'block', marginBottom: 16 }} htmlFor="utilization-reason">Reason for change
        <textarea id="utilization-reason" className="staffing-textarea" rows={3} maxLength={1000} required
          value={reason} disabled={busy} onChange={event => setReason(event.target.value)} />
      </label>
      <p className="staffing-muted">Saving activates a new policy version. Existing assignments and historical hours are not changed. People already above the limit cannot receive additional work in an affected week.</p>
      <div className="staffing-inline-actions"><Button variant="primary" type="submit" disabled={busy || !valid || !reason.trim() || Number(limit) === Number(policy.maximum_allocation_pct)}>{busy ? 'Saving…' : 'Save utilization limit'}</Button></div>
      <p className="staffing-muted"><small>Active policy: {policy.version}</small></p>
    </form>}
    <Button disabled={busy} onClick={() => { setMessage(''); setRefresh(value => value + 1); }}>Refresh setting</Button>
  </div>;
}
