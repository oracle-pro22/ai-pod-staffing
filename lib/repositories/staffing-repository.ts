import 'server-only';

import oracledb, { type Connection } from 'oracledb';

import { withOracleConnection } from '@/lib/db/oracle';

export type DatabaseRow = Record<string, unknown>;

export type OracleStaffingSnapshot = {
  database: DatabaseRow;
  projectTypes: DatabaseRow[];
  interests: DatabaseRow[];
  people: DatabaseRow[];
  customerMapping: DatabaseRow[];
  deliverables: DatabaseRow[];
  deliverableSkills: DatabaseRow[];
  personInterests: DatabaseRow[];
  availability: DatabaseRow[];
  requests: DatabaseRow[];
  requirements: DatabaseRow[];
  recommendations: DatabaseRow[];
  roles: DatabaseRow[];
  rolePermissions: DatabaseRow[];
  userRoles: DatabaseRow[];
};

const queryOptions = {
  outFormat: oracledb.OUT_FORMAT_OBJECT,
  fetchArraySize: 250,
} as const;

async function rows(connection: Connection, sql: string): Promise<DatabaseRow[]> {
  const result = await connection.execute<DatabaseRow>(sql, [], queryOptions);
  return result.rows ?? [];
}

async function row(connection: Connection, sql: string): Promise<DatabaseRow> {
  return (await rows(connection, sql))[0] ?? {};
}

export async function readOracleStaffingSnapshot(): Promise<OracleStaffingSnapshot> {
  return withOracleConnection(async (connection) => ({
    database: await row(connection, `
      SELECT USER AS database_user,
             SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') AS current_schema,
             TO_CHAR(SYSTIMESTAMP, 'YYYY-MM-DD"T"HH24:MI:SS.FF3TZH:TZM') AS database_time
        FROM DUAL
    `),
    projectTypes: await rows(connection, `
      SELECT project_type_id, project_name, project_description, source_version, source_row
        FROM project_types
       ORDER BY source_row, project_type_id
    `),
    interests: await rows(connection, `
      SELECT interest_id, interest_name, category, source, source_version, customer_controlled
        FROM interests
       ORDER BY interest_id
    `),
    people: await rows(connection, `
      SELECT person_id, full_name, initials, job_title, location, allocation_pct, active_pods,
             external_identity_subject, email_address, active_flag, created_at, updated_at
        FROM people
       WHERE active_flag = 'Y'
       ORDER BY full_name, person_id
    `),
    customerMapping: await rows(connection, `
      SELECT projects, project_description, deliverables, skills_type_of_work, note,
             source_version, source_row, customer_controlled
        FROM customer_mapping
       ORDER BY source_version, source_row
    `),
    deliverables: await rows(connection, `
      SELECT deliverable_id, project_type_id, project_name, deliverable_name, skills_raw,
             customer_note, source_version, source_row
        FROM deliverables
       ORDER BY source_row, deliverable_id
    `),
    deliverableSkills: await rows(connection, `
      SELECT deliverable_id, skill_id, skill_name, source_version, source_row
        FROM deliverable_skills
       ORDER BY deliverable_id, skill_id
    `),
    personInterests: await rows(connection, `
      SELECT person_id, interest_id, strength, evidence_note, source
        FROM person_interests
       ORDER BY person_id, strength DESC, interest_id
    `),
    availability: await rows(connection, `
      SELECT availability_id, person_id, event_type,
             TO_CHAR(starts_on, 'YYYY-MM-DD') AS starts_on,
             TO_CHAR(ends_on, 'YYYY-MM-DD') AS ends_on,
             title,
             allocated_hours, created_by, created_at, updated_at
        FROM availability
       ORDER BY starts_on, person_id, availability_id
    `),
    requests: await rows(connection, `
      SELECT request_id, title, project_type_id, project_type, deliverable_id, deliverable,
             deliverables_json, skills_type_of_work, owner_name, request_source,
             request_source_person_id,
             project_description,
             TO_CHAR(needed_by, 'YYYY-MM-DD') AS needed_by,
             TO_CHAR(estimated_start_date, 'YYYY-MM-DD') AS estimated_start_date,
             TO_CHAR(estimated_completion_date, 'YYYY-MM-DD') AS estimated_completion_date,
             estimated_effort_value, estimated_effort_unit, estimated_hours,
             requested_lead_count, requested_contributor_count, priority, status,
             business_context, business_objectives, expected_outcomes, mapping_version,
             created_by, created_at, updated_by, updated_at
        FROM requests
       ORDER BY needed_by, request_id
    `),
    requirements: await rows(connection, `
      SELECT requirement_id, request_id, deliverable_id, interest_id, skill_name,
             custom_capability_name, capability_source, required_strength, display_order,
             requirement_source, source_version, created_by, created_at
        FROM requirements
       ORDER BY request_id, display_order, requirement_id
    `),
    recommendations: await rows(connection, `
      SELECT request_id, person_id, role_in_pod, score, rank_position, rationale,
             factor_breakdown_json, matching_capabilities_json, selected_flag,
             decision_status, source, generated_at
        FROM recommendations
       ORDER BY request_id, role_in_pod, rank_position, score DESC
    `),
    roles: await rows(connection, `
      SELECT role_code, role_name, role_description, active_flag, created_at
        FROM app_roles
       ORDER BY role_name
    `),
    rolePermissions: await rows(connection, `
      SELECT role_code, resource_code, access_scope, can_view, can_create, can_update,
             can_approve, can_export, can_administer
        FROM role_permissions
       ORDER BY role_code, resource_code
    `),
    userRoles: await rows(connection, `
      SELECT identity_subject, role_code, person_id, active_flag, effective_from, effective_to,
             assigned_by, assigned_at
        FROM app_user_roles
       WHERE active_flag = 'Y'
         AND effective_from <= TRUNC(SYSDATE)
         AND (effective_to IS NULL OR effective_to >= TRUNC(SYSDATE))
       ORDER BY identity_subject, role_code
    `),
  }));
}
