import { validationError } from '@/lib/errors/staffing-api-error';
import type { DeliverableExperienceInput, SelfSkillsPatch } from '@/types/self-skills';
import { deliverableExperienceError } from '@/lib/deliverable-experience';

function object(value: unknown, keys: string[]): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw validationError('Expected a JSON object.');
  const result = value as Record<string, unknown>;
  if (Object.keys(result).some((key) => !keys.includes(key))) throw validationError('Unexpected field in skills request.');
  return result;
}
function skillId(value: unknown): string {
  if (typeof value !== 'string' || !/^[A-Za-z0-9_-]{1,30}$/.test(value)) throw validationError('Choose a valid catalogue skill.');
  return value;
}

export function validateSelfSkillsPatch(value: unknown): SelfSkillsPatch {
  const body = object(value, ['version', 'upserts', 'removeSkillIds', 'deliverableUpserts', 'removeDeliverableIds']);
  if (!Number.isSafeInteger(body.version) || Number(body.version) < 0 || Number(body.version) >= 9999999999) {
    throw validationError('Provide the profile version returned by GET /api/me/skills.');
  }
  const upserts = body.upserts ?? [];
  const removals = body.removeSkillIds ?? [];
  const deliveries = body.deliverableUpserts ?? [];
  const removedDeliveries = body.removeDeliverableIds ?? [];
  if (!Array.isArray(upserts) || !Array.isArray(removals) || !Array.isArray(deliveries) || !Array.isArray(removedDeliveries)
    || upserts.length + removals.length + deliveries.length + removedDeliveries.length < 1
    || upserts.length + removals.length + deliveries.length + removedDeliveries.length > 200) {
    throw validationError('Send between 1 and 200 profile changes.');
  }
  const deliveryIds = new Set<string>();
  const uniqueDeliveryId = (value: unknown) => {
    const id = skillId(value);
    if (deliveryIds.has(id)) throw validationError('A deliverable can appear only once in a save.');
    deliveryIds.add(id);
    return id;
  };
  const seen = new Set<string>();
  function uniqueId(value: unknown) {
    const id = skillId(value);
    if (seen.has(id)) throw validationError('A skill can appear only once in a save.');
    seen.add(id);
    return id;
  }
  return {
    version: Number(body.version),
    upserts: upserts.map((item) => {
      const row = object(item, ['skillId', 'strength', 'interested', 'evidence']);
      const id = uniqueId(row.skillId);
      if (row.strength !== null && (typeof row.strength !== 'number' || !Number.isInteger(row.strength) || row.strength < 1 || row.strength > 5)) {
        throw validationError('Choose a whole-number proficiency from 1 to 5, or null for interest only.');
      }
      if (typeof row.interested !== 'boolean') throw validationError('Specify whether you are interested in the skill.');
      if (row.strength === null && !row.interested) throw validationError('Select an interest or provide a proficiency rating.');
      if (row.evidence !== undefined && typeof row.evidence !== 'string') throw validationError('Evidence must be text.');
      const evidence = String(row.evidence ?? '').trim();
      // Existing Oracle column uses byte semantics; avoid a late ORA-12899 for Unicode input.
      if (Buffer.byteLength(evidence, 'utf8') > 2000) throw validationError('Evidence must fit within 2,000 UTF-8 bytes.');
      if (row.strength !== null && !evidence) throw validationError('Add a short evidence note for a proficiency rating.');
      return { skillId: id, strength: row.strength as number | null, interested: row.interested, evidence };
    }),
    removeSkillIds: removals.map(uniqueId),
    deliverableUpserts: deliveries.map((item) => {
      const row = object(item, ['deliverableId', 'experienceLevel', 'contributionScope', 'interested', 'experience']);
      const id = uniqueDeliveryId(row.deliverableId);
      const input = { ...row, deliverableId: id } as DeliverableExperienceInput;
      const error = deliverableExperienceError(input);
      if (error) throw validationError(error);
      return { ...input, experience: input.experience.trim() };
    }),
    removeDeliverableIds: removedDeliveries.map(uniqueDeliveryId),
  };
}
