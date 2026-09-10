import 'server-only';

import oracledb, { type Connection } from 'oracledb';

import { withOracleTransaction } from '@/lib/db/oracle';
import { conflictError, forbiddenError, validationError } from '@/lib/errors/staffing-api-error';
import { ROLE_CODES } from '@/types/roles';
import type {
  AvailabilityCreatedResult,
  CreateAvailabilityPayload,
  CreateRequestPayload,
  RequestCreatedResult,
  StaffingMutationContext,
} from '@/types/mutations';

type Row = Record<string, unknown>;

const objectRows = { outFormat: oracledb.OUT_FORMAT_OBJECT } as const;

function text(row: Row, key: string): string {
  const value = row[key.toUpperCase()];
  return value === null || value === undefined ? '' : String(value).trim();
}

function number(row: Row, key: string): number {
  const result = Number(row[key.toUpperCase()]);
  return Number.isFinite(result) ? result : 0;
}

async function rows(connection: Connection, sql: string, binds: Record<string, unknown> = {}): Promise<Row[]> {
  const result = await connection.execute<Row>(sql, binds, objectRows);
  return result.rows ?? [];
}

async function authorizeCreate(
  connection: Connection,
  context: StaffingMutationContext,
  resourceCode: 'REQUESTS' | 'MY_AVAILABILITY',
): Promise<'FULL' | 'SCOPED' | 'OWN'> {
  const permission = (await rows(connection, `
    SELECT rp.access_scope, rp.can_view, rp.can_create
      FROM app_roles ar
      JOIN role_permissions rp ON rp.role_code = ar.role_code
     WHERE ar.role_name = :roleName
       AND ar.role_code = :roleCode
       AND ar.active_flag = 'Y'
       AND rp.resource_code = :resourceCode
  `, { roleName: context.role, roleCode: ROLE_CODES[context.role], resourceCode }))[0];

  const scope = text(permission ?? {}, 'access_scope');
  if (text(permission ?? {}, 'can_view') !== 'Y' || text(permission ?? {}, 'can_create') !== 'Y' || !['FULL', 'SCOPED', 'OWN'].includes(scope)) throw forbiddenError();
  return scope === 'FULL' || scope === 'SCOPED' ? scope : 'OWN';
}

function placeholders(prefix: string, values: string[]): { sql: string; binds: Record<string, string> } {
  const binds: Record<string, string> = {};
  const sql = values.map((value, index) => {
    const key = `${prefix}${index}`;
    binds[key] = value;
    return `:${key}`;
  }).join(', ');
  return { sql, binds };
}

function effortHours(value: number, unit: string): number {
  return value * ({ HOURS: 1, DAYS: 8, WEEKS: 40, MONTHS: 160 }[unit] ?? 1);
}

function podCounts(value: string): { leads: number; contributors: number } {
  const match = value.match(/^(\d+)\s+leads?\s*\+\s*(\d+)\s+contributors?$/i);
  if (!match) throw validationError('Requested pod size is not valid.');
  return { leads: Number(match[1]), contributors: Number(match[2]) };
}

