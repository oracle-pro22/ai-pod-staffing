'use client';
import { useState, type FormEvent } from 'react';
import { SkillCombobox } from '@/components/ui/SkillCombobox';
import { staffingFetch } from '@/lib/staffing-fetch';
import type { OnboardingState } from '@/types/onboarding';

type Skill = { skill_id: string; strength: number | null; interested: boolean; evidence: string };
type Experience = { deliverable_id: string; experience_level: string; contribution_scope: string; interested: boolean; experience: string };
type Work = { kind: string; title: string; starts_on: string; ends_on: string; total_hours: string; role_code: string | null };

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
        {step === 0 && <>
          <h2>Skills</h2><p>Choose skills you have experience in or want to use in future work. Interest is only a small preference signal; it does not change your proficiency or qualify you for a required skill.</p>
          <label>Add a skill<SkillCombobox disabled={busy} options={(initial.skills ?? []).filter(s => !skills.some(x => x.skill_id === s.interest_id)).map(s => ({ skillId: s.interest_id, name: s.interest_name }))}
            onSelect={skillId => setSkills([...skills, { skill_id: skillId, strength: null, interested: true, evidence: '' }])} /></label>
          {skills.map((s, i) => <fieldset key={s.skill_id}><legend>{initial.skills?.find(x => x.interest_id === s.skill_id)?.interest_name}</legend>
            <div className="roster-fields"><label>Proficiency<select value={s.strength ?? ''} onChange={e => setSkills(skills.map((v, n) => n === i ? { ...v, strength: e.target.value ? Number(e.target.value) : null, interested: e.target.value ? v.interested : true } : v))}>
                <option value="">Not rated — interest only</option>{[1, 2, 3, 4, 5].map(value => <option key={value} value={value}>{value} / 5</option>)}</select></label>
              <label className="roster-check"><input type="checkbox" checked={s.interested} disabled={s.strength === null} onChange={e => setSkills(skills.map((v, n) => n === i ? { ...v, interested: e.target.checked } : v))} /> Interested in future work using this skill</label></div>
            <p className="roster-help">{s.strength === null ? 'No proficiency is claimed. This entry records future-work interest only.' : 'This preference is considered separately from your proficiency rating.'}</p>
            <label>{s.strength === null ? 'Evidence or learning goal (optional)' : 'Evidence supporting this proficiency (optional)'}<input maxLength={2000} value={s.evidence} onChange={e => setSkills(skills.map((v, n) => n === i ? { ...v, evidence: e.target.value } : v))} /></label>
            <button type="button" onClick={() => setSkills(skills.filter((_, n) => n !== i))}>Remove skill</button></fieldset>)}
          <h2>Deliverable experience</h2>
          <label>Add a deliverable<SkillCombobox noun="deliverables" disabled={busy} options={(initial.deliverables ?? []).filter(d => !experiences.some(x => x.deliverable_id === d.deliverable_id))
            .map(d => ({ skillId: d.deliverable_id, name: deliverableOptionLabel(d) }))}
            onSelect={deliverableId => setExperiences([...experiences, { deliverable_id: deliverableId, experience_level: 'LEARNING', contribution_scope: 'CONTRIBUTOR', interested: true, experience: '' }])} /></label>
          {experiences.map((d, i) => { const item = initial.deliverables?.find(x => x.deliverable_id === d.deliverable_id); return <fieldset key={d.deliverable_id}><legend>{item?.deliverable_name}{item?.project_name ? <small>{item.project_name}</small> : null}</legend>
            <div className="roster-fields"><label>Experience level<select value={d.experience_level} onChange={e => setExperiences(experiences.map((v, n) => n === i ? { ...v, experience_level: e.target.value } : v))}>{['LEARNING', 'SUPPORTED', 'INDEPENDENT', 'MENTOR'].map(v => <option key={v}>{v}</option>)}</select></label>
              <label>Contribution<select value={d.contribution_scope} onChange={e => setExperiences(experiences.map((v, n) => n === i ? { ...v, contribution_scope: e.target.value } : v))}><option value="CONTRIBUTOR">Contributor</option><option value="END_TO_END">End to end</option></select></label></div>
            <label>Describe your experience<textarea maxLength={8000} value={d.experience} onChange={e => setExperiences(experiences.map((v, n) => n === i ? { ...v, experience: e.target.value } : v))} /></label>
            <label className="roster-check"><input type="checkbox" checked={d.interested} onChange={e => setExperiences(experiences.map((v, n) => n === i ? { ...v, interested: e.target.checked } : v))} /> Interested in this deliverable</label>
            <button type="button" onClick={() => setExperiences(experiences.filter((_, n) => n !== i))}>Remove deliverable</button></fieldset>; })}
        </>}
        {step === 1 && <>
          <h2>Confirm your planning period</h2><p>Include today, up to 13 complete weeks. Capacity outside this period stays unknown until refreshed.</p>
          <div className="roster-fields"><label>From<input type="date" value={start} onChange={e => setStart(e.target.value)} /></label><label>Through<input type="date" value={end} onChange={e => setEnd(e.target.value)} /></label></div>
          <h2>Work and leave already planned</h2><p>Enter total hours across each date range. Hours are spread across weekdays. For uneven schedules, use separate entries. No entries means you confirm no existing work or leave in this period.</p>
          {work.map((w, i) => <fieldset key={i}><legend>Entry {i + 1}</legend>
            <label>Type<select value={w.kind} onChange={e => setWork(work.map((v, n) => n === i ? { ...v, kind: e.target.value, role_code: e.target.value === 'POD' ? staffingRoles[0] ?? null : null } : v))}><option value="EXTERNAL">External commitment</option><option value="LEAVE">Leave</option><option value="POD" disabled={!staffingRoles.length}>Existing POD work</option></select></label>
            <label>Work / leave title<input value={w.title} maxLength={500} onChange={e => setWork(work.map((v, n) => n === i ? { ...v, title: e.target.value } : v))} /></label>
            <div className="roster-fields"><label>Start<input type="date" value={w.starts_on} onChange={e => setWork(work.map((v, n) => n === i ? { ...v, starts_on: e.target.value } : v))} /></label><label>End<input type="date" value={w.ends_on} onChange={e => setWork(work.map((v, n) => n === i ? { ...v, ends_on: e.target.value } : v))} /></label><label>Total hours<input type="number" min="0.01" step="0.01" value={w.total_hours} onChange={e => setWork(work.map((v, n) => n === i ? { ...v, total_hours: e.target.value } : v))} /></label></div>
            {w.kind === 'POD' && <label>Your existing POD role<select value={w.role_code ?? ''} onChange={e => setWork(work.map((v, n) => n === i ? { ...v, role_code: e.target.value } : v))}>{staffingRoles.map(role => <option key={role} value={role}>{role === 'POD_LEAD' ? 'Lead' : 'Member'}</option>)}</select></label>}
            <button type="button" onClick={() => setWork(work.filter((_, n) => n !== i))}>Remove entry</button></fieldset>)}
          <button type="button" disabled={work.length >= 40} onClick={() => setWork([...work, { kind: 'EXTERNAL', title: '', starts_on: start, ends_on: end, total_hours: '', role_code: null }])}>＋ Add work or leave</button>
        </>}
        {step === 2 && <>
          <h2>Review your details</h2><p>{skills.length} skill assessments · {experiences.length} deliverable assessments · {work.length} dated work/leave entries.</p>
          <p>Confirmed period: <strong>{start} – {end}</strong>. Contracted capacity: <strong>40 hours/week</strong>.</p>
          <ul>{work.map((w, i) => <li key={i}>{w.title || '(Missing title)'} — {w.kind}, {w.total_hours || '0'} total hours, {w.starts_on} to {w.ends_on}</li>)}</ul>
          {work.some(w => w.kind === 'POD') && <p className="roster-notice">Existing POD work is saved as self-reported workload and counts toward your capacity immediately. It does not create a project assignment or increase the active-POD count by itself.</p>}
          <label className="roster-check"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} /> I reviewed my skills, experience, current work and leave. Empty sections mean I have nothing to record.</label>
        </>}
        {error && <p role="alert" className="roster-error">{error}</p>}
        <footer>{step > 0 && <button type="button" disabled={busy} onClick={() => setStep(step - 1)}>Back</button>}{step < 2 ? <button type="button" className="roster-primary" onClick={() => setStep(step + 1)}>Continue</button> : <button type="submit" className="roster-primary" disabled={!confirmed || busy}>{busy ? 'Saving…' : 'Confirm and save profile'}</button>}</footer>
      </form>
    </section>
  </main>;
}
