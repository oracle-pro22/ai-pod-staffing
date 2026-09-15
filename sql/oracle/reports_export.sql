SET SERVEROUTPUT ON
SET DEFINE OFF
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK
ALTER SESSION DISABLE PARALLEL DML;
ALTER SESSION DISABLE PARALLEL QUERY;
DECLARE
  n NUMBER;
BEGIN
  IF USER <> 'AI_POD_STAFFING' OR SYS_CONTEXT('USERENV','CURRENT_SCHEMA') <> 'AI_POD_STAFFING' THEN
    RAISE_APPLICATION_ERROR(-20001,'Connect as AI_POD_STAFFING.');
  END IF;
  SELECT COUNT(*) INTO n FROM role_permissions WHERE resource_code='REPORTS'
    AND role_code IN ('POD_CAPTAIN','SYSTEM_ADMINISTRATOR') AND can_view='Y' AND access_scope='FULL';
  IF n<>2 THEN RAISE_APPLICATION_ERROR(-20002,'Expected two existing Reports viewer permissions.'); END IF;
  SELECT COUNT(*) INTO n FROM user_tables WHERE table_name='AIPS_RPT_EXPORT_BK';
  IF n=0 THEN
    EXECUTE IMMEDIATE q'~CREATE TABLE AIPS_RPT_EXPORT_BK AS
      SELECT role_code,resource_code,can_export FROM role_permissions
      WHERE resource_code='REPORTS' AND role_code IN ('POD_CAPTAIN','SYSTEM_ADMINISTRATOR')~';
  END IF;
END;
/
DECLARE
  changed NUMBER;
BEGIN
  UPDATE role_permissions SET can_export='Y' WHERE resource_code='REPORTS'
    AND role_code IN ('POD_CAPTAIN','SYSTEM_ADMINISTRATOR') AND can_view='Y'
    AND access_scope='FULL' AND can_export='N';
  changed:=SQL%ROWCOUNT;
  IF changed>0 THEN
    INSERT INTO audit_events(audit_event_id,entity_type,entity_id,action_type,actor_subject,correlation_id,after_state_json,reason)
      VALUES(RAWTOHEX(SYS_GUID()),'ROLE_PERMISSIONS','REPORTS','REPORT_EXPORT_ENABLED',USER,RAWTOHEX(SYS_GUID()),
        '{"roles":["POD_CAPTAIN","SYSTEM_ADMINISTRATOR"],"can_export":"Y"}',
        'Restore requested Reports Excel export, retaining existing record scopes.');
  END IF;
  COMMIT;
  DBMS_OUTPUT.PUT_LINE('Reports export enabled for Captain and Administrator. Existing view scopes retained.');
EXCEPTION WHEN OTHERS THEN ROLLBACK; RAISE;
END;
/
SELECT role_code,access_scope,can_view,can_export FROM role_permissions WHERE resource_code='REPORTS';
-- Recovery if required: restore only can_export from AIPS_RPT_EXPORT_BK for these two REPORTS rows.
-- Keep the backup until the recovery window ends. No people or project records are modified.
