WHENEVER SQLERROR EXIT FAILURE ROLLBACK
SET SERVEROUTPUT ON

DECLARE
  v_person_id       people.person_id%TYPE;
  v_account_count   PLS_INTEGER;
  v_assignment_count PLS_INTEGER;
BEGIN
  IF SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA') <> 'AI_POD_STAFFING' THEN
    RAISE_APPLICATION_ERROR(-20370, 'Run this script only in the AI_POD_STAFFING schema.');
  END IF;

  SELECT person_id
    INTO v_person_id
    FROM people
   WHERE LOWER(email_address) = 'amy.s.lawrence@oracle.com'
     AND full_name = 'Amy Lawrence'
     AND active_flag = 'Y';

  SELECT COUNT(*)
    INTO v_account_count
    FROM app_accounts
   WHERE person_id = v_person_id
     AND active_flag = 'Y';

  IF v_account_count <> 1 THEN
    RAISE_APPLICATION_ERROR(-20371, 'Amy must retain exactly one active application account.');
  END IF;

  SELECT COUNT(*)
    INTO v_assignment_count
    FROM pod_assignments
   WHERE person_id = v_person_id
     AND status = 'CONFIRMED';

  IF v_assignment_count <> 0 THEN
    RAISE_APPLICATION_ERROR(-20372, 'Amy has a confirmed POD assignment. Close or reset that test assignment before making her access-only.');
  END IF;

  MERGE INTO app_user_roles target
  USING (
    SELECT a.identity_subject, a.person_id
      FROM app_accounts a
     WHERE a.person_id = v_person_id
       AND a.active_flag = 'Y'
  ) source
     ON (target.identity_subject = source.identity_subject
         AND target.role_code = 'SYSTEM_ADMINISTRATOR')
   WHEN MATCHED THEN UPDATE SET
        target.person_id = source.person_id,
        target.active_flag = 'Y',
        target.effective_from = TRUNC(SYSDATE),
        target.effective_to = NULL,
        target.assigned_by = 'amy-access-only'
   WHEN NOT MATCHED THEN INSERT
        (identity_subject, role_code, person_id, active_flag, effective_from, effective_to, assigned_by)
     VALUES
        (source.identity_subject, 'SYSTEM_ADMINISTRATOR', source.person_id, 'Y', TRUNC(SYSDATE), NULL, 'amy-access-only');

  UPDATE people
     SET staffing_eligible_flag = 'N'
   WHERE person_id = v_person_id;

  IF SQL%ROWCOUNT <> 1 THEN
    RAISE_APPLICATION_ERROR(-20373, 'Amy access-only update did not affect exactly one person.');
  END IF;

  DBMS_OUTPUT.PUT_LINE('Amy Lawrence remains active, has Captain plus Administrator access, and is excluded from future POD staffing.');
END;
/

COMMIT;

SELECT p.person_id,
       p.full_name,
       p.email_address,
       p.active_flag,
       p.staffing_eligible_flag,
       a.active_flag AS account_active,
       LISTAGG(ur.role_code, ', ') WITHIN GROUP (ORDER BY ur.role_code) AS active_roles
  FROM people p
  JOIN app_accounts a
    ON a.person_id = p.person_id
  LEFT JOIN app_user_roles ur
    ON ur.person_id = p.person_id
   AND ur.identity_subject = a.identity_subject
   AND ur.active_flag = 'Y'
 WHERE LOWER(p.email_address) = 'amy.s.lawrence@oracle.com'
 GROUP BY p.person_id, p.full_name, p.email_address, p.active_flag,
          p.staffing_eligible_flag, a.active_flag;
