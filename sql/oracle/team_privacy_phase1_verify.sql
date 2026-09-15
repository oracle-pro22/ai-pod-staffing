SET SERVEROUTPUT ON
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK
DECLARE
  n NUMBER;
BEGIN
  IF USER <> 'AI_POD_STAFFING' THEN RAISE_APPLICATION_ERROR(-20001,'Connect as AI_POD_STAFFING.'); END IF;
  EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL QUERY';
  SELECT COUNT(*) INTO n FROM role_permissions WHERE resource_code='TEAM_SKILLS' AND can_view='Y' AND
    ((role_code='POD_MEMBER' AND access_scope='OWN') OR
     (role_code='POD_LEAD' AND access_scope='SCOPED') OR
     (role_code IN ('POD_CAPTAIN','SYSTEM_ADMINISTRATOR') AND access_scope='FULL'));
  IF n<>4 THEN RAISE_APPLICATION_ERROR(-20002,'Team visibility policy verification failed.'); END IF;
  DBMS_OUTPUT.PUT_LINE('PASS: four Team and Skills visibility scopes match the policy.');
END;
/
SELECT role_code,access_scope,can_view,can_create,can_update
FROM role_permissions WHERE resource_code='TEAM_SKILLS'
AND role_code IN ('POD_MEMBER','POD_LEAD','POD_CAPTAIN','SYSTEM_ADMINISTRATOR') ORDER BY role_code;
