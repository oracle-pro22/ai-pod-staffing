-- Additive Supervisor/selection storage. F5 as AI_POD_STAFFING, all services stopped.
-- No catalogue, roles, people, assignments, policies or runtime flags are changed.
SET SERVEROUTPUT ON
SET DEFINE OFF
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK
DECLARE
  n NUMBER;
  PROCEDURE install(object_name_ VARCHAR2, ddl VARCHAR2) IS
  BEGIN
    SELECT COUNT(*) INTO n FROM user_objects WHERE object_name=object_name_;
    IF n=0 THEN
      EXECUTE IMMEDIATE ddl;
      DBMS_OUTPUT.PUT_LINE('Created '||object_name_);
    ELSE
      DBMS_OUTPUT.PUT_LINE('Retained '||object_name_||'; schema verification is required before restart.');
    END IF;
  END;
BEGIN
  IF USER<>'AI_POD_STAFFING' OR SYS_CONTEXT('USERENV','CURRENT_SCHEMA')<>'AI_POD_STAFFING' THEN
    RAISE_APPLICATION_ERROR(-20001,'Use AI_POD_STAFFING only.');
  END IF;
  EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL DDL';
  EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL DML';
  SELECT COUNT(*) INTO n FROM staffing_runtime WHERE runtime_id=1 AND agents_enabled='N' AND notifications_enabled='N';
  IF n<>1 THEN RAISE_APPLICATION_ERROR(-20001,'Disable agents and notifications while services are stopped before upgrading.'); END IF;
  SELECT COUNT(*) INTO n FROM agent_executions WHERE status IN ('QUEUED','RUNNING');
  IF n<>0 THEN RAISE_APPLICATION_ERROR(-20001,'Resolve queued/running executions before upgrading. Do not delete history.'); END IF;
  install('MVP_P2_REVIEWS',q'~CREATE TABLE mvp_p2_reviews (
    proposal_id VARCHAR2(30) NOT NULL,
    review_json CLOB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    CONSTRAINT mp2_review_pk PRIMARY KEY(proposal_id),
    CONSTRAINT mp2_review_proposal FOREIGN KEY(proposal_id) REFERENCES pod_proposals(proposal_id),
    CONSTRAINT mp2_review_json CHECK(review_json IS JSON STRICT WITH UNIQUE KEYS)
  )~');
  install('MVP_P2_SELECTIONS',q'~CREATE TABLE mvp_p2_selections (
    selection_id VARCHAR2(30) NOT NULL,
    proposal_id VARCHAR2(30) NOT NULL,
    revision NUMBER(10) NOT NULL,
    actor_subject VARCHAR2(255) NOT NULL,
    idempotency_key VARCHAR2(64) NOT NULL,
    body_hash VARCHAR2(64) NOT NULL,
    review_json CLOB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    CONSTRAINT mp2_selection_pk PRIMARY KEY(selection_id),
    CONSTRAINT mp2_selection_proposal FOREIGN KEY(proposal_id) REFERENCES mvp_p2_reviews(proposal_id),
    CONSTRAINT mp2_selection_revision UNIQUE(proposal_id,revision),
    CONSTRAINT mp2_selection_idem UNIQUE(idempotency_key),
    CONSTRAINT mp2_selection_positive CHECK(revision>0),
    CONSTRAINT mp2_selection_json CHECK(review_json IS JSON STRICT WITH UNIQUE KEYS)
  )~');
  install('MVP_P2_DECISIONS',q'~CREATE TABLE mvp_p2_decisions (
    decision_id VARCHAR2(30) NOT NULL,
    source_proposal_id VARCHAR2(30) NOT NULL,
    source_proposal_version NUMBER(10) NOT NULL,
    selection_id VARCHAR2(30),
    CONSTRAINT mp2_decision_pk PRIMARY KEY(decision_id),
    CONSTRAINT mp2_decision_parent FOREIGN KEY(decision_id) REFERENCES approval_decisions(decision_id),
    CONSTRAINT mp2_decision_source FOREIGN KEY(source_proposal_id) REFERENCES pod_proposals(proposal_id),
    CONSTRAINT mp2_decision_selection FOREIGN KEY(selection_id) REFERENCES mvp_p2_selections(selection_id),
    CONSTRAINT mp2_decision_version CHECK(source_proposal_version>0)
  )~');
  install('MP2_REVIEW_FREEZE',q'~CREATE TRIGGER mp2_review_freeze
    BEFORE UPDATE OR DELETE ON mvp_p2_reviews FOR EACH ROW
    BEGIN RAISE_APPLICATION_ERROR(-20270,'Selection history is append-only.'); END;~');
  install('MP2_SELECTION_FREEZE',q'~CREATE TRIGGER mp2_selection_freeze
    BEFORE UPDATE OR DELETE ON mvp_p2_selections FOR EACH ROW
    BEGIN RAISE_APPLICATION_ERROR(-20270,'Selection history is append-only.'); END;~');
  install('MP2_DECISION_FREEZE',q'~CREATE TRIGGER mp2_decision_freeze
    BEFORE UPDATE OR DELETE ON mvp_p2_decisions FOR EACH ROW
    BEGIN RAISE_APPLICATION_ERROR(-20270,'Selection history is append-only.'); END;~');
  DBMS_OUTPUT.PUT_LINE('Schema prepared. Run python -m app.selection_schema --env-file .env before restarting services.');
END;
/
