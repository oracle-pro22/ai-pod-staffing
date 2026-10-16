-- Enable the assigned, read-only AI Fitment workspace for Leads and Members.
-- Run after roles_catalog.sql, as the application schema owner.
-- Idempotent DML only. No people, assignments, requests or other grants change.
SET SERVEROUTPUT ON
SET DEFINE OFF
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK

DECLARE
  role_count NUMBER;
BEGIN
  SELECT COUNT(*) INTO role_count FROM app_roles
    WHERE role_code IN ('POD_LEAD','POD_MEMBER') AND active_flag='Y';
  IF role_count <> 2 THEN
    RAISE_APPLICATION_ERROR(-20380, 'Active POD Lead and Member profiles are required.');
  END IF;

  MERGE INTO role_permissions target
  USING (SELECT 'POD_LEAD' role_code, 'SCOPED' access_scope FROM dual
         UNION ALL SELECT 'POD_MEMBER', 'OWN' FROM dual) source
  ON (target.role_code=source.role_code AND target.resource_code='AI_FITMENT')
  WHEN MATCHED THEN UPDATE SET target.access_scope=source.access_scope,
    target.can_view='Y',target.can_create='N',target.can_update='N',
    target.can_approve='N',target.can_export='N',target.can_administer='N'
  WHEN NOT MATCHED THEN INSERT
    (role_code,resource_code,access_scope,can_view,can_create,can_update,can_approve,can_export,can_administer)
    VALUES (source.role_code,'AI_FITMENT',source.access_scope,'Y','N','N','N','N','N');
  COMMIT;
  DBMS_OUTPUT.PUT_LINE('Assigned AI Fitment viewing enabled. No write or approval permissions granted.');
EXCEPTION WHEN OTHERS THEN
  ROLLBACK;
  RAISE;
END;
/

SELECT role_code,access_scope,can_view,can_create,can_update,can_approve,can_export,can_administer
FROM role_permissions WHERE resource_code='AI_FITMENT' AND role_code IN ('POD_LEAD','POD_MEMBER')
ORDER BY role_code;
