-- ============================================================================
-- AI Pod Staffing - Reset an EMPTY failed setup only
-- Schema: AI_POD_STAFFING
--
-- Purpose:
--   Remove only the 14 explicitly named current-scope tables left behind by a
--   failed fresh installation, so setup.sql can be run again.
--
-- Safety controls:
--   * Refuses to run outside AI_POD_STAFFING.
--   * Requires all 14 expected tables to be present.
--   * Refuses to drop anything if any target table contains a row.
--   * Never discovers or drops tables by wildcard or naming pattern.
--   * Does not touch any other schema or any other table.
--
-- Run in Oracle SQL Developer with F5 (Run Script).
-- ============================================================================

SET SERVEROUTPUT ON SIZE UNLIMITED
SET FEEDBACK ON
SET VERIFY OFF
WHENEVER OSERROR EXIT FAILURE ROLLBACK
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK

PROMPT ============================================================
PROMPT Checking whether the failed empty setup is safe to reset

DECLARE
  TYPE t_names IS TABLE OF VARCHAR2(30);
  l_tables t_names := t_names(
    'APP_USER_ROLES',
    'ROLE_PERMISSIONS',
    'APP_ROLES',
    'RECOMMENDATIONS',
    'REQUIREMENTS',
    'REQUESTS',
    'AVAILABILITY',
    'PERSON_INTERESTS',
    'DELIVERABLE_SKILLS',
    'DELIVERABLES',
    'CUSTOMER_MAPPING',
    'PEOPLE',
    'INTERESTS',
    'PROJECT_TYPES'
  );
  l_session_user   VARCHAR2(128);
  l_current_schema VARCHAR2(128);
  l_existing       NUMBER;
  l_rows           NUMBER;
BEGIN
  l_session_user := UPPER(SYS_CONTEXT('USERENV', 'SESSION_USER'));
  l_current_schema := UPPER(SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA'));

  IF l_session_user <> 'AI_POD_STAFFING' THEN
    RAISE_APPLICATION_ERROR(-20201,
      'Reset stopped: expected session user AI_POD_STAFFING; found ' || l_session_user);
  END IF;

  IF l_current_schema <> 'AI_POD_STAFFING' THEN
    RAISE_APPLICATION_ERROR(-20202,
      'Reset stopped: expected current schema AI_POD_STAFFING; found ' || l_current_schema);
  END IF;

  SELECT COUNT(*)
    INTO l_existing
    FROM USER_TABLES
   WHERE TABLE_NAME IN (
     'PROJECT_TYPES', 'INTERESTS', 'PEOPLE', 'CUSTOMER_MAPPING',
     'DELIVERABLES', 'DELIVERABLE_SKILLS', 'PERSON_INTERESTS',
     'AVAILABILITY', 'REQUESTS', 'REQUIREMENTS', 'RECOMMENDATIONS',
     'APP_ROLES', 'ROLE_PERMISSIONS', 'APP_USER_ROLES'
   );

  IF l_existing <> 14 THEN
    RAISE_APPLICATION_ERROR(-20203,
      'Reset stopped: expected all 14 current-scope tables; found ' || l_existing || '.');
  END IF;

  FOR i IN 1 .. l_tables.COUNT LOOP
    EXECUTE IMMEDIATE
      'SELECT COUNT(*) FROM ' || DBMS_ASSERT.SIMPLE_SQL_NAME(l_tables(i))
      INTO l_rows;

    IF l_rows <> 0 THEN
      RAISE_APPLICATION_ERROR(-20204,
        'Reset stopped: ' || l_tables(i) || ' contains ' || l_rows || ' row(s).');
    END IF;
  END LOOP;

  DBMS_OUTPUT.PUT_LINE('Safety checks passed: all 14 target tables are empty.');

  FOR i IN 1 .. l_tables.COUNT LOOP
    EXECUTE IMMEDIATE
      'DROP TABLE ' || DBMS_ASSERT.SIMPLE_SQL_NAME(l_tables(i)) ||
      ' CASCADE CONSTRAINTS PURGE';
    DBMS_OUTPUT.PUT_LINE('Dropped ' || l_tables(i));
  END LOOP;

  DBMS_OUTPUT.PUT_LINE('Empty failed setup removed successfully.');
  DBMS_OUTPUT.PUT_LINE('No other tables or schemas were changed.');
END;
/

PROMPT ============================================================
PROMPT RESET COMPLETED SUCCESSFULLY
PROMPT You can now run setup.sql again using F5.
PROMPT ============================================================

