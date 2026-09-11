'use client';

import { AiRephraseTextarea } from '@/components/ui/AiRephraseTextarea';
import { Button } from '@/components/ui/Button';
import { DropdownField } from '@/components/ui/DropdownField';
import { FormGroup } from '@/components/ui/FormControls';
import { SkillCombobox } from '@/components/ui/SkillCombobox';
import { deliverableDraft, deliverablePatch } from '@/lib/deliverable-experience';
import { CONTRIBUTION_SCOPES, EXPERIENCE_LEVELS, type DeliverableExperienceInput, type SelfSkillsProfile } from '@/types/self-skills';

export function DeliverableExperienceEditor({ profile, draft, disabled, onChange, onBusyChange }: {
  profile: SelfSkillsProfile; draft: DeliverableExperienceInput[]; disabled: boolean;
  onChange: (rows: DeliverableExperienceInput[]) => void; onBusyChange: (id: string, busy: boolean) => void;
}) {
  const catalogue = profile.deliverableCatalogue ?? [];
  const saved = profile.deliverables ?? [];
  const describe = (id: string) => catalogue.find((row) => row.deliverableId === id) ?? saved.find((row) => row.deliverableId === id);
  const change = (id: string, changes: Partial<DeliverableExperienceInput>) => onChange(draft.map((row) => row.deliverableId === id ? { ...row, ...changes } : row));
  const removed = deliverablePatch(profile, draft).removeDeliverableIds;
  return <section className="staffing-create-section">
    <div className="staffing-create-section-head"><h4>Deliverables & experience</h4><span>{draft.length} selected</span></div>
    <p className="staffing-muted">Choose work you can deliver or want to learn. These entries do not change your skill ratings or role-based capabilities.</p>
    <FormGroup label="Add a catalogue deliverable"><SkillCombobox noun="deliverables" disabled={disabled || draft.length >= 100}
      options={catalogue.filter((row) => !draft.some((item) => item.deliverableId === row.deliverableId))
        .map((row) => ({ skillId: row.deliverableId, name: `${row.name} — ${row.projectName}` }))}
      onSelect={(deliverableId) => { if (!draft.some((row) => row.deliverableId === deliverableId)) onChange([...draft,
        { deliverableId, experienceLevel: 'LEARNING', contributionScope: 'CONTRIBUTOR', interested: true, experience: '' }]); }} /></FormGroup>
    <div className="staffing-skills-edit-list">
      {!draft.length ? <p className="staffing-skills-notice">No deliverables selected. Search the catalogue to add one.</p> : draft.map((row) => {
        const item = describe(row.deliverableId);
        const retired = !catalogue.some((entry) => entry.deliverableId === row.deliverableId);
        return <div className="staffing-skills-edit-card" key={row.deliverableId}>
          <div className="staffing-create-section-head"><div><h4>{item?.name ?? row.deliverableId}</h4><p className="staffing-muted">{item?.projectName}{retired ? ' · Retired — saved experience retained' : ''}</p></div>
            <Button type="button" disabled={disabled} onClick={() => onChange(draft.filter((entry) => entry.deliverableId !== row.deliverableId))} aria-label={`Remove ${item?.name ?? row.deliverableId}`}>Remove</Button></div>
          <div className="staffing-deliverable-experience-controls">
            <FormGroup label="Experience level"><DropdownField disabled={disabled || retired} value={row.experienceLevel}
              options={Object.entries(EXPERIENCE_LEVELS).map(([value, label]) => ({ value, label }))}
              onChange={(value) => change(row.deliverableId, { experienceLevel: value as DeliverableExperienceInput['experienceLevel'] })} /></FormGroup>
            <FormGroup label="Contribution scope"><DropdownField disabled={disabled || retired} value={row.contributionScope}
              options={Object.entries(CONTRIBUTION_SCOPES).map(([value, label]) => ({ value, label }))}
              onChange={(value) => change(row.deliverableId, { contributionScope: value as DeliverableExperienceInput['contributionScope'] })} /></FormGroup>
          </div>
          <label className="staffing-skills-interest"><input type="checkbox" disabled={disabled || retired} checked={row.interested}
            onChange={(event) => change(row.deliverableId, { interested: event.target.checked })} /> Interested in this deliverable</label>
          <FormGroup label={`Experience${row.experienceLevel === 'LEARNING' ? ' (optional)' : ' (required)'}`}>
            <AiRephraseTextarea field="deliverableExperience" value={row.experience} disabled={disabled || retired} maxLength={8000}
              context={{ deliverables: [item?.name ?? row.deliverableId], projectType: item?.projectName }}
              onChange={(experience) => change(row.deliverableId, { experience })}
              onBusyChange={(_field, busy) => onBusyChange(row.deliverableId, busy)}
              placeholder="Describe work you contributed to, what you did, and any support you needed" />
          </FormGroup>
        </div>;
      })}
    </div>
    {removed.length ? <div className="staffing-skills-notice"><b>Deliverables removed from this draft</b>{removed.map((id) => <div className="staffing-actions" key={id}>
      <span>{describe(id)?.name ?? id}</span><Button type="button" disabled={disabled} onClick={() => {
        const original = deliverableDraft(profile).find((row) => row.deliverableId === id);
        if (original) onChange([...draft, original]);
      }}>Undo removal</Button></div>)}</div> : null}
  </section>;
}
