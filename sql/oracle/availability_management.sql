WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK
SET SERVEROUTPUT ON

DECLARE
  l_user VARCHAR2(128) := SYS_CONTEXT('USERENV', 'SESSION_USER');
  l_schema VARCHAR2(128) := SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA');
  l_count NUMBER;
BEGIN
  IF l_user <> 'AI_POD_STAFFING' OR l_schema <> 'AI_POD_STAFFING' THEN
    RAISE_APPLICATION_ERROR(-20901, 'Run this migration as AI_POD_STAFFING in its own schema.');
  END IF;

  SELECT COUNT(*) INTO l_count FROM user_tab_columns
   WHERE table_name='AVAILABILITY' AND column_name='STATUS';
  IF l_count=0 THEN
    EXECUTE IMMEDIATE q'[ALTER TABLE availability ADD (
      status VARCHAR2(12) DEFAULT 'ACTIVE' NOT NULL,
      cancelled_at TIMESTAMP WITH TIME ZONE,
      cancelled_by VARCHAR2(255))]';
  END IF;

  SELECT COUNT(*) INTO l_count FROM user_constraints
   WHERE table_name='AVAILABILITY' AND constraint_name='CK_AVAIL_STATUS';
  IF l_count=0 THEN
    EXECUTE IMMEDIATE q'[ALTER TABLE availability ADD CONSTRAINT ck_avail_status
      CHECK ((status='ACTIVE' AND cancelled_at IS NULL AND cancelled_by IS NULL)
          OR (status='CANCELLED' AND cancelled_at IS NOT NULL AND cancelled_by IS NOT NULL))]';
  END IF;

  SELECT COUNT(*) INTO l_count FROM user_indexes WHERE index_name='IDX_AVAIL_ACTIVE_PERSON_DATES';
  IF l_count=0 THEN
    EXECUTE IMMEDIATE 'CREATE INDEX idx_avail_active_person_dates ON availability(person_id,status,starts_on,ends_on)';
  END IF;

  DBMS_OUTPUT.PUT_LINE('Availability edit/cancel and external commitment schema installed.');
END;
/
COMMIT;
