-- Run as the application schema with API, web and worker stopped.
-- Oracle DDL commits independently. Repeat-safe additions; never deletes data.
-- Keep services stopped if any step fails. Take a fresh demo baseline AFTER this migration.
-- After an event uses EFFECTIVE_UNTIL, do not downgrade to an older application:
-- older code ignores the cutoff. Use forward repair or a verified compatible restore.
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK
SET SERVEROUTPUT ON
DECLARE
  n NUMBER;
BEGIN
  IF USER<>'AI_POD_STAFFING' OR SYS_CONTEXT('USERENV','CURRENT_SCHEMA')<>'AI_POD_STAFFING' THEN
    raise_application_error(-20340,'Run as AI_POD_STAFFING in its own schema.');
  END IF;
  SELECT COUNT(*) INTO n FROM staffing_runtime WHERE runtime_id=1 AND agents_enabled='N' AND notifications_enabled='N';
  IF n<>1 THEN raise_application_error(-20340,'Stop services and disable agents/notifications before migrating.'); END IF;
  SELECT COUNT(*) INTO n FROM agent_executions WHERE status IN ('QUEUED','RUNNING');
  IF n<>0 THEN raise_application_error(-20340,'Resolve queued/running executions before migrating.'); END IF;
  SELECT COUNT(*) INTO n FROM availability WHERE event_type='Commitment' AND (capacity_kind<>'EXTERNAL_WORK' OR capacity_kind IS NULL);
  IF n<>0 THEN raise_application_error(-20342,'Legacy Commitment records have ambiguous capacity classification. Review them before migration; no hours changed.'); END IF;
  SELECT COUNT(*) INTO n FROM availability a JOIN availability b ON a.person_id=b.person_id
    AND a.starts_on=b.starts_on AND a.ends_on=b.ends_on AND a.title=b.title
    WHERE a.event_type='Commitment' AND a.capacity_kind='EXTERNAL_WORK' AND b.event_type='External commitment';
  IF n<>0 THEN raise_application_error(-20341,'Conflicting legacy commitment names exist. Reconcile them before normalizing; no records deleted.'); END IF;
END;
/
DECLARE
  n NUMBER;
BEGIN
  SELECT COUNT(*) INTO n FROM user_tab_columns WHERE table_name='AVAILABILITY' AND column_name='EFFECTIVE_UNTIL';
  IF n=0 THEN EXECUTE IMMEDIATE 'ALTER TABLE availability ADD (effective_until DATE)'; END IF;
  SELECT COUNT(*) INTO n FROM user_tab_columns WHERE table_name='AVAILABILITY' AND column_name='REVISION';
  IF n=0 THEN EXECUTE IMMEDIATE 'ALTER TABLE availability ADD (revision NUMBER(10) DEFAULT 1 NOT NULL)'; END IF;
  SELECT COUNT(*) INTO n FROM user_constraints WHERE constraint_name='AVAIL_REVISION_CK';
  IF n=0 THEN EXECUTE IMMEDIATE 'ALTER TABLE availability ADD CONSTRAINT avail_revision_ck CHECK (revision>=1)'; END IF;
  SELECT COUNT(*) INTO n FROM user_constraints WHERE constraint_name='AVAIL_CUTOFF_CK';
  IF n=0 THEN EXECUTE IMMEDIATE 'ALTER TABLE availability ADD CONSTRAINT avail_cutoff_ck CHECK (effective_until IS NULL OR effective_until<=ends_on)'; END IF;
END;
/
DECLARE
  old_version NUMBER;
BEGIN
  FOR p IN (SELECT DISTINCT person_id FROM availability WHERE event_type='Commitment' AND capacity_kind='EXTERNAL_WORK' ORDER BY person_id) LOOP
    SELECT availability_version INTO old_version FROM people WHERE person_id=p.person_id FOR UPDATE;
    UPDATE availability SET event_type='External commitment',revision=revision+1,updated_at=SYSTIMESTAMP
      WHERE person_id=p.person_id AND event_type='Commitment' AND capacity_kind='EXTERNAL_WORK';
    -- This rename changes no hours. Preserve valid caches, but never bless an
    -- already-stale version. P2_AVAIL_VERSION increments the person's version.
    UPDATE person_capacity_days SET availability_version=(SELECT availability_version FROM people WHERE person_id=p.person_id)
      WHERE person_id=p.person_id AND availability_version=old_version;
  END LOOP;
  DBMS_OUTPUT.PUT_LINE('Lifecycle columns installed; external commitment labels normalized. No accounts, assignments or reported POD claims changed.');
END;
/
COMMIT;
