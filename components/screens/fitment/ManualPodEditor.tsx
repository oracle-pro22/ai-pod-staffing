'use client';
import { useState } from 'react';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { PersonCombobox } from '@/components/ui/PersonCombobox';
import type { Member } from './LiveStaffingReview';

export type ManualSlot = { person_id: string; role: 'POD_LEAD' | 'POD_MEMBER'; manual: boolean };
export type ManualPerson = { person_id: string; full_name: string; role_code: string };

export function manualPeopleForSlot(people: ManualPerson[], draft: ManualSlot[], slotIndex: number) {
  const slot = draft[slotIndex];
  const selectedElsewhere = new Set(draft.filter((_, index) => index !== slotIndex).map(row => row.person_id).filter(Boolean));
  return [...new Map(people
    .filter(person => slot.role === 'POD_LEAD' ? person.role_code === 'POD_LEAD' : ['POD_MEMBER', 'POD_LEAD'].includes(person.role_code))
    .filter(person => person.person_id === slot.person_id || !selectedElsewhere.has(person.person_id))
    .map(person => [person.person_id, person])).values()];
}

export function ManualPodEditor({ people, selected, slots, leadCount, memberCount, busy, onClose, onPreview }: {
  people: ManualPerson[]; selected: Member[]; slots?: ManualSlot[]; leadCount: number; memberCount: number;
  busy: boolean; onClose: () => void; onPreview: (slots: ManualSlot[]) => void;
}) {
  const [draft, setDraft] = useState<ManualSlot[]>(() => slots ?? [
    ...Array.from({ length: leadCount }, (_, i) => ({ person_id: selected.filter(m => m.role_in_pod === 'POD_LEAD')[i]?.person_id ?? '', role: 'POD_LEAD' as const, manual: !selected.length })),
    ...Array.from({ length: memberCount }, (_, i) => ({ person_id: selected.filter(m => m.role_in_pod === 'POD_MEMBER')[i]?.person_id ?? '', role: 'POD_MEMBER' as const, manual: !selected.length })),
  ]);
  const allSelected = draft.every(slot => slot.person_id);
  const uniquePeople = new Set(draft.map(slot => slot.person_id).filter(Boolean)).size === draft.length;
  const manualCount = draft.filter(slot => slot.manual).length;
  const valid = allSelected && uniquePeople && manualCount > 0;
  const readiness = !allSelected ? 'Choose a person for every POD role.'
    : !uniquePeople ? 'Choose a different person for each POD role.'
    : !manualCount ? 'Change a person or mark at least one existing choice as a manual override.'
    : `${manualCount} manual override${manualCount === 1 ? '' : 's'} ready for allocation preview.`;
  return <Modal open title="Captain manual override"
    description="Choose the exact people for this POD. Changing a person automatically marks that role as a manual override."
    className="staffing-manual-override-modal" onClose={onClose} footer={<>
    <Button disabled={busy} onClick={onClose}>Cancel</Button>
    <Button variant="primary" disabled={busy || !valid} onClick={() => onPreview(draft)}>{busy ? 'Calculating…' : 'Calculate preview'}</Button>
  </>}>
    <div className="staffing-manual-policy"><span aria-hidden="true">!</span><div>
      <b>Manual limit: 100% POD allocation</b>
      <p>Includes existing POD assignments. Manual choices bypass skill matching, leave and external commitments, while roles, working hours and total effort remain enforced.</p>
    </div></div>
    <div className="staffing-manual-slots">{draft.map((slot, i) => {
      const eligible = manualPeopleForSlot(people, draft, i).map(person => ({
        id: person.person_id,
        name: person.full_name,
      }));
      const original = selected.some(m => m.person_id === slot.person_id && m.role_in_pod === slot.role && m.source !== 'MANUAL');
      const roleSlot = draft.slice(0, i + 1).filter(row => row.role === slot.role).length;
      const slotTitle = slot.role === 'POD_LEAD'
        ? (leadCount > 1 ? `POD Lead ${roleSlot}` : 'POD Lead')
        : (memberCount > 1 ? `POD Member ${roleSlot}` : 'POD Member');
      return <div className="staffing-manual-slot" key={`${slot.role}-${roleSlot}`}>
        <div className="staffing-manual-slot-head"><div><span>{slot.role === 'POD_LEAD' ? 'Lead role' : 'Contributor role'}</span><b>{slotTitle}</b></div>
          <label className={`staffing-manual-check${slot.manual ? ' active' : ''}`}>
            <input type="checkbox" checked={slot.manual} disabled={busy || !original}
              onChange={event => setDraft(rows => rows.map((row, index) => index === i ? { ...row, manual: event.target.checked } : row))} />
            <span>Manual override</span>
          </label></div>
        <label className="staffing-manual-person"><span>Person</span>
          <PersonCombobox aria-label={`Manual ${slot.role} slot ${i + 1}`} disabled={busy} people={eligible}
            value={slot.person_id} placeholder="Search by name or ID"
            onChange={personId => setDraft(rows => rows.map((row, index) => index === i ? { ...row, person_id: personId, manual: true } : row))} />
        </label>
      </div>;
    })}</div>
    <div className={`staffing-manual-readiness${valid ? ' ready' : ''}`} role="status"><span aria-hidden="true">{valid ? '✓' : 'i'}</span>{readiness}</div>
  </Modal>;
}
