-- Roster Phase 2: shared Captain decisions, without changing ownership/history.
-- Run as AI_POD_STAFFING with application services stopped. Oracle DDL commits.
-- This does NOT archive/delete/import people, requests or catalogue data.
SET SERVEROUTPUT ON
SET DEFINE OFF
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK

DECLARE
  n NUMBER;
  cols VARCHAR2(4000);
  PROCEDURE demand(ok BOOLEAN, message VARCHAR2) IS
  BEGIN
    IF NOT ok OR ok IS NULL THEN RAISE_APPLICATION_ERROR(-20340, message); END IF;
  END;
  PROCEDURE backup_object(kind VARCHAR2, name VARCHAR2) IS
  BEGIN
    EXECUTE IMMEDIATE 'SELECT COUNT(*) FROM rm2_ddl_backup WHERE object_name=:1' INTO n USING name;
    IF n=0 THEN
      EXECUTE IMMEDIATE 'INSERT INTO rm2_ddl_backup(object_name,object_type,ddl_text) VALUES(:1,:2,:3)'
        USING name, kind, DBMS_METADATA.GET_DDL(kind,name,USER);
      COMMIT;
    END IF;
  END;
  PROCEDURE ensure_key(name VARCHAR2, tbl VARCHAR2, key_kind VARCHAR2,
                       key_columns VARCHAR2, parent_name VARCHAR2, parent_columns VARCHAR2, ddl VARCHAR2) IS
    actual user_constraints%ROWTYPE;
    parent user_constraints%ROWTYPE;
  BEGIN
    SELECT COUNT(*) INTO n FROM user_constraints WHERE constraint_name=name;
    IF n=0 THEN EXECUTE IMMEDIATE ddl; END IF;
    SELECT * INTO actual FROM user_constraints WHERE constraint_name=name;
    SELECT LISTAGG(column_name,',') WITHIN GROUP(ORDER BY position) INTO cols
      FROM user_cons_columns WHERE constraint_name=name;
    demand(actual.table_name=tbl AND actual.constraint_type=key_kind AND cols=key_columns
           AND actual.status='ENABLED' AND actual.validated='VALIDATED', 'Unexpected key: '||name);
    IF parent_name IS NOT NULL THEN
      SELECT * INTO parent FROM user_constraints WHERE constraint_name=actual.r_constraint_name;
      SELECT LISTAGG(column_name,',') WITHIN GROUP(ORDER BY position) INTO cols
        FROM user_cons_columns WHERE constraint_name=actual.r_constraint_name;
      demand(actual.r_owner=USER AND parent.table_name=parent_name AND cols=parent_columns
             AND actual.delete_rule='NO ACTION','Unexpected foreign key target: '||name);
    END IF;
  END;
