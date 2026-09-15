SET SERVEROUTPUT ON
SET DEFINE OFF
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK
PROMPT Restoring only the original Team and Skills scopes
DECLARE
  n NUMBER;
  original_scope VARCHAR2(20);
  target_scope VARCHAR2(20);
BEGIN
  IF USER <> 'AI_POD_STAFFING' THEN RAISE_APPLICATION_ERROR(-20001,'Connect as AI_POD_STAFFING.'); END IF;
  EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL DML';
  EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL QUERY';
  EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL DDL';
  EXECUTE IMMEDIATE 'SELECT COUNT(*) FROM AIPS_TP1_BK_SCOPE' INTO n;
  IF n<>4 THEN RAISE_APPLICATION_ERROR(-20002,'Expected four backup rows.'); END IF;
  EXECUTE IMMEDIATE q'~SELECT COUNT(DISTINCT role_code) FROM AIPS_TP1_BK_SCOPE
    WHERE resource_code='TEAM_SKILLS' AND role_code IN
      ('POD_MEMBER','POD_LEAD','POD_CAPTAIN','SYSTEM_ADMINISTRATOR')
      AND access_scope IN ('OWN','SCOPED','FULL','LOCKED')~' INTO n;
  IF n<>4 THEN RAISE_APPLICATION_ERROR(-20003,'Backup verification failed.'); END IF;
  SELECT COUNT(*) INTO n FROM role_permissions WHERE resource_code='TEAM_SKILLS'
    AND role_code IN ('POD_MEMBER','POD_LEAD','POD_CAPTAIN','SYSTEM_ADMINISTRATOR');
  IF n<>4 THEN RAISE_APPLICATION_ERROR(-20004,'Permission baseline changed.'); END IF;
  FOR item IN (SELECT /*+ NO_PARALLEL */ role_code,access_scope FROM role_permissions
    WHERE resource_code='TEAM_SKILLS' AND role_code IN
      ('POD_MEMBER','POD_LEAD','POD_CAPTAIN','SYSTEM_ADMINISTRATOR')
    ORDER BY role_code FOR UPDATE WAIT 5) LOOP
    EXECUTE IMMEDIATE 'SELECT access_scope FROM AIPS_TP1_BK_SCOPE WHERE role_code=:roleCode'
      INTO original_scope USING item.role_code;
    target_scope := CASE item.role_code WHEN 'POD_MEMBER' THEN 'OWN'
      WHEN 'POD_LEAD' THEN 'SCOPED' ELSE 'FULL' END;
    IF item.access_scope IS NULL OR
      (item.access_scope<>target_scope AND item.access_scope<>original_scope) THEN
      RAISE_APPLICATION_ERROR(-20005,'A later scope change exists; rollback stopped.');
    END IF;
    UPDATE /*+ DISABLE_PARALLEL_DML NO_PARALLEL */ role_permissions SET access_scope=original_scope
      WHERE role_code=item.role_code AND resource_code='TEAM_SKILLS' AND access_scope<>original_scope;
  END LOOP;
  COMMIT;
  DBMS_OUTPUT.PUT_LINE('SUCCESS: original scopes restored; backup and business records retained.');
EXCEPTION WHEN OTHERS THEN ROLLBACK; RAISE;
END;
/
