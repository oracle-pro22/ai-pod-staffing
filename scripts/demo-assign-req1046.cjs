/* One-request demo fixture. Default is read-only; --apply inserts only the named lead recommendation. */
const path = require('node:path');
const oracledb = require('oracledb');
require('@next/env').loadEnvConfig(path.resolve(__dirname, '..'), true, { info() {}, error() {} });
const options = { outFormat: oracledb.OUT_FORMAT_OBJECT };
const requestId = 'REQ-1046';
const personId = 'P-006';
const source = 'Demo assignment REQ-1046';

async function main() {
  const connection = await oracledb.getConnection({
    user: process.env.DB_USER, password: process.env.DB_PASSWORD,
    connectString: process.env.DB_TNS_ALIAS,
    configDir: path.resolve(process.env.DB_WALLET_LOCATION),
    walletLocation: path.resolve(process.env.DB_WALLET_LOCATION), walletPassword: process.env.DB_WALLET_PASSWORD,
  });
  try {
    const identity = (await connection.execute(`SELECT USER AS db_user, SYS_CONTEXT('USERENV','SESSION_USER') AS session_user_name,
      SYS_CONTEXT('USERENV','CURRENT_SCHEMA') AS schema_name FROM dual`, {}, options)).rows[0];
    if (Object.values(identity).some((value) => value !== 'AI_POD_STAFFING')) throw new Error('Wrong database schema; stopped.');
    await connection.execute('ALTER SESSION DISABLE PARALLEL DML');
    await connection.execute('ALTER SESSION DISABLE PARALLEL QUERY');
    const apply = process.argv.includes('--apply');
    const requests = (await connection.execute(`SELECT request_id, title, status, request_source_person_id FROM requests
      WHERE request_id = :requestId ${apply ? 'FOR UPDATE WAIT 5' : ''}`, { requestId }, options)).rows;
    const people = (await connection.execute(`SELECT person_id, full_name, active_flag FROM people
      WHERE person_id = :personId ${apply ? 'FOR UPDATE WAIT 5' : ''}`, { personId }, options)).rows;
    const recommendations = (await connection.execute(`SELECT request_id, person_id, role_in_pod, selected_flag, decision_status, source
      FROM recommendations WHERE request_id = :requestId ORDER BY person_id, role_in_pod`, { requestId }, options)).rows;
    const triggers = (await connection.execute(`SELECT trigger_name, table_name FROM user_triggers
      WHERE table_name = 'RECOMMENDATIONS' AND status = 'ENABLED'`, {}, options)).rows;
    console.log(JSON.stringify({ requests, people, recommendations, enabledRecommendationTriggers: triggers }, null, 2));
    if (!apply) return;
    if (requests.length !== 1 || requests[0].TITLE.trim().toLowerCase() !== 'test req for elicia') throw new Error('Request title does not match; stopped.');
    if (people.length !== 1 || people[0].FULL_NAME.trim() !== 'Elena Garcia' || people[0].ACTIVE_FLAG !== 'Y') throw new Error('Elena profile does not match; stopped.');
    if (triggers.length) throw new Error('Review enabled recommendation triggers before applying.');
    const existing = recommendations.filter((row) => row.PERSON_ID === personId);
    if (existing.length === 1 && existing[0].ROLE_IN_POD === 'POD Lead' && existing[0].SOURCE === source
      && existing[0].SELECTED_FLAG === 'Y' && existing[0].DECISION_STATUS === 'APPROVED') {
      console.log('Demo assignment already present; no changes made.'); return;
    }
    if (existing.length) throw new Error('Elena already has a recommendation; stopped without overwriting it.');
    if (recommendations.some((row) => /^(pod[ _-]?)?lead$/i.test(row.ROLE_IN_POD.trim())
      && row.SELECTED_FLAG === 'Y' && row.DECISION_STATUS.trim().toUpperCase() === 'APPROVED')) throw new Error('An approved lead already exists; stopped.');
    await connection.execute(`INSERT INTO recommendations
      (request_id, person_id, role_in_pod, score, rank_position, rationale, factor_breakdown_json,
       matching_capabilities_json, selected_flag, decision_status, source)
      VALUES (:requestId, :personId, 'POD Lead', 0, 1, :rationale, '[]', '[]', 'Y', 'APPROVED', :sourceName)`, {
      requestId, personId, sourceName: source,
      rationale: 'Demo-only lead assignment requested for REQ-1046. Selected/approved flags enable the existing lead view; no real Captain approval or Lead acceptance was recorded. Score 0 is a placeholder, not a fitment assessment.',
    });
    const verified = (await connection.execute(`SELECT person_id, role_in_pod, selected_flag, decision_status, source
      FROM recommendations WHERE request_id = :requestId AND person_id = :personId`, { requestId, personId }, options)).rows;
    if (verified.length !== 1 || verified[0].SOURCE !== source || verified[0].DECISION_STATUS !== 'APPROVED') throw new Error('Verification failed; rolling back.');
    await connection.commit();
    console.log('COMMITTED: one demo lead recommendation for Elena Garcia on REQ-1046. Request status and all other records unchanged.');
  } finally {
    await connection.rollback(); // Releases read/lock-only transactions; committed changes are unaffected.
    await connection.close();
  }
}
main().catch((error) => {
  console.error(error.code || (error.errorNum ? `ORA-${error.errorNum}` : error.message));
  process.exitCode = 1;
});
