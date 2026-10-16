'use client';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { DropdownField, type DropdownOption } from '@/components/ui/DropdownField';
import { SkillCombobox } from '@/components/ui/SkillCombobox';
import { staffingFetch } from '@/lib/staffing-fetch';
import { onboardingDateIssue } from '@/lib/onboarding-validation';
import type { OnboardingState } from '@/types/onboarding';

type Skill = { skill_id: string; strength: number | null; interested: boolean; evidence: string };
type Experience = { deliverable_id: string; experience_level: string; contribution_scope: string; interested: boolean; experience: string };
type Work = { kind: string; title: string; starts_on: string; ends_on: string; total_hours: string; role_code: string | null };

const PROFICIENCY_OPTIONS: DropdownOption[] = [
  { value: '', label: 'Not rated — interest only' },
  ...[1, 2, 3, 4, 5].map(value => ({ value: String(value), label: `${value} / 5` })),
];
const EXPERIENCE_OPTIONS: DropdownOption[] = [
  { value: 'LEARNING', label: 'Learning' },
  { value: 'SUPPORTED', label: 'Supported' },
  { value: 'INDEPENDENT', label: 'Independent' },
  { value: 'MENTOR', label: 'Mentor' },
];
const CONTRIBUTION_OPTIONS: DropdownOption[] = [
  { value: 'CONTRIBUTOR', label: 'Contributor' },
  { value: 'END_TO_END', label: 'End to end' },
];
const WORK_TYPE_OPTIONS: DropdownOption[] = [
  { value: 'EXTERNAL', label: 'External commitment' },
  { value: 'LEAVE', label: 'Leave' },
  { value: 'POD', label: 'Existing POD work' },
];

function RosterDropdown({ label, value, options, onChange, disabled = false }: {
  label: string; value: string; options: DropdownOption[]; onChange: (value: string) => void; disabled?: boolean;
}) {
  return <div className="roster-field-group"><span>{label}</span><DropdownField aria-label={label} value={value}
    options={options} onChange={onChange} disabled={disabled} /></div>;
}

export function deliverableOptionLabel(item: { deliverable_name: string; project_name?: string; display_name?: string }) {
  if (item.display_name?.trim()) return item.display_name.trim();
  const project = item.project_name?.trim();
  return project ? `${item.deliverable_name} — ${project}` : item.deliverable_name;
}

