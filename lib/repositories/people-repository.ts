import 'server-only';
import oracledb from 'oracledb';
import { withOracleConnection, withOracleTransaction } from '@/lib/db/oracle';
import { conflictError, forbiddenError, StaffingApiError } from '@/lib/errors/staffing-api-error';
import type { StaffingMutationContext } from '@/types/mutations';
import type { CreatePersonInput } from '@/lib/validation/people';
import { assertIdentityMapping } from '@/lib/auth/identity-mapping';
import { EMPLOYEE_SCOPE_SQL } from '@/lib/repositories/employee-scope';

const options = { outFormat: oracledb.OUT_FORMAT_OBJECT } as const;

export async function listActivePeopleNames() {
  return withOracleConnection(async (connection) => {
    const result = await connection.execute<{ PERSON_ID: string; FULL_NAME: string }>(
      `SELECT p.person_id, p.full_name FROM people p WHERE p.active_flag = 'Y'
        AND ${EMPLOYEE_SCOPE_SQL} ORDER BY p.full_name, p.person_id`, {}, options);
    return (result.rows ?? []).map((row) => ({ id: row.PERSON_ID, name: row.FULL_NAME }));
  });
}

export async function createPerson(input: CreatePersonInput, context: StaffingMutationContext) {
  if (context.role !== 'Administrator') throw forbiddenError();
  try {
    return await withOracleTransaction(async (connection) => {
      await assertIdentityMapping(connection, context);
      const permission = await connection.execute<Record<string, unknown>>(`
        SELECT rp.can_view, rp.can_create, rp.access_scope
        FROM app_roles ar JOIN role_permissions rp ON rp.role_code = ar.role_code
        WHERE ar.role_code = :roleCode AND ar.role_name = :roleName AND ar.active_flag = 'Y'
          AND rp.resource_code = :resourceCode
      `, { roleCode: 'SYSTEM_ADMINISTRATOR', roleName: context.role, resourceCode: 'TEAM_SKILLS' }, options);
      const row = permission.rows?.[0];
      if (row?.CAN_VIEW !== 'Y' || row.CAN_CREATE !== 'Y' || row.ACCESS_SCOPE !== 'FULL') throw forbiddenError();
      if (input.email) {
        const duplicate = await connection.execute("SELECT person_id FROM people WHERE LOWER(TRIM(email_address)) = :email", { email: input.email }, options);
        if (duplicate.rows?.length) throw conflictError('A person with this email already exists, including inactive profiles.');
      }
      const sequence = await connection.execute<{ PERSON_NUMBER: string }>(
        "SELECT TO_CHAR(person_id_seq.NEXTVAL, 'TM9') AS person_number FROM dual", {}, options);
      const next = sequence.rows?.[0]?.PERSON_NUMBER?.trim();
      if (!next || !/^\d+$/.test(next)) throw new StaffingApiError('Unable to generate a person ID.', 503, 'PERSON_ID_UNAVAILABLE');
      const personId = `P-${next.padStart(3, '0')}`;
      const parts = input.fullName.split(/\s+/);
      const initials = [Array.from(parts[0])[0], parts.length > 1 ? Array.from(parts[parts.length - 1])[0] : ''].join('').toUpperCase();
      await connection.execute(`
        INSERT INTO people (person_id, full_name, initials, job_title, location, allocation_pct, active_pods, email_address, active_flag)
        VALUES (:personId, :fullName, :initials, :jobTitle, :location, :allocationPct, :activePods, :email, 'Y')
      `, { personId, fullName: input.fullName, initials, jobTitle: input.jobTitle, location: input.location,
        allocationPct: input.allocationPct, activePods: input.activePods, email: input.email || null });
      return { personId, fullName: input.fullName };
    });
  } catch (error) {
    const number = (error as { errorNum?: number })?.errorNum;
    if (number === 1) throw conflictError('This person could not be added because the email or generated ID already exists. Refresh before trying again.');
    if (number === 2289) throw new StaffingApiError('People setup is incomplete. Run admin_people.sql in SQL Developer first.', 503, 'PEOPLE_SETUP_REQUIRED');
    throw error;
  }
}
