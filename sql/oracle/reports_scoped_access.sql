-- Reports: full Captain/Admin, scoped Lead, own Member. No business data changes.
-- Run as AI_POD_STAFFING. Existing sessions may refresh or sign in again afterward.
SET SERVEROUTPUT ON
SET DEFINE OFF
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK
ALTER SESSION DISABLE PARALLEL DML;
ALTER SESSION DISABLE PARALLEL QUERY;

DECLARE
  n NUMBER;
  changed NUMBER := 0;
  PROCEDURE demand(ok BOOLEAN, message VARCHAR2) IS
  BEGIN
    IF NOT ok OR ok IS NULL THEN RAISE_APPLICATION_ERROR(-20570, message); END IF;
  END;
BEGIN
  demand(USER='AI_POD_STAFFING' AND SYS_CONTEXT('USERENV','CURRENT_SCHEMA')='AI_POD_STAFFING',
         'Connect as AI_POD_STAFFING.');
  SELECT COUNT(*) INTO n FROM role_permissions
   WHERE resource_code='REPORTS'
     AND role_code IN ('POD_CAPTAIN','POD_LEAD','POD_MEMBER','SYSTEM_ADMINISTRATOR');
  demand(n=4, 'Expected one REPORTS permission for each official profile.');

  SELECT COUNT(*) INTO n FROM user_tables WHERE table_name='AIPS_RPT_ACCESS_BK';
  IF n=0 THEN
    EXECUTE IMMEDIATE q'~CREATE TABLE AIPS_RPT_ACCESS_BK AS
      SELECT role_code,resource_code,access_scope,can_view,can_create,can_update,
             can_approve,can_export,can_administer
        FROM role_permissions
       WHERE resource_code='REPORTS'
         AND role_code IN ('POD_CAPTAIN','POD_LEAD','POD_MEMBER','SYSTEM_ADMINISTRATOR')~';
  END IF;
  -- The backup may be created earlier in this same block. Keep this lookup
  -- dynamic so Oracle does not try to resolve the table while compiling the
  -- block, before the conditional CREATE TABLE has executed.
  EXECUTE IMMEDIATE 'SELECT COUNT(*) FROM aips_rpt_access_bk' INTO n;
  demand(n=4, 'REPORTS recovery backup is incomplete; no permissions changed.');

  SELECT COUNT(*) INTO changed FROM role_permissions
   WHERE resource_code='REPORTS' AND (
     (role_code IN ('POD_CAPTAIN','SYSTEM_ADMINISTRATOR') AND
       (access_scope<>'FULL' OR can_view<>'Y' OR can_create<>'N' OR can_update<>'N'
        OR can_approve<>'N' OR can_export<>'Y' OR can_administer<>'N'))
     OR (role_code='POD_LEAD' AND
       (access_scope<>'SCOPED' OR can_view<>'Y' OR can_create<>'N' OR can_update<>'N'
        OR can_approve<>'N' OR can_export<>'N' OR can_administer<>'N'))
     OR (role_code='POD_MEMBER' AND
       (access_scope<>'OWN' OR can_view<>'Y' OR can_create<>'N' OR can_update<>'N'
        OR can_approve<>'N' OR can_export<>'N' OR can_administer<>'N')));

  UPDATE role_permissions SET access_scope='FULL',can_view='Y',can_create='N',can_update='N',
         can_approve='N',can_export='Y',can_administer='N'
   WHERE role_code='POD_CAPTAIN' AND resource_code='REPORTS';
  UPDATE role_permissions SET access_scope='FULL',can_view='Y',can_create='N',can_update='N',
         can_approve='N',can_export='Y',can_administer='N'
   WHERE role_code='SYSTEM_ADMINISTRATOR' AND resource_code='REPORTS';
  UPDATE role_permissions SET access_scope='SCOPED',can_view='Y',can_create='N',can_update='N',
         can_approve='N',can_export='N',can_administer='N'
   WHERE role_code='POD_LEAD' AND resource_code='REPORTS';
  UPDATE role_permissions SET access_scope='OWN',can_view='Y',can_create='N',can_update='N',
         can_approve='N',can_export='N',can_administer='N'
   WHERE role_code='POD_MEMBER' AND resource_code='REPORTS';
  IF changed>0 THEN
    INSERT INTO audit_events(audit_event_id,entity_type,entity_id,action_type,actor_subject,
                             correlation_id,after_state_json,reason)
    VALUES(RAWTOHEX(SYS_GUID()),'ROLE_PERMISSIONS','REPORTS','REPORT_SCOPES_ENABLED',USER,
           RAWTOHEX(SYS_GUID()),
           '{"POD_CAPTAIN":"FULL_EXPORT","SYSTEM_ADMINISTRATOR":"FULL_EXPORT","POD_LEAD":"SCOPED_VIEW","POD_MEMBER":"OWN_VIEW"}',
           'Enable permission-scoped operational reports without changing staffing data.');
  END IF;
  COMMIT;
  DBMS_OUTPUT.PUT_LINE('Reports access installed. Four permission rows reviewed; no staffing data changed.');
END;
/

SELECT role_code,access_scope,can_view,can_export
  FROM role_permissions WHERE resource_code='REPORTS' ORDER BY role_code;
