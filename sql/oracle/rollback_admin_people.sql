-- Permission-only rollback. Run F5 as AI_POD_STAFFING in a fresh connection.
-- Stop this application's writers first. Do not use after unrelated permission edits.
-- Keeps all people, the ID sequence, the duplicate-email index, and recovery backup.
SET SERVEROUTPUT ON
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK
DECLARE
  n NUMBER;
BEGIN
  IF USER<>'AI_POD_STAFFING' OR SYS_CONTEXT('USERENV','SESSION_USER')<>'AI_POD_STAFFING'
    OR SYS_CONTEXT('USERENV','CURRENT_SCHEMA')<>'AI_POD_STAFFING' THEN
    RAISE_APPLICATION_ERROR(-20001,'Use AI_POD_STAFFING only.');
  END IF;
  EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL DML';
  EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL QUERY';
  EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL DDL';
  EXECUTE IMMEDIATE 'SELECT COUNT(*) FROM AIPS_BK_ADMIN_ACCESS WHERE role_code=''SYSTEM_ADMINISTRATOR''' INTO n;
  IF n<>12 THEN RAISE_APPLICATION_ERROR(-20002,'Expected permission backup is missing or invalid.'); END IF;
  EXECUTE IMMEDIATE q'[
    UPDATE /*+ DISABLE_PARALLEL_DML NO_PARALLEL */ role_permissions rp
    SET (can_view,access_scope,can_create) = (
      SELECT b.can_view,b.access_scope,b.can_create FROM AIPS_BK_ADMIN_ACCESS b
      WHERE b.role_code=rp.role_code AND b.resource_code=rp.resource_code)
    WHERE rp.role_code='SYSTEM_ADMINISTRATOR'
      AND EXISTS (SELECT 1 FROM AIPS_BK_ADMIN_ACCESS b WHERE b.role_code=rp.role_code AND b.resource_code=rp.resource_code)
  ]';
  IF SQL%ROWCOUNT<>12 THEN RAISE_APPLICATION_ERROR(-20003,'Unexpected permission count.'); END IF;
  COMMIT;
  DBMS_OUTPUT.PUT_LINE('Administrator view/create permissions restored. All people retained.');
EXCEPTION WHEN OTHERS THEN ROLLBACK; RAISE;
END;
/