BEGIN
  demand(USER='AI_POD_STAFFING' AND SYS_CONTEXT('USERENV','CURRENT_SCHEMA')='AI_POD_STAFFING',
         'Use the AI_POD_STAFFING schema only.');
  SELECT COUNT(*) INTO n FROM user_tables WHERE table_name IN
    ('APP_ACCOUNTS','APP_USER_ROLES','ROLE_PERMISSIONS','REQUESTS','POD_PROPOSALS','APPROVAL_DECISIONS','STAFFING_RUNTIME','AGENT_EXECUTIONS');
  demand(n=8, 'Required account/decision/runtime schema is missing.');
  SELECT COUNT(*) INTO n FROM staffing_runtime
    WHERE runtime_id=1 AND agents_enabled='N' AND notifications_enabled='N';
  demand(n=1, 'Stop application services and disable agents/notifications before running this migration.');
  SELECT COUNT(*) INTO n FROM agent_executions WHERE status IN ('QUEUED','RUNNING');
  demand(n=0, 'Resolve queued/running executions through the application before running this migration.');
  SELECT COUNT(*) INTO n FROM user_triggers WHERE trigger_name='P2_DECISION_REVIEW' AND status='ENABLED';
  demand(n=1, 'Existing decision guard must be present and enabled.');
  SELECT COUNT(*) INTO n FROM user_objects WHERE object_name='RM2_DDL_BACKUP';
  IF n=0 THEN
    EXECUTE IMMEDIATE 'CREATE TABLE rm2_ddl_backup (
      object_name VARCHAR2(128) PRIMARY KEY, object_type VARCHAR2(30) NOT NULL,
      ddl_text CLOB NOT NULL, saved_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL)';
  END IF;
  SELECT COUNT(*) INTO n FROM user_tables WHERE table_name='RM2_DDL_BACKUP';
  demand(n=1,'RM2_DDL_BACKUP must be a table.');
  SELECT COUNT(*) INTO n FROM user_tab_columns WHERE table_name='RM2_DDL_BACKUP';
  demand(n=4,'Unexpected RM2_DDL_BACKUP column set.');
  SELECT COUNT(*) INTO n FROM user_tab_columns WHERE table_name='RM2_DDL_BACKUP' AND nullable='N' AND (
    (column_name='OBJECT_NAME' AND data_type='VARCHAR2' AND char_length=128)
    OR (column_name='OBJECT_TYPE' AND data_type='VARCHAR2' AND char_length=30)
    OR (column_name='DDL_TEXT' AND data_type='CLOB')
    OR (column_name='SAVED_AT' AND data_type='TIMESTAMP(6) WITH TIME ZONE'));
  demand(n=4,'Unexpected RM2_DDL_BACKUP column definitions.');
  SELECT COUNT(*) INTO n FROM user_constraints c WHERE c.table_name='RM2_DDL_BACKUP'
    AND c.constraint_type='P' AND c.status='ENABLED' AND c.validated='VALIDATED'
    AND (SELECT COUNT(*) FROM user_cons_columns cc WHERE cc.constraint_name=c.constraint_name)=1
    AND EXISTS (SELECT 1 FROM user_cons_columns cc WHERE cc.constraint_name=c.constraint_name AND cc.column_name='OBJECT_NAME');
  demand(n=1,'Unexpected RM2_DDL_BACKUP primary key.');
  backup_object('TABLE','POD_PROPOSALS');
  backup_object('TABLE','APPROVAL_DECISIONS');
  backup_object('TRIGGER','P2_DECISION_REVIEW');

  -- Install replacement integrity before removing the owner-equality FK.
  ensure_key('RM2_PROPOSAL_REQUEST','POD_PROPOSALS','U','PROPOSAL_ID,REQUEST_ID',NULL,NULL,
    'ALTER TABLE pod_proposals ADD CONSTRAINT rm2_proposal_request UNIQUE(proposal_id,request_id)');
  ensure_key('RM2_DECISION_REQUEST','APPROVAL_DECISIONS','R','PROPOSAL_ID,REQUEST_ID',
    'POD_PROPOSALS','PROPOSAL_ID,REQUEST_ID',
    'ALTER TABLE approval_decisions ADD CONSTRAINT rm2_decision_request FOREIGN KEY(proposal_id,request_id)
     REFERENCES pod_proposals(proposal_id,request_id)');
  ensure_key('RM2_DECISION_ACTOR','APPROVAL_DECISIONS','R','CAPTAIN_PERSON_ID','PEOPLE','PERSON_ID',
    'ALTER TABLE approval_decisions ADD CONSTRAINT rm2_decision_actor FOREIGN KEY(captain_person_id)
     REFERENCES people(person_id)');
  SELECT COUNT(*) INTO n FROM user_constraints WHERE constraint_name='P2_DECISION_PROPOSAL';
  IF n=1 THEN
    ensure_key('P2_DECISION_PROPOSAL','APPROVAL_DECISIONS','R','PROPOSAL_ID,REQUEST_ID,CAPTAIN_PERSON_ID',
      'POD_PROPOSALS','PROPOSAL_ID,REQUEST_ID,RESPONSIBLE_CAPTAIN_ID',NULL);
    EXECUTE IMMEDIATE 'ALTER TABLE approval_decisions DROP CONSTRAINT p2_decision_proposal';
  END IF;
END;
/

CREATE OR REPLACE TRIGGER p2_decision_review
BEFORE INSERT ON approval_decisions FOR EACH ROW
DECLARE
  proposal_status VARCHAR2(20);
  request_status VARCHAR2(20);
  proposal_revision NUMBER;
  current_revision NUMBER;
  proposal_request VARCHAR2(30);
  proposal_owner VARCHAR2(30);
  request_owner VARCHAR2(30);
  permitted NUMBER;
BEGIN
  -- Match the application's request-before-proposal serialization order.
  SELECT request_revision,responsible_captain_id,status
    INTO current_revision,request_owner,request_status
    FROM requests WHERE request_id=:NEW.request_id FOR UPDATE;
  SELECT status,request_revision,request_id,responsible_captain_id
    INTO proposal_status,proposal_revision,proposal_request,proposal_owner
    FROM pod_proposals WHERE proposal_id=:NEW.proposal_id FOR UPDATE;
  IF proposal_status<>'READY_FOR_REVIEW' OR request_status NOT IN ('NEEDS_RECOMMENDATION','IN_REVIEW')
     OR proposal_revision<>current_revision OR proposal_request<>:NEW.request_id
     OR request_owner IS NULL OR proposal_owner<>request_owner THEN
    RAISE_APPLICATION_ERROR(-20153,'Proposal is stale, not in review or does not match its request owner.');
  END IF;
  SELECT COUNT(*) INTO permitted FROM app_user_roles ur
    JOIN people p ON p.person_id=ur.person_id AND p.active_flag='Y'
    JOIN app_roles ar ON ar.role_code=ur.role_code AND ar.active_flag='Y'
    JOIN role_permissions rp ON rp.role_code=ar.role_code AND rp.resource_code='AI_FITMENT'
    WHERE ur.identity_subject=:NEW.actor_subject AND ur.person_id=:NEW.captain_person_id
      AND ur.role_code='POD_CAPTAIN' AND ur.active_flag='Y'
      AND ur.effective_from<=TRUNC(SYSDATE)
      AND (ur.effective_to IS NULL OR ur.effective_to>=TRUNC(SYSDATE))
      AND rp.can_view='Y' AND rp.can_approve='Y'
      AND (rp.access_scope='FULL' OR (rp.access_scope IN ('OWN','SCOPED') AND ur.person_id=request_owner))
      AND (NOT EXISTS (SELECT 1 FROM app_accounts a WHERE a.identity_subject=ur.identity_subject OR a.person_id=ur.person_id)
           OR EXISTS (SELECT 1 FROM app_accounts a WHERE a.identity_subject=ur.identity_subject
                      AND a.person_id=ur.person_id AND a.active_flag='Y'));
  IF permitted<>1 THEN
    RAISE_APPLICATION_ERROR(-20341,'An active Captain identity and current approval permission are required.');
  END IF;
END;
/

DECLARE n NUMBER;
BEGIN
  SELECT COUNT(*) INTO n FROM user_errors WHERE name='P2_DECISION_REVIEW' AND type='TRIGGER';
  IF n<>0 THEN RAISE_APPLICATION_ERROR(-20342,'Decision trigger compilation failed; keep services stopped.'); END IF;
  SELECT COUNT(*) INTO n FROM user_objects WHERE object_name='P2_DECISION_REVIEW' AND status='VALID';
  IF n<>1 THEN RAISE_APPLICATION_ERROR(-20342,'Decision trigger is invalid; keep services stopped.'); END IF;
  DBMS_OUTPUT.PUT_LINE('Shared Captain decision schema installed. No roster/history/policy data changed.');
  DBMS_OUTPUT.PUT_LINE('Run python -m app.roster_schema --env-file .env before restarting services.');
END;
/
