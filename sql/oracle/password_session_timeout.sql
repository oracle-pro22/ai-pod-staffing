-- Install with F5 as AI_POD_STAFFING before deploying the updated API and web app.
-- Stop API, web and worker first. This is additive and keeps accounts and staffing data.
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK
SET SERVEROUTPUT ON
DECLARE
  n NUMBER;
BEGIN
  IF USER <> 'AI_POD_STAFFING' OR SYS_CONTEXT('USERENV','CURRENT_SCHEMA') <> 'AI_POD_STAFFING' THEN
    RAISE_APPLICATION_ERROR(-20350, 'Run as AI_POD_STAFFING in its own schema.');
  END IF;
  SELECT COUNT(*) INTO n FROM user_tab_columns
    WHERE table_name='APP_SESSIONS' AND column_name='LAST_ACTIVITY_AT';
  IF n=0 THEN
    EXECUTE IMMEDIATE 'ALTER TABLE app_sessions ADD (last_activity_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP)';
  END IF;
  -- Dynamic SQL avoids resolving this new column before the ALTER TABLE runs.
  EXECUTE IMMEDIATE 'UPDATE app_sessions SET last_activity_at=SYSTIMESTAMP WHERE last_activity_at IS NULL';
  EXECUTE IMMEDIATE 'ALTER TABLE app_sessions MODIFY (last_activity_at DEFAULT SYSTIMESTAMP NOT NULL)';
  COMMIT;
  DBMS_OUTPUT.PUT_LINE('Password session activity column installed. Existing sessions remain subject to the new one-hour maximum.');
END;
/
SELECT COUNT(*) AS session_timeout_column_ready FROM user_tab_columns
WHERE table_name='APP_SESSIONS' AND column_name='LAST_ACTIVITY_AT' AND nullable='N';
