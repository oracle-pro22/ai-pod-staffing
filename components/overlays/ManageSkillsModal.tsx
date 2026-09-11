'use client';

import { type FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import { DeliverableExperienceEditor } from '@/components/overlays/DeliverableExperienceEditor';
import { Button } from '@/components/ui/Button';
import { DropdownField } from '@/components/ui/DropdownField';
import { FormGroup, TextArea } from '@/components/ui/FormControls';
import { Modal } from '@/components/ui/Modal';
import { SkillCombobox } from '@/components/ui/SkillCombobox';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { assessmentDraft, fetchSelfSkills, saveSelfSkills, SkillsClientError, skillsDraftError, skillsPatch } from '@/lib/self-skills-client';
import type { SkillAssessmentInput, SelfSkillsProfile } from '@/types/self-skills';
import { deliverableDraft, deliverableExperienceError, deliverablePatch } from '@/lib/deliverable-experience';

export function ManageSkillsModal({ initial, canEdit, onClose, onSaved }: {
  initial: SelfSkillsProfile; canEdit: boolean; onClose: () => void; onSaved: () => void;
}) {
  const { state, notify } = useStaffingApp();
  const [profile, setProfile] = useState(initial);
  const [draft, setDraft] = useState(() => assessmentDraft(initial));
  const [deliverables, setDeliverables] = useState(() => deliverableDraft(initial));
  const [rephrasing, setRephrasing] = useState(false);
  const aiRequests = useRef(new Set<string>());
  const rephraseBusy = useCallback((id: string, active: boolean) => {
    if (active) aiRequests.current.add(id); else aiRequests.current.delete(id);
    setRephrasing(aiRequests.current.size > 0);
  }, []);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [needsReload, setNeedsReload] = useState(false);
  const [confirmation, setConfirmation] = useState<'close' | 'reload' | null>(null);
  const busy = useRef(false);
  const alive = useRef(true);
  const errorRef = useRef<HTMLDivElement>(null);
  const confirmationRef = useRef<HTMLDivElement>(null);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => { if (error) errorRef.current?.focus(); }, [error]);
  useEffect(() => { if (confirmation) confirmationRef.current?.focus(); }, [confirmation]);
  const patch = { ...skillsPatch(profile, draft), ...deliverablePatch(profile, deliverables) };
  const dirty = patch.upserts.length + patch.removeSkillIds.length + patch.deliverableUpserts.length + patch.removeDeliverableIds.length > 0;
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ''; };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  const disabled = saving || rephrasing || !canEdit;
  const names = new Map(profile.catalogue.map((row) => [row.skillId, row.name]));
  const change = (skillId: string, updates: Partial<SkillAssessmentInput>) => setDraft((rows) => rows.map((row) => row.skillId === skillId ? { ...row, ...updates } : row));
  const close = () => { if (!busy.current && !aiRequests.current.size) { if (dirty) setConfirmation('close'); else onClose(); } };

  async function reload() {
    if (busy.current || aiRequests.current.size) return;
    busy.current = true; setSaving(true);
    try {
      const latest = await fetchSelfSkills(state.role);
      if (!alive.current) return;
      setProfile(latest); setDraft(assessmentDraft(latest)); setDeliverables(deliverableDraft(latest)); setError(''); setNeedsReload(false); setConfirmation(null);
    } catch (failure) { if (alive.current) setError(failure instanceof Error ? failure.message : 'Unable to reload. Your draft is still here.'); }
    finally { busy.current = false; if (alive.current) setSaving(false); }
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (busy.current || aiRequests.current.size || disabled || needsReload || confirmation || !dirty) return;
    const message = skillsDraftError(profile, draft);
    if (message) { setError(message); return; }
    if (new Set(deliverables.map((row) => row.deliverableId)).size !== deliverables.length || deliverables.length > 100) {
      setError('Choose up to 100 distinct catalogue deliverables.'); return;
    }
    for (const row of patch.deliverableUpserts) {
      const item = profile.deliverableCatalogue.find((entry) => entry.deliverableId === row.deliverableId);
      const problem = !item ? 'Choose an active catalogue deliverable.' : deliverableExperienceError(row);
      if (problem) { setError(`${item?.name ?? row.deliverableId}: ${problem}`); return; }
    }
    busy.current = true; setSaving(true); setError('');
    try {
      const result = await saveSelfSkills(state.role, patch);
      if (result.personId !== profile.personId || result.version !== profile.version + 1) throw new SkillsClientError('The save response could not be confirmed. Reload saved skills before trying again.');
      if (!alive.current) return;
      notify('Profile updated', 'Your skills, deliverable experience, and interests have been saved.');
      onSaved();
    } catch (failure) {
      if (!alive.current) return;
      const status = failure instanceof SkillsClientError ? failure.status : 0;
      setNeedsReload(status === 0 || status === 409 || status === 403 || status === 401 || status === 503 || status >= 500);
      setError(failure instanceof Error ? failure.message : 'Save status is unknown. Reload saved skills before retrying.');
    } finally { busy.current = false; if (alive.current) setSaving(false); }
  }

  async function copyDraft() {
    try { await navigator.clipboard.writeText(JSON.stringify({ skills: draft.map((row) => ({ name: names.get(row.skillId), ...row })), deliverables }, null, 2)); notify('Draft copied', 'Your draft has been copied so you can refer to it after reloading.'); }
    catch { notify('Copy unavailable', 'Your browser did not allow copying. Your draft remains in this form.'); }
  }

  return <Modal open title="Manage my skills" description="Choose catalogue skills and deliverables, describe your experience, and share your interests."
    size="large" className="staffing-create-request-modal staffing-skills-modal" onClose={close}
    footerNote={dirty ? 'Unsaved changes' : 'All changes saved'}
    footer={<><Button onClick={close} disabled={saving || rephrasing}>Cancel</Button><Button type="submit" form="manageSkillsForm" variant="primary" disabled={disabled || needsReload || !!confirmation || !dirty}>{saving ? 'Please wait…' : 'Save changes'}</Button></>}>
    <form id="manageSkillsForm" onSubmit={save}>
      {!canEdit ? <p role="status">Your current profile does not have permission to edit these skills.</p> : null}
      {error ? <div ref={errorRef} tabIndex={-1} role="alert" className="staffing-skills-error"><b>{error}</b><p>Your draft has been kept below.</p>
        {needsReload ? <div className="staffing-actions"><Button type="button" onClick={copyDraft} disabled={saving}>Copy draft</Button><Button type="button" onClick={() => setConfirmation('reload')} disabled={saving}>Reload saved skills</Button></div> : null}
      </div> : null}
      {confirmation ? <div ref={confirmationRef} tabIndex={-1} className="staffing-skills-notice" role="alert"><b>{confirmation === 'close' ? 'Discard your unsaved changes?' : 'Replace this draft with the latest saved skills?'}</b><p>This only discards your local draft; it does not delete saved database records.</p>
        <div className="staffing-actions"><Button type="button" disabled={saving} onClick={() => setConfirmation(null)}>Keep draft</Button><Button type="button" disabled={saving} onClick={() => confirmation === 'close' ? onClose() : void reload()}>{confirmation === 'close' ? 'Discard and close' : 'Discard draft and reload'}</Button></div>
      </div> : null}
      <DeliverableExperienceEditor profile={profile} draft={deliverables} disabled={disabled || !!confirmation} onChange={setDeliverables} onBusyChange={rephraseBusy} />
      <section className="staffing-create-section">
        <div className="staffing-create-section-head"><h4>Skills and interests</h4><span>{draft.length} selected</span></div>
        <FormGroup label="Add a catalogue skill"><SkillCombobox options={profile.catalogue.filter((row) => !draft.some((item) => item.skillId === row.skillId))} disabled={disabled}
          onSelect={(skillId) => setDraft((rows) => rows.some((row) => row.skillId === skillId) ? rows : [...rows, { skillId, strength: null, interested: true, evidence: '' }])} /></FormGroup>
        <p className="staffing-muted">Search by name and select a result. New entries start as interest only; add a rating if you have experience.</p>
        <div className="staffing-skills-edit-list">
          {draft.length ? draft.map((row) => <fieldset key={row.skillId} className="staffing-skills-edit-card" disabled={disabled}>
            <legend>{names.get(row.skillId) ?? row.skillId}</legend>
            <div className="staffing-skills-edit-controls">
              <FormGroup label={`Proficiency — ${names.get(row.skillId) ?? row.skillId}`}><DropdownField value={row.strength === null ? '' : String(row.strength)} disabled={disabled}
                onChange={(value) => change(row.skillId, { strength: value ? Number(value) : null })}
                options={[{ value: '', label: 'Not rated — interest only' }, ...[1, 2, 3, 4, 5].map((value) => ({ value: String(value), label: `${value} / 5` })),
                  ...(row.strength !== null && !Number.isInteger(row.strength) ? [{ value: String(row.strength), label: `${row.strength} / 5 — existing rating` }] : [])]} /></FormGroup>
              <label className="staffing-skills-interest"><input type="checkbox" checked={row.interested} onChange={(event) => change(row.skillId, { interested: event.target.checked })} /> Interested in this skill</label>
              <Button type="button" onClick={() => setDraft((rows) => rows.filter((item) => item.skillId !== row.skillId))} aria-label={`Remove ${names.get(row.skillId) ?? row.skillId}`}>Remove</Button>
            </div>
            <FormGroup label={`Evidence${row.strength === null ? ' (optional)' : ' (required)'} — ${names.get(row.skillId) ?? row.skillId}`}><TextArea value={row.evidence} maxLength={2000} onChange={(event) => change(row.skillId, { evidence: event.target.value })} placeholder="Briefly describe relevant work or experience" /></FormGroup>
          </fieldset>) : <p className="staffing-skills-notice">No skills selected. Search the catalogue above to add your first skill or interest.</p>}
        </div>
        {patch.removeSkillIds.length ? <div className="staffing-skills-notice"><b>Removed from this draft</b>{patch.removeSkillIds.map((skillId) => <div className="staffing-actions" key={skillId}><span>{names.get(skillId) ?? skillId}</span><Button type="button" disabled={disabled} onClick={() => {
          const original = assessmentDraft(profile).find((row) => row.skillId === skillId);
          if (original) setDraft((rows) => [...rows, original]);
        }}>Undo removal</Button></div>)}</div> : null}
      </section>
      <section className="staffing-create-section">
        <div className="staffing-create-section-head"><h4>Role-based capabilities</h4><span>Read-only</span></div>
        <p>Project Manager comes from an assigned role. It cannot be added or rated here.</p>
        {profile.roleCapabilities.map((row) => <p className="staffing-skills-notice" key={row.skillId}>{row.name} — assigned through your role</p>)}
        {profile.warnings.map((warning) => <p className="staffing-muted" key={warning}>{warning}</p>)}
        {!profile.roleCapabilities.length && !profile.warnings.length ? <p className="staffing-muted">No role-based capabilities are currently assigned.</p> : null}
      </section>
    </form>
  </Modal>;
}