export async function createStaffingRequest(
  input: CreateRequestPayload,
  context: StaffingMutationContext,
): Promise<RequestCreatedResult> {
  return withOracleTransaction(async (connection) => {
    await authorizeCreate(connection, context, 'REQUESTS');

    const project = (await rows(connection, `
      SELECT project_type_id, project_name, project_description, source_version
        FROM project_types
       WHERE project_type_id = :projectTypeId
    `, { projectTypeId: input.projectTypeId }))[0];
    if (!project) throw validationError('The selected project type is no longer available.');

    const requestSourcePerson = (await rows(connection, `
      SELECT person_id, full_name
        FROM people
       WHERE person_id = :personId
         AND active_flag = 'Y'
    `, { personId: input.requestSourcePersonId }))[0];
    if (!requestSourcePerson) throw validationError('The selected request source is no longer available.');
    const requestSourceName = text(requestSourcePerson, 'full_name');

    const mappedDeliverables = input.deliverables.filter((item) => !item.custom);
    const mappedDeliverableIds = [...new Set(mappedDeliverables.map((item) => item.id))];
    let catalogueDeliverables: Row[] = [];
    if (mappedDeliverableIds.length) {
      const selected = placeholders('deliverable', mappedDeliverableIds);
      catalogueDeliverables = await rows(connection, `
        SELECT deliverable_id, deliverable_name, customer_note
          FROM deliverables
         WHERE project_type_id = :projectTypeId
           AND active_flag = 'Y'
           AND deliverable_id IN (${selected.sql})
      `, { projectTypeId: input.projectTypeId, ...selected.binds });
      if (catalogueDeliverables.length !== mappedDeliverableIds.length) {
        throw validationError('A selected deliverable has been retired or does not belong to this project type. Refresh the catalogue and select it again.');
      }
    }
    const catalogueDeliverablesById = new Map(catalogueDeliverables.map((row) => [text(row, 'deliverable_id'), row]));
    const storedDeliverables = input.deliverables.map((item, index) => {
      const mapped = catalogueDeliverablesById.get(item.id);
      return item.custom
        ? { id: `CUSTOM-DEL-${index + 1}`, name: item.name, note: item.note, custom: true }
        : { id: item.id, name: text(mapped ?? {}, 'deliverable_name'), note: text(mapped ?? {}, 'customer_note'), custom: false };
    });

    const mappedCapabilities = input.requiredCapabilities.filter((item) => !item.custom);
    const mappedCapabilityIds = [...new Set(mappedCapabilities.map((item) => item.id))];
    let catalogueCapabilities: Row[] = [];
    if (mappedCapabilityIds.length) {
      const selected = placeholders('capability', mappedCapabilityIds);
      catalogueCapabilities = await rows(connection, `
        SELECT interest_id, interest_name
          FROM interests
         WHERE interest_id IN (${selected.sql})
      `, selected.binds);
      if (catalogueCapabilities.length !== mappedCapabilityIds.length) {
        throw validationError('One or more selected capabilities are no longer available.');
      }
    }
    const catalogueCapabilitiesById = new Map(catalogueCapabilities.map((row) => [text(row, 'interest_id'), row]));

    const mappedLinks = new Map<string, string>();
    if (mappedDeliverableIds.length && mappedCapabilityIds.length) {
      const deliverableBinds = placeholders('linkedDeliverable', mappedDeliverableIds);
      const capabilityBinds = placeholders('linkedCapability', mappedCapabilityIds);
      const links = await rows(connection, `
        SELECT deliverable_id, skill_id
          FROM deliverable_skills
         WHERE deliverable_id IN (${deliverableBinds.sql})
           AND skill_id IN (${capabilityBinds.sql})
      `, { ...deliverableBinds.binds, ...capabilityBinds.binds });
      for (const link of links) {
        const skillId = text(link, 'skill_id');
        if (!mappedLinks.has(skillId)) mappedLinks.set(skillId, text(link, 'deliverable_id'));
      }
    }

    const sequence = (await rows(connection, 'SELECT request_id_seq.NEXTVAL AS next_value FROM dual'))[0];
    const requestId = `REQ-${number(sequence ?? {}, 'next_value')}`;
    const unit = input.estimatedEffort.unit.toUpperCase();
    const counts = podCounts(input.requestedPodSize);
    const firstMapped = storedDeliverables.find((item) => !item.custom);
    const firstDeliverable = storedDeliverables[0];
    const skills = input.requiredCapabilities.map((item) => item.custom ? item.name : text(catalogueCapabilitiesById.get(item.id) ?? {}, 'interest_name')).join(', ');
    if (skills.length > 1000) throw validationError('The combined capability names are too long.');

    await connection.execute(`
      INSERT INTO requests (
        request_id, title, project_type_id, project_type, deliverable_id, deliverable,
        deliverables_json, skills_type_of_work, owner_name, request_source, request_source_person_id,
        project_description, needed_by, estimated_start_date, estimated_completion_date,
        estimated_effort_value, estimated_effort_unit, estimated_hours,
        requested_lead_count, requested_contributor_count, priority, status,
        business_context, business_objectives, expected_outcomes, mapping_version,
        created_by, updated_by
      ) VALUES (
        :requestId, :title, :projectTypeId, :projectType, :deliverableId, :deliverable,
        :deliverablesJson, :skills, :ownerName, :requestSource, :requestSourcePersonId,
        :projectDescription, TO_DATE(:neededBy, 'YYYY-MM-DD'),
        TO_DATE(:startDate, 'YYYY-MM-DD'),
        TO_DATE(:completionDate, 'YYYY-MM-DD'),
        :effortValue, :effortUnit, :estimatedHours,
        :leadCount, :contributorCount, :priority, 'NEEDS_RECOMMENDATION',
        :businessContext, :businessObjectives, :expectedOutcomes, :mappingVersion,
        :createdBy, :updatedBy
      )
    `, {
      requestId,
      title: input.title,
      projectTypeId: input.projectTypeId,
      projectType: text(project, 'project_name'),
      deliverableId: firstMapped?.id ?? null,
      deliverable: firstDeliverable?.name ?? null,
      deliverablesJson: JSON.stringify(storedDeliverables),
      skills,
      ownerName: requestSourceName,
      requestSource: requestSourceName,
      requestSourcePersonId: input.requestSourcePersonId,
      projectDescription: input.projectDescription || text(project, 'project_description'),
      neededBy: input.neededBy,
      startDate: input.estimatedStartDate || null,
      completionDate: input.estimatedCompletionDate || null,
      effortValue: input.estimatedEffort.value,
      effortUnit: unit,
      estimatedHours: effortHours(input.estimatedEffort.value, unit),
      leadCount: counts.leads,
      contributorCount: counts.contributors,
      priority: input.priority.toUpperCase(),
      businessContext: input.businessObjectives,
      businessObjectives: input.businessObjectives,
      expectedOutcomes: input.expectedOutcomes || null,
      mappingVersion: text(project, 'source_version'),
      createdBy: context.actor,
      updatedBy: context.actor,
    });

    for (const [index, capability] of input.requiredCapabilities.entries()) {
      const mapped = catalogueCapabilitiesById.get(capability.id);
      const linkedDeliverableId = capability.custom ? null : mappedLinks.get(capability.id) ?? null;
      const capabilitySource = capability.custom ? 'CUSTOM' : linkedDeliverableId ? 'MAPPED' : 'CATALOGUE';
      const skillName = capability.custom ? capability.name : text(mapped ?? {}, 'interest_name');
      await connection.execute(`
        INSERT INTO requirements (
          request_id, deliverable_id, interest_id, skill_name, custom_capability_name,
          capability_source, required_strength, display_order, requirement_source,
          source_version, created_by
        ) VALUES (
          :requestId, :deliverableId, :interestId, :skillName, :customCapabilityName,
          :capabilitySource, :requiredStrength, :displayOrder, :requirementSource,
          :sourceVersion, :createdBy
        )
      `, {
        requestId,
        deliverableId: linkedDeliverableId,
        interestId: capability.custom ? null : capability.id,
        skillName,
        customCapabilityName: capability.custom ? capability.name : null,
        capabilitySource,
        requiredStrength: capability.requiredStrength,
        displayOrder: index + 1,
        requirementSource: capability.custom ? 'Request entry' : linkedDeliverableId ? 'Customer catalogue' : 'Customer taxonomy',
        sourceVersion: text(project, 'source_version'),
        createdBy: context.actor,
      });
    }

    return { requestId };
  });
}

export async function createAvailabilityEvent(
  input: CreateAvailabilityPayload,
  context: StaffingMutationContext,
): Promise<AvailabilityCreatedResult> {
  return withOracleTransaction(async (connection) => {
    await authorizeCreate(connection, context, 'MY_AVAILABILITY');
    const person = (await rows(connection, `
      SELECT person_id
        FROM people
       WHERE person_id = :personId
         AND active_flag = 'Y'
    `, { personId: input.personId }))[0];
    if (!person) throw validationError('The selected person is no longer available.');

    try {
      await connection.execute(`
        INSERT INTO availability (
          person_id, event_type, starts_on, ends_on, title, allocated_hours, created_by
        ) VALUES (
          :personId, :eventType, TO_DATE(:startsOn, 'YYYY-MM-DD'),
          TO_DATE(:endsOn, 'YYYY-MM-DD'), :title, :allocatedHours, :createdBy
        )
      `, { ...input, createdBy: context.actor });
    } catch (error) {
      if (error instanceof Error && /ORA-00001/.test(error.message)) {
        throw conflictError('This availability event is already recorded.');
      }
      throw error;
    }

    return input;
  });
}
