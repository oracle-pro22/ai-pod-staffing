'use client';

import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { staffingFetch } from '@/lib/staffing-fetch';

type Document = { content: string; revision: number; updated_by_name: string | null; updated_at: string | null };
const endpoint = '/api/agentic/admin/enhancements';

async function payload(response: Response) {
  const result = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof result?.error === 'string' ? result.error
    : result?.error?.message || 'The notepad could not be loaded or saved. Your draft has not been cleared.');
  const value = result?.data;
  if (!value || typeof value.content !== 'string' || !Number.isInteger(value.revision) || value.revision < 1) {
    throw new Error('Unexpected notepad response. Your draft has not been cleared. Refresh to check the saved version.');
  }
  return value as Document;
}

export function EnhancementNotepad({ canEdit, onDirtyChange }: {
  canEdit: boolean; onDirtyChange: (dirty: boolean) => void;
}) {
  const [saved, setSaved] = useState<Document | null>(null);
  const [draft, setDraft] = useState('');
  const [latest, setLatest] = useState<Document | null>(null);
  const [retainedDraft, setRetainedDraft] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const inFlight = useRef(false);
  const mounted = useRef(true);
  const dirty = saved !== null && draft !== saved.content;

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    staffingFetch(endpoint, { cache: 'no-store', signal: controller.signal }).then(payload).then(value => {
      if (!controller.signal.aborted) { setSaved(value); setDraft(value.content); }
    }).catch(e => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : 'Unable to load notes.'); })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => { mounted.current = false; controller.abort(); };
  }, []);

  useEffect(() => {
    const unsaved = dirty || conflict || retainedDraft !== null;
    onDirtyChange(unsaved);
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    if (unsaved) window.addEventListener('beforeunload', warn);
    return () => { onDirtyChange(false); window.removeEventListener('beforeunload', warn); };
  }, [dirty, conflict, retainedDraft, onDirtyChange]);

  async function refresh(preserveDraft = false) {
    if (inFlight.current || busy) return;
    if (!preserveDraft && (dirty || retainedDraft !== null)
      && !window.confirm('Discard your unsaved draft and load the latest saved notes?')) return;
    inFlight.current = true; setBusy(true); setError(''); setMessage('');
    try {
      const value = await payload(await staffingFetch(endpoint, { cache: 'no-store' }));
      if (!mounted.current) return;
      if (preserveDraft) setLatest(value);
      else { setSaved(value); setDraft(value.content); setLatest(null); setConflict(false); setRetainedDraft(null); }
    } catch (e) { if (mounted.current) setError(e instanceof Error ? e.message : 'Unable to refresh notes.'); }
    finally { inFlight.current = false; if (mounted.current) setBusy(false); }
  }

  async function save() {
    if (!saved || !dirty || busy || inFlight.current || conflict || !canEdit || draft.length > 50000) return;
    inFlight.current = true; setBusy(true); setError(''); setMessage('');
    try {
      const response = await staffingFetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: draft, expected_revision: saved.revision }) });
      if (!mounted.current) return;
      if (response.status === 409) {
        setConflict(true);
        setError('Another administrator saved changes. Your draft is preserved below. Review the latest version before saving.');
        const value = await payload(await staffingFetch(endpoint, { cache: 'no-store' }));
        if (mounted.current) setLatest(value);
        return;
      }
      const value = await payload(response);
      if (!mounted.current) return;
      setSaved(value); setDraft(value.content); setLatest(null); setRetainedDraft(null);
      setMessage('Enhancement notes saved. Other administrators can load them using Refresh.');
    } catch (e) { if (mounted.current) setError(e instanceof Error ? e.message : 'Save failed. Your draft is still available.'); }
    finally { inFlight.current = false; if (mounted.current) setBusy(false); }
  }

  return <div>
    <h3>Shared enhancement notepad</h3>
    <p className="staffing-muted">A shared space for future features and suggestions. All administrators can edit these notes. Save before leaving this page.</p>
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 16, margin: '16px 0' }}>
      {saved && <p className="staffing-muted" style={{ margin: 0 }}>{saved.updated_at
        ? `Last saved by ${saved.updated_by_name || 'Administrator'} · ${new Date(saved.updated_at).toLocaleString()}`
        : 'No notes saved yet.'}</p>}
      <div className="staffing-inline-actions" style={{ marginLeft: 'auto', flexWrap: 'wrap' }}>
        {canEdit && <Button variant="primary" disabled={!saved || !dirty || busy || conflict || draft.length > 50000}
          onClick={() => void save()}>{busy && saved ? 'Please wait…' : 'Save changes'}</Button>}
        <Button disabled={busy} onClick={() => void refresh()}>Refresh</Button>
      </div>
    </div>
    {error && <p role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}
    {!saved && busy && <p role="status">Loading shared notes…</p>}
    {saved && <>
      <label htmlFor="enhancement-notes">{conflict ? 'Your unsaved draft' : 'Enhancement ideas'}</label>
      <textarea id="enhancement-notes" className="staffing-textarea" rows={16} maxLength={50000}
        style={{ width: '100%', minHeight: 320, resize: 'vertical', lineHeight: 1.6, marginTop: 8 }}
        placeholder={'Ideas for future improvements…\n\n• Describe the feature\n• Explain why it would help'}
        value={draft} readOnly={!canEdit} disabled={busy} onChange={e => setDraft(e.target.value)} />
      <p className="staffing-muted" role="status">{draft.length.toLocaleString()} / 50,000 characters · {dirty ? 'Unsaved changes' : 'No unsaved changes'}</p>
      {conflict && <section aria-label="Resolve editing conflict">
        {latest ? <>
          <label htmlFor="enhancement-latest">Latest saved notes — {latest.updated_by_name || 'Administrator'}</label>
          <textarea id="enhancement-latest" className="staffing-textarea" rows={8} value={latest.content} readOnly style={{ width: '100%' }} />
          <p>Start from the latest version, then copy any missing ideas from your retained draft. Nothing is overwritten until you save.</p>
          <Button disabled={busy} onClick={() => {
            setRetainedDraft(draft); setSaved(latest); setDraft(latest.content); setLatest(null); setConflict(false); setError('');
          }}>Edit latest version</Button>
        </> : <Button disabled={busy} onClick={() => void refresh(true)}>Load latest without losing my draft</Button>}
      </section>}
      {retainedDraft !== null && <details open style={{ margin: '16px 0' }}>
        <summary>Your previous draft — copy any ideas you want to keep</summary>
        <textarea aria-label="Retained previous draft" className="staffing-textarea" rows={8} value={retainedDraft} readOnly style={{ width: '100%' }} />
      </details>}
    </>}
  </div>;
}
