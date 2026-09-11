import 'server-only';
import oracledb, { type Connection } from 'oracledb';
import { StaffingApiError, validationError } from '@/lib/errors/staffing-api-error';
import { deliverableExperienceError } from '@/lib/deliverable-experience';
import type { DeliverableExperienceInput, SelfSkillsPatch } from '@/types/self-skills';

type StoredExperience = DeliverableExperienceInput & { name: string; projectName: string; updatedAt: string; updatedBy: string; source: string };
type Row = Record<string, unknown>;
const options = { outFormat: oracledb.OUT_FORMAT_OBJECT } as const;

// Fail closed for malformed storage: never replace an unreadable profile with an empty one.
export function readDeliverableExperience(value: unknown): StoredExperience[] {
  if (value == null) return [];
  try {
    if (typeof value !== 'string') throw new Error();
    const rows: unknown = JSON.parse(value);
    if (!Array.isArray(rows) || rows.length > 100) throw new Error();
    const ids = new Set<string>();
    for (const row of rows) {
      if (!row || typeof row !== 'object' || typeof row.deliverableId !== 'string' || !/^[A-Za-z0-9_-]{1,30}$/.test(row.deliverableId)
        || ids.has(row.deliverableId) || deliverableExperienceError(row)
        || !['name', 'projectName', 'updatedAt', 'updatedBy', 'source'].every((key) => typeof row[key] === 'string')) throw new Error();
      ids.add(row.deliverableId);
    }
    return rows as StoredExperience[];
  } catch {
    throw new StaffingApiError('Saved deliverable experience needs administrator review. No changes were saved.', 409, 'INVALID_DELIVERABLE_PROFILE');
  }
}

export async function readDeliverableCatalogue(connection: Connection) {
  const result = await connection.execute<Row>(`
    SELECT deliverable_id, deliverable_name, project_name, active_flag
      FROM deliverables ORDER BY deliverable_name, project_name, deliverable_id
  `, {}, options);
  return (result.rows ?? []).map((row) => ({ deliverableId: String(row.DELIVERABLE_ID), name: String(row.DELIVERABLE_NAME),
    projectName: String(row.PROJECT_NAME ?? ''), active: row.ACTIVE_FLAG === 'Y' }));
}

export async function saveDeliverableExperience(connection: Connection, personId: string, stored: unknown, patch: SelfSkillsPatch, actor: string) {
  const upserts = patch.deliverableUpserts ?? [];
  const removals = patch.removeDeliverableIds ?? [];
  if (!upserts.length && !removals.length) return;
  const entries = new Map(readDeliverableExperience(stored).map((row) => [row.deliverableId, row]));
  for (const row of [...upserts].sort((a, b) => a.deliverableId.localeCompare(b.deliverableId))) {
    const binds = { deliverableId: row.deliverableId };
    await connection.execute(`SELECT /*+ NO_PARALLEL */ deliverable_id FROM deliverables WHERE deliverable_id = :deliverableId FOR UPDATE WAIT 5`, binds, options);
    // Fresh read after any lock wait; retired entries may be retained or removed, not newly assessed.
    const result = await connection.execute<Row>(`SELECT deliverable_name, project_name, active_flag FROM deliverables WHERE deliverable_id = :deliverableId`, binds, options);
    const catalogue = result.rows?.[0];
    if (!catalogue || catalogue.ACTIVE_FLAG !== 'Y') throw validationError('Choose an active catalogue deliverable. Retired entries can only be kept or removed.');
    entries.set(row.deliverableId, { ...row, name: String(catalogue.DELIVERABLE_NAME), projectName: String(catalogue.PROJECT_NAME ?? ''),
      source: 'Self-assessment', updatedAt: new Date().toISOString(), updatedBy: actor });
  }
  for (const id of removals) {
    if (!entries.has(id)) throw validationError('The deliverable to remove is not in your saved profile.');
    entries.delete(id);
  }
  if (entries.size > 100) throw validationError('A profile can contain at most 100 deliverables.');
  await connection.execute(`
    UPDATE /*+ DISABLE_PARALLEL_DML NO_PARALLEL */ people SET deliverable_experience_json = :experienceJson
     WHERE person_id = :personId
  `, { personId, experienceJson: { val: JSON.stringify([...entries.values()]), type: oracledb.CLOB } });
}
