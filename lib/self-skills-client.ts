import type { SkillAssessmentInput, SelfSkillsPatch, SelfSkillsProfile } from '@/types/self-skills';
import { staffingFetch } from '@/lib/staffing-fetch';
import type { StaffingRole } from '@/types/roles';

export class SkillsClientError extends Error {
  constructor(message: string, public status = 0) { super(message); }
}

async function skillsRequest<T>(role: StaffingRole, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await staffingFetch('/api/me/skills', { ...init, cache: 'no-store', headers: { 'Content-Type': 'application/json', 'x-staffing-role': role } });
  } catch {
    throw new SkillsClientError(init.method === 'PATCH' ? 'Save status is unknown. Reload saved skills before trying again.' : 'Skills could not be loaded. Check your connection and retry.');
  }
  const result = await response.json().catch(() => null) as { data?: T; error?: string } | null;
  if (!response.ok) throw new SkillsClientError(result?.error || 'Skills could not be processed. Please retry.', response.status);
  if (!result?.data) throw new SkillsClientError('The server response was incomplete. Reload saved skills before trying again.');
  return result.data;
}

export const fetchSelfSkills = (role: StaffingRole, signal?: AbortSignal) => skillsRequest<SelfSkillsProfile>(role, { signal });
export const saveSelfSkills = (role: StaffingRole, patch: SelfSkillsPatch) => skillsRequest<{ personId: string; version: number }>(role, { method: 'PATCH', body: JSON.stringify(patch) });

export function assessmentDraft(profile: SelfSkillsProfile): SkillAssessmentInput[] {
  return profile.skills.map(({ skillId, strength, interested, evidence }) => ({ skillId, strength, interested, evidence }));
}

export function skillsPatch(profile: SelfSkillsProfile, draft: SkillAssessmentInput[]): SelfSkillsPatch {
  const original = new Map(profile.skills.map((row) => [row.skillId, row]));
  const ids = new Set(draft.map((row) => row.skillId));
  return {
    version: profile.version,
    upserts: draft.map((row) => ({ ...row, evidence: row.evidence.trim() })).filter((row) => {
      const before = original.get(row.skillId);
      return !before || before.strength !== row.strength || before.interested !== row.interested || before.evidence.trim() !== row.evidence;
    }),
    removeSkillIds: profile.skills.filter((row) => !ids.has(row.skillId)).map((row) => row.skillId),
  };
}

export function skillsDraftError(profile: SelfSkillsProfile, draft: SkillAssessmentInput[]): string | null {
  const allowed = new Map(profile.catalogue.map((row) => [row.skillId, row.name]));
  if (new Set(draft.map((row) => row.skillId)).size !== draft.length) return 'Each skill can be added only once.';
  for (const row of skillsPatch(profile, draft).upserts) {
    const name = allowed.get(row.skillId);
    if (!name) return 'Choose a skill from the current catalogue.';
    if (row.strength !== null && (!Number.isInteger(row.strength) || row.strength < 1 || row.strength > 5)) return `${name}: choose a proficiency from 1 to 5.`;
    if (row.strength === null && !row.interested) return `${name}: choose a proficiency or mark your interest.`;
    if (row.strength !== null && !row.evidence) return `${name}: add a short evidence note for your rating.`;
    if (new TextEncoder().encode(row.evidence).length > 2000) return `${name}: shorten the evidence note (maximum 2,000 UTF-8 bytes).`;
  }
  return null;
}
