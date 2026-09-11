-- Emergency feature disable only. No data loss, schema downgrade, or restoration.
-- This revokes MY_SKILLS permission; refresh the application afterwards.
SET SERVEROUTPUT ON
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK
BEGIN
  IF USER <> 'AI_POD_STAFFING' OR SYS_CONTEXT('USERENV','SESSION_USER') <> 'AI_POD_STAFFING'
    OR SYS_CONTEXT('USERENV','CURRENT_SCHEMA') <> 'AI_POD_STAFFING' THEN
    RAISE_APPLICATION_ERROR(-20001, 'Use AI_POD_STAFFING only.');
  END IF;
  EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL DML';
  EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL QUERY';
  UPDATE /*+ DISABLE_PARALLEL_DML NO_PARALLEL */ role_permissions
     SET access_scope = 'LOCKED', can_view = 'N', can_create = 'N', can_update = 'N',
         can_approve = 'N', can_export = 'N', can_administer = 'N'
   WHERE resource_code = 'MY_SKILLS';
  COMMIT;
  DBMS_OUTPUT.PUT_LINE('MY_SKILLS disabled. All employee data and backups retained.');
END;
/
