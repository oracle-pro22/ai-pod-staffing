-- F5 as AI_POD_STAFFING with every API/worker/web using this schema stopped.
-- Never rerun setup or roster cleanup. DDL commits independently; retain backups.
SET SERVEROUTPUT ON
SET DEFINE OFF
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK
DECLARE
  n NUMBER;
  PROCEDURE install(name_ VARCHAR2, ddl_ VARCHAR2) IS
  BEGIN
    SELECT COUNT(*) INTO n FROM user_objects WHERE object_name=name_;
    IF n=0 THEN EXECUTE IMMEDIATE ddl_; DBMS_OUTPUT.PUT_LINE('Created '||name_);
    ELSE DBMS_OUTPUT.PUT_LINE('Retained '||name_||'; verify before restart.'); END IF;
  END;
  PROCEDURE add_constraint(name_ VARCHAR2, ddl_ VARCHAR2) IS
  BEGIN
    SELECT COUNT(*) INTO n FROM user_constraints WHERE constraint_name=name_;
    IF n=0 THEN EXECUTE IMMEDIATE ddl_; END IF;
  END;
BEGIN
  IF USER<>'AI_POD_STAFFING' OR SYS_CONTEXT('USERENV','CURRENT_SCHEMA')<>'AI_POD_STAFFING' THEN
    RAISE_APPLICATION_ERROR(-20001,'Connect as AI_POD_STAFFING.');
  END IF;
  EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL DDL';
  EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL DML';
  SELECT COUNT(*) INTO n FROM staffing_runtime WHERE runtime_id=1 AND agents_enabled='N' AND notifications_enabled='N';
  IF n<>1 THEN RAISE_APPLICATION_ERROR(-20001,'Stop all services and disable runtime execution and notifications first.'); END IF;
  SELECT COUNT(*) INTO n FROM agent_executions WHERE status IN ('QUEUED','RUNNING');
  IF n<>0 THEN RAISE_APPLICATION_ERROR(-20001,'Resolve active jobs first; do not delete history.'); END IF;
  SELECT COUNT(*) INTO n FROM user_tables WHERE table_name IN ('MVP_P2_REVIEWS','MVP_P2_SELECTIONS','MVP_P2_DECISIONS');
  IF n<>3 THEN RAISE_APPLICATION_ERROR(-20001,'Verified MVP Phase 2 is required.'); END IF;
  install('MVP_P3_DDL_BACKUP',q'~CREATE TABLE mvp_p3_ddl_backup (
    object_name VARCHAR2(128) PRIMARY KEY, ddl_text CLOB NOT NULL,
    captured_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL)~');
  FOR obj IN (SELECT table_name FROM user_tables WHERE table_name IN ('POD_PROPOSALS','POD_PROPOSAL_MEMBERS')) LOOP
    -- Dynamic SQL is required: this table may not exist when the block compiles.
    EXECUTE IMMEDIATE 'SELECT COUNT(*) FROM mvp_p3_ddl_backup WHERE object_name=:name' INTO n USING obj.table_name;
    IF n=0 THEN
      EXECUTE IMMEDIATE 'INSERT INTO mvp_p3_ddl_backup(object_name,ddl_text) VALUES(:name,DBMS_METADATA.GET_DDL(''TABLE'',:tableName,USER))'
        USING obj.table_name,obj.table_name;
      COMMIT;
    END IF;
  END LOOP;
  -- Nullable execution is only legal for an explicitly MANUAL-origin proposal.
  SELECT COUNT(*) INTO n FROM user_tab_columns WHERE table_name='POD_PROPOSALS' AND column_name='ORIGIN_TYPE';
  IF n=0 THEN EXECUTE IMMEDIATE 'ALTER TABLE pod_proposals ADD (origin_type VARCHAR2(8) DEFAULT ''AGENT'' NOT NULL)'; END IF;
  SELECT COUNT(*) INTO n FROM user_tab_columns WHERE table_name='POD_PROPOSAL_MEMBERS' AND column_name='MANUAL_FLAG';
  IF n=0 THEN EXECUTE IMMEDIATE 'ALTER TABLE pod_proposal_members ADD (manual_flag CHAR(1) DEFAULT ''N'' NOT NULL)'; END IF;
  SELECT COUNT(*) INTO n FROM user_tab_columns WHERE table_name='POD_PROPOSALS' AND column_name='EXECUTION_ID' AND nullable='N';
  IF n=1 THEN EXECUTE IMMEDIATE 'ALTER TABLE pod_proposals MODIFY (execution_id NULL)'; END IF;
  SELECT COUNT(*) INTO n FROM user_tab_columns WHERE table_name='POD_PROPOSAL_MEMBERS' AND column_name='SCORE' AND nullable='N';
  IF n=1 THEN EXECUTE IMMEDIATE 'ALTER TABLE pod_proposal_members MODIFY (score NULL)'; END IF;
  add_constraint('MP3_PROPOSAL_ORIGIN',q'~ALTER TABLE pod_proposals ADD CONSTRAINT mp3_proposal_origin CHECK
    ((origin_type='AGENT' AND execution_id IS NOT NULL) OR (origin_type='MANUAL' AND execution_id IS NULL))~');
  add_constraint('MP3_PROPOSAL_REQUEST',q'~ALTER TABLE pod_proposals ADD CONSTRAINT mp3_proposal_request FOREIGN KEY(request_id) REFERENCES requests(request_id)~');
  add_constraint('MP3_MEMBER_SCORE',q'~ALTER TABLE pod_proposal_members ADD CONSTRAINT mp3_member_score CHECK
    ((manual_flag='Y' AND score IS NULL) OR (manual_flag='N' AND score IS NOT NULL))~');
  install('MVP_P3_DRAFTS',q'~CREATE TABLE mvp_p3_drafts (
    draft_id VARCHAR2(30) NOT NULL, request_id VARCHAR2(30) NOT NULL, request_revision NUMBER(10) NOT NULL,
    revision NUMBER(10) NOT NULL, policy_version VARCHAR2(60) NOT NULL, actor_subject VARCHAR2(255) NOT NULL,
    idempotency_key VARCHAR2(64) NOT NULL, body_hash VARCHAR2(64) NOT NULL, preview_json CLOB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    CONSTRAINT mp3_draft_pk PRIMARY KEY(draft_id),
    CONSTRAINT mp3_draft_ref UNIQUE(draft_id,request_id),
    CONSTRAINT mp3_draft_version UNIQUE(request_id,revision),
    CONSTRAINT mp3_draft_idem UNIQUE(idempotency_key),
    CONSTRAINT mp3_draft_request FOREIGN KEY(request_id) REFERENCES requests(request_id),
    CONSTRAINT mp3_draft_policy FOREIGN KEY(policy_version) REFERENCES staffing_policies(policy_version),
    CONSTRAINT mp3_draft_positive CHECK(request_revision>0 AND revision>0),
    CONSTRAINT mp3_draft_json CHECK(preview_json IS JSON STRICT WITH UNIQUE KEYS))~');
  install('MVP_P3_RESOLUTIONS',q'~CREATE TABLE mvp_p3_resolutions (
    draft_id VARCHAR2(30) NOT NULL, request_id VARCHAR2(30) NOT NULL, action_type VARCHAR2(12) NOT NULL,
    proposal_id VARCHAR2(30), decision_id VARCHAR2(30), actor_subject VARCHAR2(255) NOT NULL,
    idempotency_key VARCHAR2(64) NOT NULL, body_hash VARCHAR2(64) NOT NULL, reason VARCHAR2(2000),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    CONSTRAINT mp3_resolution_pk PRIMARY KEY(draft_id),
    CONSTRAINT mp3_resolution_idem UNIQUE(idempotency_key),
    CONSTRAINT mp3_resolution_draft FOREIGN KEY(draft_id,request_id) REFERENCES mvp_p3_drafts(draft_id,request_id),
    CONSTRAINT mp3_resolution_decision FOREIGN KEY(decision_id,proposal_id,request_id,action_type)
      REFERENCES approval_decisions(decision_id,proposal_id,request_id,action_type),
    CONSTRAINT mp3_resolution_action CHECK((action_type='DISCARDED' AND proposal_id IS NULL AND decision_id IS NULL)
      OR (action_type IN ('APPROVED','REJECTED') AND proposal_id IS NOT NULL AND decision_id IS NOT NULL)),
    CONSTRAINT mp3_resolution_reason CHECK(action_type<>'REJECTED' OR (reason IS NOT NULL AND REGEXP_LIKE(reason,'[^[:space:]]'))))~');
  install('MP3_DRAFT_FREEZE',q'~CREATE TRIGGER mp3_draft_freeze BEFORE UPDATE OR DELETE ON mvp_p3_drafts FOR EACH ROW
    BEGIN RAISE_APPLICATION_ERROR(-20280,'Manual history is append-only.'); END;~');
  install('MP3_RESOLUTION_FREEZE',q'~CREATE TRIGGER mp3_resolution_freeze BEFORE UPDATE OR DELETE ON mvp_p3_resolutions FOR EACH ROW
    BEGIN RAISE_APPLICATION_ERROR(-20280,'Manual history is append-only.'); END;~');
  install('MP3_ORIGIN_FREEZE',q'~CREATE TRIGGER mp3_origin_freeze BEFORE UPDATE ON pod_proposals FOR EACH ROW
    BEGIN IF :OLD.status<>'BUILDING' AND (:OLD.origin_type<>:NEW.origin_type OR
      NVL(:OLD.execution_id,'!')<>NVL(:NEW.execution_id,'!')) THEN
      RAISE_APPLICATION_ERROR(-20281,'Published origin is frozen.'); END IF; END;~');
  install('MP3_MEMBER_ORIGIN',q'~CREATE TRIGGER mp3_member_origin BEFORE INSERT OR UPDATE ON pod_proposal_members FOR EACH ROW
    DECLARE origin_ VARCHAR2(8); BEGIN
      SELECT origin_type INTO origin_ FROM pod_proposals WHERE proposal_id=:NEW.proposal_id;
      IF :NEW.manual_flag='Y' AND origin_<>'MANUAL' THEN RAISE_APPLICATION_ERROR(-20282,'Manual members need Captain manual origin.'); END IF;
    END;~');
  DBMS_OUTPUT.PUT_LINE('Phase 3 schema prepared. Catalogue, skills, roster and business history retained.');
  DBMS_OUTPUT.PUT_LINE('Run python -m app.manual_schema --env-file .env before restarting. Runtime switches remain OFF.');
EXCEPTION WHEN OTHERS THEN
  DBMS_OUTPUT.PUT_LINE('STOP: earlier Oracle DDL may already be committed. Retain all objects and backups; inspect and rerun this unchanged script. Do not reset or remove tables.');
  RAISE;
END;
/
