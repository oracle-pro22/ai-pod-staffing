-- Restore Add availability event for POD Lead and POD Member only.
-- Run with F5 in SQL Developer using AIPOD / AI_POD_STAFFING.
-- No business records, table structures, other permissions, or other schemas are changed.
SET SERVEROUTPUT ON
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK
DECLARE
  matched_rows NUMBER;
BEGIN
  IF USER <> 'AI_POD_STAFFING'
    OR SYS_CONTEXT('USERENV','SESSION_USER') <> 'AI_POD_STAFFING'
    OR SYS_CONTEXT('USERENV','CURRENT_SCHEMA') <> 'AI_POD_STAFFING' THEN
    RAISE_APPLICATION_ERROR(-20001, 'Use the AI_POD_STAFFING connection only.');
  END IF;
  EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL DML';
  EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL QUERY';
  SELECT COUNT(*) INTO matched_rows
    FROM role_permissions rp JOIN app_roles ar ON ar.role_code = rp.role_code
   WHERE rp.resource_code = 'MY_AVAILABILITY' AND rp.access_scope = 'OWN' AND rp.can_view = 'Y'
     AND ar.active_flag = 'Y'
     AND ((ar.role_code = 'POD_LEAD' AND ar.role_name = 'POD Lead')
       OR (ar.role_code = 'POD_MEMBER' AND ar.role_name = 'POD Member'));
  IF matched_rows <> 2 THEN
    RAISE_APPLICATION_ERROR(-20002, 'Expected two active Lead/Member OWN availability permissions. No changes made.');
  END IF;
  UPDATE /*+ DISABLE_PARALLEL_DML NO_PARALLEL */ role_permissions
     SET can_create = 'Y'
   WHERE resource_code = 'MY_AVAILABILITY' AND role_code IN ('POD_LEAD', 'POD_MEMBER');
  COMMIT;
  DBMS_OUTPUT.PUT_LINE('SUCCESS: POD Lead and POD Member can add their own non-availability. Refresh the app.');
EXCEPTION WHEN OTHERS THEN
  ROLLBACK;
  RAISE;
END;
/
SELECT role_code, access_scope, can_view, can_create FROM role_permissions
 WHERE resource_code = 'MY_AVAILABILITY' ORDER BY role_code;
