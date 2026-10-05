import 'server-only';
import oracledb from 'oracledb';
import { withOracleConnection } from '@/lib/db/oracle';
import { forbiddenError, StaffingApiError } from '@/lib/errors/staffing-api-error';
import type { StaffingMutationContext } from '@/types/mutations';
import type { CreatePersonInput } from '@/lib/validation/people';
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
  // Retain a fail-closed guard for old callers; all creation now goes through
  // authenticated Python provisioning and its single account/person transaction.
  void input;
  throw new StaffingApiError('Use authenticated employee provisioning to create the person, login and roles together.', 409, 'EMPLOYEE_PROVISIONING_REQUIRED');
}
