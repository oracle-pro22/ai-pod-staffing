import 'server-only';
import { EMPLOYEE_SCOPE_SQL } from '@/lib/repositories/employee-scope';

import oracledb, { type Connection } from 'oracledb';

import { withOracleTransaction } from '@/lib/db/oracle';
import { conflictError, forbiddenError, validationError } from '@/lib/errors/staffing-api-error';
import { PREVIEW_PERSON_IDS } from '@/lib/preview-person-ids';
import { contextPermissions } from '@/lib/auth/context-permissions';
import { ACTIVE_IDENTITY_ACCOUNT_SQL } from '@/lib/auth/identity-mapping';
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
  const permission = (await contextPermissions(connection, context, resourceCode)).find(row =>
    text(row, 'can_view') === 'Y' && text(row, 'can_create') === 'Y'
    && (resourceCode !== 'MY_AVAILABILITY' || text(row, 'access_scope') === 'OWN'));

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
    if (context.responsibleCaptainId) {
      await connection.execute('ALTER SESSION DISABLE PARALLEL DML');
      await connection.execute('ALTER SESSION DISABLE PARALLEL QUERY');
      const schema = (await rows(connection, `SELECT USER AS schema_user, SYS_CONTEXT('USERENV','CURRENT_SCHEMA') AS current_schema FROM dual`))[0];
      if (text(schema ?? {}, 'schema_user') !== 'AI_POD_STAFFING' || text(schema ?? {}, 'current_schema') !== 'AI_POD_STAFFING') throw forbiddenError('Unexpected database schema.');
      const linked = await rows(connection, `SELECT ur.person_id FROM app_user_roles ur
        JOIN people p ON p.person_id=ur.person_id AND p.active_flag='Y'
        WHERE ur.identity_subject=:identitySubject AND ur.person_id=:personId AND ur.role_code='POD_CAPTAIN'
        AND ur.active_flag='Y' AND ur.effective_from<=TRUNC(SYSDATE)
        AND (ur.effective_to IS NULL OR ur.effective_to>=TRUNC(SYSDATE)) AND ${ACTIVE_IDENTITY_ACCOUNT_SQL}`,
        { identitySubject: context.actor, personId: context.responsibleCaptainId });
      if (linked.length !== 1 || (!context.authenticated && context.role !== 'POD Captain')) throw forbiddenError();
      if (!input.estimatedStartDate || !input.estimatedCompletionDate) throw validationError('Provide both planned start and completion dates for staffing.');
    }

    const project = (await rows(connection, `
      SELECT project_type_id, project_name, project_description, source_version
        FROM project_types
       WHERE project_type_id = :projectTypeId
    `, { projectTypeId: input.projectTypeId }))[0];
    if (!project) throw validationError('The selected project type is no longer available.');

    const requestSourcePerson = (await rows(connection, `
      SELECT person_id, full_name
        FROM people p
       WHERE person_id = :personId
         AND active_flag = 'Y'
         AND ${EMPLOYEE_SCOPE_SQL}
    `, { personId: input.requestSourcePersonId }))[0];
    if (!requestSourcePerson) throw validationError('The selected request source is no longer available.');
    const requestSourceName = text(requestSourcePerson, 'full_name');

    const normalizeCatalogueName = (value: string) => value.toLocaleLowerCase('en-US').replace(/[^a-z0-9]+/g, ' ').trim();
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
    const allProjectDeliverables = await rows(connection, `SELECT deliverable_id,deliverable_name,customer_note
      FROM deliverables WHERE project_type_id=:projectTypeId AND active_flag = 'Y'`, { projectTypeId: input.projectTypeId });
    const catalogueDeliverablesById = new Map(allProjectDeliverables.map((row) => [text(row, 'deliverable_id'), row]));
    const catalogueDeliverablesByName = new Map(allProjectDeliverables.map((row) => [normalizeCatalogueName(text(row, 'deliverable_name')), row]));
    const storedDeliverables = input.deliverables.map((item, index) => {
      const exact = item.custom ? catalogueDeliverablesByName.get(normalizeCatalogueName(item.name)) : undefined;
      const mapped = exact ?? catalogueDeliverablesById.get(item.id);
      return item.custom && !exact
        ? { id: `CUSTOM-DEL-${index + 1}`, name: item.name, note: item.note, custom: true, resolution: 'REQUEST_SCOPED' }
        : item.custom
          ? { id: text(mapped ?? {}, 'deliverable_id'), name: text(mapped ?? {}, 'deliverable_name'), note: text(mapped ?? {}, 'customer_note'), custom: false,
              requestedName: item.name, resolution: 'EXACT_NAME' }
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
    const allCatalogueCapabilities = await rows(connection, `SELECT interest_id,interest_name
      FROM interests`);
    const catalogueCapabilitiesById = new Map(allCatalogueCapabilities.map((row) => [text(row, 'interest_id'), row]));
    const catalogueCapabilitiesByName = new Map(allCatalogueCapabilities.map((row) => [normalizeCatalogueName(text(row, 'interest_name')), row]));
    const resolvedCapabilities = input.requiredCapabilities.map((item) => {
      const exact = item.custom ? catalogueCapabilitiesByName.get(normalizeCatalogueName(item.name)) : undefined;
      return exact ? { ...item, id: text(exact, 'interest_id'), name: text(exact, 'interest_name'), custom: false,
        originalName: item.name, resolution: 'EXACT_NAME', mandatory: true } : item;
    });
    if (!resolvedCapabilities.some((item) => !item.custom && item.mandatory !== false)) {
      throw validationError('Add at least one catalogue capability. New “Other” capabilities remain unverified preferences until they can be mapped safely.');
    }

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
    const skills = resolvedCapabilities.map((item) => item.custom ? item.name : text(catalogueCapabilitiesById.get(item.id) ?? {}, 'interest_name')).join(', ');
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

    for (const [index, capability] of resolvedCapabilities.entries()) {
      const mapped = catalogueCapabilitiesById.get(capability.id);
      const linkedDeliverableId = capability.custom ? null : mappedLinks.get(capability.id) ?? null;
      const capabilitySource = capability.custom ? 'CUSTOM' : linkedDeliverableId ? 'MAPPED' : 'CATALOGUE';
      const skillName = capability.custom ? capability.name : text(mapped ?? {}, 'interest_name');
      await connection.execute(`
        INSERT INTO requirements (
          request_id, deliverable_id, interest_id, skill_name, custom_capability_name,
          capability_source, required_strength, mandatory_flag, display_order, requirement_source,
          source_version, created_by
        ) VALUES (
          :requestId, :deliverableId, :interestId, :skillName, :customCapabilityName,
          :capabilitySource, :requiredStrength, :mandatoryFlag, :displayOrder, :requirementSource,
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
        mandatoryFlag: capability.mandatory === false ? 'N' : 'Y',
        displayOrder: index + 1,
        requirementSource: capability.resolution === 'EXACT_NAME'
          ? `Request entry; exact catalogue match for “${capability.originalName}”`.slice(0, 250)
          : capability.custom ? 'Request entry; unverified preference' : linkedDeliverableId ? 'Customer catalogue' : 'Customer taxonomy',
        sourceVersion: text(project, 'source_version'),
        createdBy: context.actor,
      });
    }

    if (context.responsibleCaptainId) {
      // Saved with requirements in the SAME transaction. The worker reconciles this durable intent after commit.
      await connection.execute(`UPDATE requests SET responsible_captain_id=:captainId,agent_enabled='Y'
        WHERE request_id=:requestId`, { captainId: context.responsibleCaptainId, requestId });
      return { requestId, agentPending: true };
    }
    return { requestId };
  });
}

export async function createAvailabilityEvent(
  input: CreateAvailabilityPayload,
  context: StaffingMutationContext,
): Promise<AvailabilityCreatedResult> {
  return withOracleTransaction(async (connection) => {
    const scope = await authorizeCreate(connection, context, 'MY_AVAILABILITY');
    if (scope !== 'OWN' || (!context.authenticated && (!['POD Lead', 'POD Member'].includes(context.role)
      || context.actor !== `PREVIEW:${context.role.toUpperCase().replaceAll(' ', '_')}`))) throw forbiddenError();
    const ownPersonId = context.authenticated ? context.personId : context.role === 'POD Lead' ? PREVIEW_PERSON_IDS.podLeadPersonId : PREVIEW_PERSON_IDS.podMemberPersonId;
    if (input.personId !== ownPersonId) throw forbiddenError('You can only add availability for your own profile.');
    const person = (await rows(connection, `
      SELECT person_id
        FROM people
       WHERE person_id = :personId
         AND active_flag = 'Y'
    `, { personId: input.personId }))[0];
    if (!person) throw validationError('The selected person is no longer available.');

    if (context.authenticated) {
      await connection.execute('ALTER SESSION DISABLE PARALLEL DML');
      await connection.execute('ALTER SESSION DISABLE PARALLEL QUERY');
      await connection.execute('SELECT person_id FROM people WHERE person_id=:personId FOR UPDATE WAIT 5', { personId: ownPersonId });
      await authorizeCreate(connection, context, 'MY_AVAILABILITY');
    }

    try {
      await connection.execute(`
        INSERT INTO availability (
            person_id, event_type, starts_on, ends_on, title, allocated_hours, created_by${context.authenticated ? ', capacity_kind' : ''}
        ) VALUES (
          :personId, :eventType, TO_DATE(:startsOn, 'YYYY-MM-DD'),
            TO_DATE(:endsOn, 'YYYY-MM-DD'), :title, :allocatedHours, :createdBy${context.authenticated ? ', :capacityKind' : ''}
        )
      `, { ...input, createdBy: context.actor,
        capacityKind: input.eventType === 'External commitment' ? 'EXTERNAL_WORK' : 'NON_AVAILABILITY' });
    } catch (error) {
      if (error instanceof Error && /ORA-00001/.test(error.message)) {
        throw conflictError('This availability event is already recorded.');
      }
      throw error;
    }

    return input;
  });
}
