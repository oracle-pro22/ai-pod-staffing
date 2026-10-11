-- Enable maintenance of OWN events for roles already allowed to create them.
-- Run as AI_POD_STAFFING with F5; no DDL or business-data changes.
-- Repeat-safe. Does not change Captain/Admin permissions or anyone's role grants.
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
  SELECT COUNT(*) INTO matched_rows FROM user_tab_columns
    WHERE table_name='AVAILABILITY' AND column_name IN ('STATUS','REVISION','EFFECTIVE_UNTIL');
  IF matched_rows <> 3 THEN
    RAISE_APPLICATION_ERROR(-20002, 'Install availability lifecycle schema before enabling update access.');
  END IF;
  -- Lock exactly the target permissions; fail closed on an unexpected baseline.
  matched_rows := 0;
  FOR p IN (SELECT role_code,access_scope,can_view,can_create FROM role_permissions
    WHERE resource_code='MY_AVAILABILITY' AND role_code IN ('POD_LEAD','POD_MEMBER')
    ORDER BY role_code FOR UPDATE WAIT 5) LOOP
    IF p.access_scope <> 'OWN' OR p.can_view <> 'Y' OR p.can_create <> 'Y' THEN
      RAISE_APPLICATION_ERROR(-20002, 'Expected existing OWN view/create permission. No changes made.');
    END IF;
    matched_rows := matched_rows + 1;
  END LOOP;
  IF matched_rows <> 2 THEN
    RAISE_APPLICATION_ERROR(-20002, 'Expected exactly two Lead/Member availability permissions.');
  END IF;
  SELECT COUNT(*) INTO matched_rows FROM app_roles
    WHERE active_flag='Y' AND ((role_code='POD_LEAD' AND role_name='POD Lead')
      OR (role_code='POD_MEMBER' AND role_name='POD Member'));
  IF matched_rows <> 2 THEN
    RAISE_APPLICATION_ERROR(-20002, 'Expected active Lead and Member roles.');
  END IF;
  UPDATE /*+ DISABLE_PARALLEL_DML NO_PARALLEL */ role_permissions SET can_update='Y'
    WHERE resource_code='MY_AVAILABILITY' AND role_code IN ('POD_LEAD','POD_MEMBER')
      AND access_scope='OWN' AND can_view='Y' AND can_create='Y' AND can_update='N';
  DBMS_OUTPUT.PUT_LINE('Own-availability update permissions changed: ' || SQL%ROWCOUNT);
  COMMIT;
EXCEPTION WHEN OTHERS THEN
  ROLLBACK;
  RAISE;
END;
/
SELECT role_code,access_scope,can_view,can_create,can_update FROM role_permissions
  WHERE resource_code='MY_AVAILABILITY' ORDER BY role_code;
