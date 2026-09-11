import { CONTRIBUTION_SCOPES, EXPERIENCE_LEVELS, type DeliverableExperienceInput, type SelfSkillsProfile } from '@/types/self-skills';

export function deliverableExperienceError(row: DeliverableExperienceInput): string | null {
  if (!Object.hasOwn(EXPERIENCE_LEVELS, row.experienceLevel)) return 'Choose a valid experience level.';
  if (!Object.hasOwn(CONTRIBUTION_SCOPES, row.contributionScope)) return 'Choose your contribution scope.';
  if (typeof row.interested !== 'boolean') return 'Specify your interest in this deliverable.';
  if (typeof row.experience !== 'string' || row.experience.length > 8000) return 'Experience must be text, up to 8,000 characters.';
  if (row.experienceLevel !== 'LEARNING' && !row.experience.trim()) return 'Describe your experience for this level.';
  if (row.experienceLevel === 'LEARNING' && !row.interested) return 'Mark your interest when choosing Interested in learning.';
  return null;
}

export function deliverableDraft(profile: SelfSkillsProfile): DeliverableExperienceInput[] {
  return (profile.deliverables ?? []).map(({ deliverableId, experienceLevel, contributionScope, interested, experience }) =>
    ({ deliverableId, experienceLevel, contributionScope, interested, experience }));
}

export function deliverablePatch(profile: SelfSkillsProfile, draft: DeliverableExperienceInput[]) {
  const original = new Map(deliverableDraft(profile).map((row) => [row.deliverableId, row]));
  const ids = new Set(draft.map((row) => row.deliverableId));
  return {
    deliverableUpserts: draft.map((row) => ({ ...row, experience: row.experience.trim() })).filter((row) => {
      const before = original.get(row.deliverableId);
      return !before || before.experienceLevel !== row.experienceLevel || before.contributionScope !== row.contributionScope
        || before.interested !== row.interested || before.experience.trim() !== row.experience;
    }),
    removeDeliverableIds: [...original.keys()].filter((id) => !ids.has(id)),
  };
}
