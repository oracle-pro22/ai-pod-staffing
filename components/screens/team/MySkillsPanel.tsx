'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ManageSkillsModal } from '@/components/overlays/ManageSkillsModal';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { useStaffingApp } from '@/context/StaffingAppProvider';
import { canPerform } from '@/lib/role-policy';
import { fetchSelfSkills } from '@/lib/self-skills-client';
import { CONTRIBUTION_SCOPES, EXPERIENCE_LEVELS, type SelfSkillsProfile } from '@/types/self-skills';

export function MySkillsPanel() {
  const { state, data } = useStaffingApp();
  const router = useRouter();
  const [profile, setProfile] = useState<SelfSkillsProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [open, setOpen] = useState(false);
  const request = useRef<AbortController | null>(null);
  const canEdit = canPerform(state.role, 'MY_SKILLS', 'canCreate', data.authorization) && canPerform(state.role, 'MY_SKILLS', 'canUpdate', data.authorization);
  const load = useCallback(async () => {
    request.current?.abort();
    const controller = new AbortController(); request.current = controller;
    setLoading(true); setError('');
    try {
      const result = await fetchSelfSkills(state.role, controller.signal);
      if (!controller.signal.aborted) setProfile(result);
    } catch (failure) { if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : 'Could not load your skills.'); }
    finally { if (!controller.signal.aborted) setLoading(false); }
  }, [state.role]);
  useEffect(() => { void load(); return () => request.current?.abort(); }, [load, data]);
  return <>
    <Card><CardHeader><div><h3>My skills & interests</h3><p>Skills, deliverable experience, and interests from your Oracle profile.</p></div>
      <Button variant="primary" disabled={loading || !!error || !profile} onClick={() => setOpen(true)}>Manage my skills</Button>
    </CardHeader><CardBody>
      {loading ? <p role="status">Loading your skills…</p> : error ? <div role="alert"><p>{error}</p><Button onClick={() => void load()}>Retry</Button></div> : profile ? <>
        {!profile.skills.length ? <p>No skills or interests added yet. Select Manage my skills to get started.</p> : profile.skills.map((row) => <div className="staffing-self-skill-row" key={row.skillId}>
          <div><b>{row.name}</b><p>{row.evidence || 'No evidence note recorded.'}</p><small>{row.source}</small></div>
          <div className="staffing-self-skill-labels"><span>{row.strength === null ? 'Not rated' : `${row.strength} / 5`}</span>{row.interested ? <span>Interested</span> : null}</div>
        </div>)}
        <h4>Deliverables & experience</h4>
        {!profile.deliverables?.length ? <p className="staffing-muted">No deliverable experience added yet.</p> : profile.deliverables.map((row) => <div className="staffing-self-skill-row" key={row.deliverableId}>
          <div><b>{row.name}</b><small>{row.projectName}{!row.active ? ' · Retired' : ''}</small><p>{row.experience || 'No experience note recorded.'}</p><small>{CONTRIBUTION_SCOPES[row.contributionScope]}</small></div>
          <div className="staffing-self-skill-labels"><span>{EXPERIENCE_LEVELS[row.experienceLevel]}</span>{row.interested ? <span>Interested</span> : null}</div>
        </div>)}
        <h4>Role-based capabilities</h4>
        {profile.roleCapabilities.map((row) => <p key={row.skillId}>{row.name} <span className="staffing-muted">— assigned through your role · Read-only</span></p>)}
        {profile.warnings.map((warning) => <p key={warning} className="staffing-muted">{warning}</p>)}
        {!profile.roleCapabilities.length && !profile.warnings.length ? <p className="staffing-muted">No role-based capabilities assigned.</p> : null}
      </> : null}
    </CardBody></Card>
    {open && profile ? <ManageSkillsModal initial={profile} canEdit={canEdit} onClose={() => setOpen(false)} onSaved={() => { setOpen(false); void load(); router.refresh(); }} /> : null}
  </>;
}