export function OnboardingEntry({ initial, sessionKey }: { initial: OnboardingState; sessionKey: string }) {
  const today = new Date().toISOString().slice(0, 10);
  const future = new Date(Date.now() + 76 * 86400000).toISOString().slice(0, 10);
  const [start, setStart] = useState(today), [end, setEnd] = useState(future);
  const [skills, setSkills] = useState<Skill[]>([]), [experiences, setExperiences] = useState<Experience[]>([]);
  const [work, setWork] = useState<Work[]>([]), [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const [step, setStep] = useState(0);
  const errorRef = useRef<HTMLParagraphElement>(null);
  const dateIssue = onboardingDateIssue(start, end, work);
  useEffect(() => { if (error) errorRef.current?.focus(); }, [error]);
  const staffingRoles = initial.staffing_roles ?? [];
  async function signOut() {
    try {
      const response = await staffingFetch('/api/auth/logout', { method: 'POST' });
      if (!response.ok) throw new Error('Sign out failed. Please try again.');
      window.location.assign('/');
    } catch (e) { setError(e instanceof Error ? e.message : 'Unable to sign out.'); }
  }
  async function submit(event: FormEvent) {
    event.preventDefault(); if (busy) return;
    if (skills.some(skill => skill.strength !== null && !skill.evidence.trim())) {
      setError('Describe your experience with each rated skill. No documents or approval are required.'); setStep(0); return;
    }
    if (dateIssue) { setError(dateIssue.message); setStep(1); return; }
    setBusy(true); setError('');
    try {
      const response = await staffingFetch('/api/agentic/onboarding', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ revision: initial.revision, starts_on: start, ends_on: end, confirmed,
          skills, deliverables: experiences, work: work.map(w => ({ ...w, total_hours: Number(w.total_hours) })) }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error?.message || result.error || 'Setup could not be saved. Check the entries.');
      window.location.assign('/');
    } catch (e) { setError(e instanceof Error ? e.message : 'Unable to save setup.'); setBusy(false); }
  }
  return <main className="roster-entry">
    <meta name="staffing-persona-session" content={sessionKey} />
    <header><div><strong>AI Pod Staffing</strong><span>Welcome, {initial.full_name}</span></div><button type="button" onClick={signOut}>Sign out</button></header>
    <section className="roster-panel">
      <p className="roster-eyebrow">FIRST-LOGIN SETUP</p>
      <h1>Build your staffing profile</h1>
      <form onSubmit={submit}>
        <p>We calculate allocation from dated hours, not an estimated percentage. Your contracted schedule starts at <strong>8 hours/day · 40 hours/week</strong>.</p>
        <nav aria-label="Setup steps">{['Skills & experience', 'Current work & leave', 'Review & confirm'].map((label, i) => <button type="button" key={label} aria-current={step === i ? 'step' : undefined} onClick={() => setStep(i)}>{i + 1}. {label}</button>)}</nav>
        {error && <p id="setup-error" role="alert" tabIndex={-1} ref={errorRef} className="roster-error">{error}</p>}
        {step === 0 && <>
          <h2>Skills</h2><p>Choose skills you have experience in or want to use in future work. Interest is only a small preference signal; it does not change your proficiency or qualify you for a required skill.</p>
          <label>Add a skill<SkillCombobox disabled={busy} options={(initial.skills ?? []).filter(s => !skills.some(x => x.skill_id === s.interest_id)).map(s => ({ skillId: s.interest_id, name: s.interest_name }))}
            onSelect={skillId => setSkills([...skills, { skill_id: skillId, strength: null, interested: true, evidence: '' }])} /></label>
          {skills.map((s, i) => <fieldset key={s.skill_id}><legend>{initial.skills?.find(x => x.interest_id === s.skill_id)?.interest_name}</legend>
            <div className="roster-fields"><RosterDropdown label="Proficiency" value={s.strength === null ? '' : String(s.strength)} options={PROFICIENCY_OPTIONS}
              onChange={value => setSkills(skills.map((v, n) => n === i ? { ...v, strength: value ? Number(value) : null, interested: value ? v.interested : true } : v))} />
              <label className="roster-check"><input type="checkbox" checked={s.interested} disabled={s.strength === null} onChange={e => setSkills(skills.map((v, n) => n === i ? { ...v, interested: e.target.checked } : v))} /> Interested in future work using this skill</label></div>
            <p className="roster-help">{s.strength === null ? 'No proficiency is claimed. This entry records future-work interest only.' : 'This preference is considered separately from your proficiency rating.'}</p>
            <label>{s.strength === null ? 'Learning goal (optional)' : 'Your experience with this skill (required)'}<input required={s.strength !== null} maxLength={2000} value={s.evidence} onChange={e => setSkills(skills.map((v, n) => n === i ? { ...v, evidence: e.target.value } : v))} /></label>
            {s.strength !== null && <p className="roster-help">Briefly describe how you have used this skill. No documents or approval are required.</p>}
            <button type="button" onClick={() => setSkills(skills.filter((_, n) => n !== i))}>Remove skill</button></fieldset>)}
          <h2>Deliverable experience</h2>
          <label>Add a deliverable<SkillCombobox noun="deliverables" disabled={busy} options={(initial.deliverables ?? []).filter(d => !experiences.some(x => x.deliverable_id === d.deliverable_id))
            .map(d => ({ skillId: d.deliverable_id, name: deliverableOptionLabel(d) }))}
            onSelect={deliverableId => setExperiences([...experiences, { deliverable_id: deliverableId, experience_level: 'LEARNING', contribution_scope: 'CONTRIBUTOR', interested: true, experience: '' }])} /></label>
          {experiences.map((d, i) => { const item = initial.deliverables?.find(x => x.deliverable_id === d.deliverable_id); return <fieldset key={d.deliverable_id}><legend>{item?.deliverable_name}{item?.project_name ? <small>{item.project_name}</small> : null}</legend>
            <div className="roster-fields"><RosterDropdown label="Experience level" value={d.experience_level} options={EXPERIENCE_OPTIONS}
              onChange={value => setExperiences(experiences.map((v, n) => n === i ? { ...v, experience_level: value } : v))} />
              <RosterDropdown label="Contribution" value={d.contribution_scope} options={CONTRIBUTION_OPTIONS}
                onChange={value => setExperiences(experiences.map((v, n) => n === i ? { ...v, contribution_scope: value } : v))} /></div>
            <label>Describe your experience<textarea maxLength={8000} value={d.experience} onChange={e => setExperiences(experiences.map((v, n) => n === i ? { ...v, experience: e.target.value } : v))} /></label>
            <label className="roster-interest-choice"><input type="checkbox" checked={d.interested} onChange={e => setExperiences(experiences.map((v, n) => n === i ? { ...v, interested: e.target.checked } : v))} />
              <span><strong>Consider me for future work with this deliverable</strong><small>This is a preference only. Your experience level is recorded separately.</small></span></label>
            <button type="button" onClick={() => setExperiences(experiences.filter((_, n) => n !== i))}>Remove deliverable</button></fieldset>; })}
        </>}
        {step === 1 && <>
          <h2>Availability confirmation period</h2><p>Choose the period you are confirming, starting today and covering up to 13 complete weeks. Your normal 40-hour weekly schedule applies throughout this period. Any planned work or leave you add below must fall within these dates.</p>
          <div className="roster-fields"><label>Period starts<input type="date" value={start} onChange={e => setStart(e.target.value)} /></label><label>Period ends<input type="date" value={end} onChange={e => setEnd(e.target.value)} /></label></div>
          <h2>Planned work and leave within this period</h2><p>Add each existing commitment or leave period that affects your availability. Give each entry its own dates and total hours; hours are spread across weekdays. Use separate entries for uneven schedules. If you add no entries, you are confirming that none are already planned within this period.</p>
          {work.map((w, i) => <fieldset key={i}><legend>Entry {i + 1}</legend>
            <RosterDropdown label="Type" value={w.kind} options={WORK_TYPE_OPTIONS.filter(option => option.value !== 'POD' || staffingRoles.length > 0)}
              onChange={value => setWork(work.map((v, n) => n === i ? { ...v, kind: value, role_code: value === 'POD' ? staffingRoles[0] ?? null : null } : v))} />
            <label>Work / leave title<input value={w.title} maxLength={500} onChange={e => setWork(work.map((v, n) => n === i ? { ...v, title: e.target.value } : v))} /></label>
            <div className="roster-fields"><label>Start<input type="date" value={w.starts_on} aria-invalid={Boolean(error && dateIssue?.entryIndex === i)} aria-describedby={error && dateIssue?.entryIndex === i ? 'setup-error' : undefined} onChange={e => setWork(work.map((v, n) => n === i ? { ...v, starts_on: e.target.value } : v))} /></label><label>End<input type="date" value={w.ends_on} aria-invalid={Boolean(error && dateIssue?.entryIndex === i)} aria-describedby={error && dateIssue?.entryIndex === i ? 'setup-error' : undefined} onChange={e => setWork(work.map((v, n) => n === i ? { ...v, ends_on: e.target.value } : v))} /></label><label>Total hours<input type="number" min="0.01" step="0.01" value={w.total_hours} onChange={e => setWork(work.map((v, n) => n === i ? { ...v, total_hours: e.target.value } : v))} /></label></div>
            {w.kind === 'POD' && <RosterDropdown label="Your existing POD role" value={w.role_code ?? ''}
              options={staffingRoles.map(role => ({ value: role, label: role === 'POD_LEAD' ? 'Lead' : 'Member' }))}
              onChange={value => setWork(work.map((v, n) => n === i ? { ...v, role_code: value } : v))} />}
            <button type="button" onClick={() => setWork(work.filter((_, n) => n !== i))}>Remove entry</button></fieldset>)}
          <button type="button" disabled={work.length >= 40} onClick={() => setWork([...work, { kind: 'EXTERNAL', title: '', starts_on: start, ends_on: end, total_hours: '', role_code: null }])}>＋ Add work or leave</button>
        </>}
        {step === 2 && <>
          <h2>Review your details</h2><p>{skills.length} skill assessments · {experiences.length} deliverable assessments · {work.length} dated work/leave entries.</p>
          <p>Availability confirmation period: <strong>{start} – {end}</strong>. Contracted capacity: <strong>40 hours/week</strong>.</p>
          <ul>{work.map((w, i) => <li key={i}>{w.title || '(Missing title)'} — {w.kind}, {w.total_hours || '0'} total hours, {w.starts_on} to {w.ends_on}</li>)}</ul>
          {work.some(w => w.kind === 'POD') && <p className="roster-notice">Existing POD work is saved as self-reported workload and counts toward your capacity immediately. It does not create a project assignment or increase the active-POD count by itself.</p>}
          <label className="roster-check"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} /> I reviewed my skills, experience, current work and leave. Empty sections mean I have nothing to record.</label>
        </>}
        <footer>{step > 0 && <button type="button" disabled={busy} onClick={() => setStep(step - 1)}>Back</button>}{step < 2 ? <button type="button" className="roster-primary" onClick={() => {
          if (step === 1 && dateIssue) { setError(dateIssue.message); return; }
          setError(''); setStep(step + 1);
        }}>Continue</button> : <button type="submit" className="roster-primary" disabled={!confirmed || busy}>{busy ? 'Saving…' : 'Confirm and save profile'}</button>}</footer>
      </form>
    </section>
  </main>;
}
