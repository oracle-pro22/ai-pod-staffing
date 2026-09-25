-- Recovery only: restore the four REPORTS permission rows saved by reports_scoped_access.sql.
SET SERVEROUTPUT ON
SET DEFINE OFF
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK
DECLARE
  n NUMBER;
BEGIN
  IF USER<>'AI_POD_STAFFING' OR SYS_CONTEXT('USERENV','CURRENT_SCHEMA')<>'AI_POD_STAFFING' THEN
    RAISE_APPLICATION_ERROR(-20571,'Connect as AI_POD_STAFFING.');
  END IF;
  SELECT COUNT(*) INTO n FROM user_tables WHERE table_name='AIPS_RPT_ACCESS_BK';
  IF n<>1 THEN RAISE_APPLICATION_ERROR(-20571,'REPORTS recovery backup is missing.'); END IF;
  SELECT COUNT(*) INTO n FROM aips_rpt_access_bk;
  IF n<>4 THEN RAISE_APPLICATION_ERROR(-20571,'REPORTS recovery backup is incomplete.'); END IF;
  MERGE INTO role_permissions target
  USING aips_rpt_access_bk source
     ON (target.role_code=source.role_code AND target.resource_code=source.resource_code)
  WHEN MATCHED THEN UPDATE SET target.access_scope=source.access_scope,target.can_view=source.can_view,
    target.can_create=source.can_create,target.can_update=source.can_update,target.can_approve=source.can_approve,
    target.can_export=source.can_export,target.can_administer=source.can_administer;
  INSERT INTO audit_events(audit_event_id,entity_type,entity_id,action_type,actor_subject,
                           correlation_id,after_state_json,reason)
  VALUES(RAWTOHEX(SYS_GUID()),'ROLE_PERMISSIONS','REPORTS','REPORT_SCOPES_RESTORED',USER,
         RAWTOHEX(SYS_GUID()),'{"source":"AIPS_RPT_ACCESS_BK"}',
         'Restore the pre-release REPORTS access matrix.');
  COMMIT;
  DBMS_OUTPUT.PUT_LINE('Previous Reports access restored. Staffing data unchanged.');
END;
/

SELECT role_code,access_scope,can_view,can_export
  FROM role_permissions WHERE resource_code='REPORTS' ORDER BY role_code;

