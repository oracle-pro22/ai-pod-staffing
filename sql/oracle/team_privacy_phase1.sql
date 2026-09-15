SET SERVEROUTPUT ON
SET DEFINE OFF
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK
PROMPT Applying Team and Skills profile visibility
DECLARE
  n NUMBER;
  backup_count NUMBER;
  original_scope VARCHAR2(20);
  target_scope VARCHAR2(20);
BEGIN
  IF USER <> 'AI_POD_STAFFING' THEN
    RAISE_APPLICATION_ERROR(-20001, 'Connect as AI_POD_STAFFING.');
  END IF;
  -- The serial FOR UPDATE locks below must not be handed to parallel DML
  -- siblings (ORA-12860 on Autonomous Database). Change this session only.
  EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL DML';
  EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL QUERY';
  EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL DDL';
  SELECT COUNT(*) INTO n FROM app_roles WHERE active_flag='Y' AND
    ((role_code='POD_MEMBER' AND role_name='POD Member') OR
     (role_code='POD_LEAD' AND role_name='POD Lead') OR
     (role_code='POD_CAPTAIN' AND role_name='POD Captain') OR
     (role_code='SYSTEM_ADMINISTRATOR' AND role_name='Administrator'));
  IF n<>4 THEN RAISE_APPLICATION_ERROR(-20002, 'Expected four active official profiles.'); END IF;
  SELECT COUNT(*),COUNT(DISTINCT role_code) INTO n,backup_count FROM role_permissions
    WHERE resource_code='TEAM_SKILLS' AND role_code IN
      ('POD_MEMBER','POD_LEAD','POD_CAPTAIN','SYSTEM_ADMINISTRATOR') AND can_view='Y';
  IF n<>4 OR backup_count<>4 THEN
    RAISE_APPLICATION_ERROR(-20003, 'Expected four unique view-enabled TEAM_SKILLS permission rows.');
  END IF;
  SELECT COUNT(*) INTO n FROM user_tables WHERE table_name='AIPS_TP1_BK_SCOPE';
  IF n=0 THEN
    EXECUTE IMMEDIATE q'~CREATE TABLE AIPS_TP1_BK_SCOPE NOPARALLEL AS
      SELECT /*+ NO_PARALLEL */ role_code,resource_code,access_scope FROM role_permissions
      WHERE resource_code='TEAM_SKILLS' AND role_code IN
        ('POD_MEMBER','POD_LEAD','POD_CAPTAIN','SYSTEM_ADMINISTRATOR')~';
    DBMS_OUTPUT.PUT_LINE('Original visibility scopes backed up.');
  ELSE
    DBMS_OUTPUT.PUT_LINE('Reusing the original visibility backup.');
  END IF;
  EXECUTE IMMEDIATE 'SELECT COUNT(*) FROM AIPS_TP1_BK_SCOPE' INTO backup_count;
  EXECUTE IMMEDIATE q'~SELECT COUNT(DISTINCT role_code) FROM AIPS_TP1_BK_SCOPE
    WHERE resource_code='TEAM_SKILLS' AND role_code IN
      ('POD_MEMBER','POD_LEAD','POD_CAPTAIN','SYSTEM_ADMINISTRATOR')
      AND access_scope IN ('OWN','SCOPED','FULL','LOCKED')~' INTO n;
  IF backup_count<>4 OR n<>4 THEN
    RAISE_APPLICATION_ERROR(-20004, 'Backup contents do not match this migration; backup retained.');
  END IF;
  FOR item IN (SELECT /*+ NO_PARALLEL */ role_code,access_scope FROM role_permissions
    WHERE resource_code='TEAM_SKILLS' AND role_code IN
      ('POD_MEMBER','POD_LEAD','POD_CAPTAIN','SYSTEM_ADMINISTRATOR')
    ORDER BY role_code FOR UPDATE WAIT 5) LOOP
    EXECUTE IMMEDIATE 'SELECT access_scope FROM AIPS_TP1_BK_SCOPE WHERE role_code=:roleCode'
      INTO original_scope USING item.role_code;
    target_scope := CASE item.role_code WHEN 'POD_MEMBER' THEN 'OWN'
      WHEN 'POD_LEAD' THEN 'SCOPED' ELSE 'FULL' END;
    IF item.access_scope IS NULL OR
      (item.access_scope<>original_scope AND item.access_scope<>target_scope) THEN
      RAISE_APPLICATION_ERROR(-20005, 'Visibility changed since backup; inspect before retrying.');
    END IF;
  END LOOP;
  UPDATE /*+ DISABLE_PARALLEL_DML NO_PARALLEL */ role_permissions SET access_scope=CASE role_code
    WHEN 'POD_MEMBER' THEN 'OWN' WHEN 'POD_LEAD' THEN 'SCOPED' ELSE 'FULL' END
    WHERE resource_code='TEAM_SKILLS' AND role_code IN
      ('POD_MEMBER','POD_LEAD','POD_CAPTAIN','SYSTEM_ADMINISTRATOR')
    AND access_scope<>CASE role_code WHEN 'POD_MEMBER' THEN 'OWN'
      WHEN 'POD_LEAD' THEN 'SCOPED' ELSE 'FULL' END;
  DBMS_OUTPUT.PUT_LINE('Visibility scopes changed: ' || SQL%ROWCOUNT);
  SELECT COUNT(*) INTO n FROM role_permissions WHERE resource_code='TEAM_SKILLS' AND can_view='Y' AND
    ((role_code='POD_MEMBER' AND access_scope='OWN') OR
     (role_code='POD_LEAD' AND access_scope='SCOPED') OR
     (role_code IN ('POD_CAPTAIN','SYSTEM_ADMINISTRATOR') AND access_scope='FULL'));
  IF n<>4 THEN RAISE_APPLICATION_ERROR(-20006, 'Expected exactly four verified permission rows.'); END IF;
  COMMIT;
  DBMS_OUTPUT.PUT_LINE('SUCCESS: Member OWN; Lead SCOPED; Captain and Administrator FULL.');
  DBMS_OUTPUT.PUT_LINE('Action permissions and business records retained. Run team_privacy_phase1_verify.sql.');
EXCEPTION WHEN OTHERS THEN
  ROLLBACK;
  DBMS_OUTPUT.PUT_LINE('Permission updates rolled back. Any created backup remains committed and is retained.');
  RAISE;
END;
/
