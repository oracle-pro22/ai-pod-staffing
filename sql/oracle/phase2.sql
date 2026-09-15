-- Agentic backend phase 2, migration AIPS_BACKEND_P2_V1.
-- Run THIS file with F5 in a NEW AIPOD worksheet as AI_POD_STAFFING.
-- Stop ONLY this application's writers first. Export a backup before DDL.
-- Additive: no existing business row is updated/deleted and no table is dropped.
-- DDL commits independently: ROLLBACK cannot undo completed schema changes.
-- Resume by rerunning this identical file; unknown objects/schema drift STOP.
-- Runner correction: helper counts are local. DDL payloads/journal hashes unchanged.
SET DEFINE OFF
SET SERVEROUTPUT ON SIZE UNLIMITED
SET SQLBLANKLINES ON
SET VERIFY OFF
WHENEVER OSERROR EXIT FAILURE ROLLBACK
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK

PROMPT Checking AI_POD_STAFFING baseline and migration ownership
DECLARE
 n NUMBER; marker VARCHAR2(4000);
 PROCEDURE demand(ok BOOLEAN, msg VARCHAR2) IS
 BEGIN IF ok IS NULL OR NOT ok THEN RAISE_APPLICATION_ERROR(-20100,msg); END IF; END;
BEGIN
 demand(USER='AI_POD_STAFFING' AND SYS_CONTEXT('USERENV','SESSION_USER')='AI_POD_STAFFING'
 AND SYS_CONTEXT('USERENV','CURRENT_SCHEMA')='AI_POD_STAFFING','STOP: use AI_POD_STAFFING directly, not ADMIN.');
 EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL DML';
 EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL QUERY';
 EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL DDL';
 EXECUTE IMMEDIATE 'ALTER SESSION SET DDL_LOCK_TIMEOUT = 5';
 SELECT COUNT(*) INTO n FROM user_tables WHERE table_name IN ('PROJECT_TYPES','INTERESTS','PEOPLE','CUSTOMER_MAPPING','DELIVERABLES','DELIVERABLE_SKILLS','PERSON_INTERESTS','AVAILABILITY','REQUESTS','REQUIREMENTS','RECOMMENDATIONS','APP_ROLES','ROLE_PERMISSIONS','APP_USER_ROLES');
 demand(n=14,'Expected enhanced 14-table application baseline is missing.');
 SELECT COUNT(*) INTO n FROM user_tab_columns WHERE
 (table_name='PEOPLE' AND column_name IN ('SKILLS_VERSION','DELIVERABLE_EXPERIENCE_JSON'))
 OR (table_name='INTERESTS' AND column_name IN ('ASSESSMENT_TYPE','DERIVED_ROLE_CODE'))
 OR (table_name='PERSON_INTERESTS' AND column_name='INTERESTED_FLAG')
 OR (table_name='DELIVERABLES' AND column_name='ACTIVE_FLAG');
 demand(n=6,'Apply catalogue, self-skills and deliverable-experience migrations first.');
 SELECT COUNT(*) INTO n FROM app_roles WHERE active_flag='Y' AND role_code IN
 ('POD_CAPTAIN','POD_LEAD','POD_MEMBER','SYSTEM_ADMINISTRATOR');
 demand(n=4,'The four official active roles are required.');
 SELECT COUNT(*) INTO n FROM user_objects WHERE object_name='AIPS_P2_MIGRATION';
 IF n=0 THEN
   SELECT COUNT(*) INTO n FROM user_objects WHERE object_name IN ('STAFFING_POLICIES','ELIGIBILITY_RULES','LOAD_GUARDRAILS','SCORING_WEIGHTS','AGENT_EXECUTIONS','AGENT_EXECUTION_EVENTS','POD_PROPOSALS','POD_PROPOSAL_MEMBERS','APPROVAL_DECISIONS','POD_ASSIGNMENTS','ASSIGNMENT_DAYS','PERSON_CAPACITY_DAYS','AUDIT_EVENTS','NOTIFICATION_OUTBOX','STAFFING_RUNTIME','P2_EXEC_QUEUE','P2_EXEC_REQUEST','P2_EXEC_ACTIVE','P2_PROP_REVIEW','P2_ASSIGN_ACTIVE','P2_ASSIGN_PERSON','P2_ASSIGN_DATES','P2_OUTBOX_PENDING','P2_AUDIT_ENTITY','P2_CAPTAIN_REQUEST','P2_AUDIT_APPEND','P2_DECISION_APPEND','P2_EVENT_APPEND','P2_RULE_FREEZE','P2_LOAD_FREEZE','P2_WEIGHT_FREEZE','P2_POLICY_FREEZE','P2_MEMBER_FREEZE','P2_REQUEST_REVISION','P2_AVAIL_VERSION','P2_CAPACITY_VERSION','P2_DAY_VERSION','P2_ASSIGN_VERSION','P2_PROPOSAL_FREEZE','P2_DECISION_REVIEW','P2_DAY_BOUNDS');
   demand(n=0,'A phase-2 target name already exists without a migration journal. No object will be overwritten.');
   SELECT COUNT(*) INTO n FROM user_tab_columns WHERE
     (table_name='PEOPLE' AND column_name IN ('WEEKLY_WORK_HOURS','WORKLOAD_VERSION','STAFFING_SEED_BATCH','AVAILABILITY_VERSION'))
     OR (table_name='REQUESTS' AND column_name IN ('REQUEST_REVISION','RESPONSIBLE_CAPTAIN_ID','AGENT_ENABLED','STAFFING_SEED_BATCH'))
     OR (table_name='REQUIREMENTS' AND column_name='MANDATORY_FLAG')
     OR (table_name='AVAILABILITY' AND column_name='CAPACITY_KIND');
   demand(n=0,'Phase-2 columns exist without a migration journal. Stop and review.');
   EXECUTE IMMEDIATE q'~CREATE TABLE AI_POD_STAFFING.AIPS_P2_MIGRATION (
     step_key VARCHAR2(80) PRIMARY KEY, object_type VARCHAR2(20) NOT NULL,
     object_name VARCHAR2(128) NOT NULL, script_hash VARCHAR2(64) NOT NULL,
     before_hash VARCHAR2(64), after_hash VARCHAR2(64),
     state VARCHAR2(12) NOT NULL CHECK (state IN ('STARTED','APPLIED')),
     applied_at TIMESTAMP WITH TIME ZONE,
     original_rows NUMBER
   )~';
   EXECUTE IMMEDIATE 'COMMENT ON TABLE AI_POD_STAFFING.AIPS_P2_MIGRATION IS ''AIPS_BACKEND_P2_V1''';
 ELSE
   SELECT MAX(comments) INTO marker FROM user_tab_comments WHERE table_name='AIPS_P2_MIGRATION';
   demand(marker='AIPS_BACKEND_P2_V1','Unrecognised migration journal. Stop and review.');
 END IF;
END;
/

DECLARE
 n NUMBER; marker VARCHAR2(4000);
 PROCEDURE demand(ok BOOLEAN, msg VARCHAR2) IS
 BEGIN IF ok IS NULL OR NOT ok THEN RAISE_APPLICATION_ERROR(-20101,msg); END IF; END;
 FUNCTION digest(txt VARCHAR2) RETURN VARCHAR2 IS v VARCHAR2(64);
 BEGIN SELECT LOWER(RAWTOHEX(STANDARD_HASH(txt,'SHA256'))) INTO v FROM dual; RETURN v; END;
 FUNCTION fingerprint(kind VARCHAR2, obj VARCHAR2) RETURN VARCHAR2 IS
   c CLOB;
   object_count NUMBER;
 BEGIN
   SELECT COUNT(*) INTO object_count FROM user_objects WHERE object_name=obj AND object_type=kind;
   IF object_count=0 THEN RETURN NULL; END IF;
   c := DBMS_METADATA.GET_DDL(kind,obj,'AI_POD_STAFFING');
   demand(DBMS_LOB.GETLENGTH(c)<=32767,'Metadata too large for fingerprint: '||obj);
   RETURN digest(DBMS_LOB.SUBSTR(c,32767,1));
 END;
 PROCEDURE apply_step(k VARCHAR2, kind VARCHAR2, obj VARCHAR2, ddl_text VARCHAR2, existing BOOLEAN) IS
   rec AIPS_P2_MIGRATION%ROWTYPE;
   current_hash VARCHAR2(64); sql_hash VARCHAR2(64):=digest(ddl_text);
   journal_count NUMBER;
   compilation_error_count NUMBER;
 BEGIN
   SELECT COUNT(*) INTO journal_count FROM AIPS_P2_MIGRATION WHERE step_key=k;
   current_hash:=fingerprint(kind,obj);
   IF journal_count=0 THEN
     demand(existing OR current_hash IS NULL,'Unowned target object: '||obj);
     demand(NOT existing OR current_hash IS NOT NULL,'Missing baseline table: '||obj);
     INSERT INTO AIPS_P2_MIGRATION(step_key,object_type,object_name,script_hash,before_hash,state)
       VALUES(k,kind,obj,sql_hash,current_hash,'STARTED');
     COMMIT; -- Durable intent BEFORE any implicit DDL commit.
   ELSE
     SELECT * INTO rec FROM AIPS_P2_MIGRATION WHERE step_key=k;
     demand(rec.script_hash=sql_hash AND rec.object_type=kind AND rec.object_name=obj,'Migration file changed: '||k);
     IF rec.state='APPLIED' THEN
       demand(current_hash=rec.after_hash,'Schema drift detected: '||obj);
       DBMS_OUTPUT.PUT_LINE('Verified existing step: '||k); RETURN;
     END IF;
     demand((current_hash IS NULL AND rec.before_hash IS NULL) OR current_hash=rec.before_hash,
       'Interrupted DDL may already exist: '||obj||'. Manual metadata review required; no destructive retry.');
   END IF;
   EXECUTE IMMEDIATE ddl_text;
   IF kind='TRIGGER' THEN
     SELECT COUNT(*) INTO compilation_error_count FROM user_errors WHERE name=obj AND type='TRIGGER';
     demand(compilation_error_count=0,'Trigger compilation failed: '||obj||'. See USER_ERRORS; do not continue.');
   END IF;
   current_hash:=fingerprint(kind,obj);
   UPDATE AIPS_P2_MIGRATION SET state='APPLIED',after_hash=current_hash,applied_at=SYSTIMESTAMP WHERE step_key=k;
   COMMIT;
   DBMS_OUTPUT.PUT_LINE('Applied: '||k);
 END;
BEGIN
 DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM,'SEGMENT_ATTRIBUTES',FALSE);
 DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM,'STORAGE',FALSE);
 DBMS_METADATA.SET_TRANSFORM_PARAM(DBMS_METADATA.SESSION_TRANSFORM,'SQLTERMINATOR',FALSE);
 SELECT COUNT(*) INTO n FROM AIPS_P2_MIGRATION WHERE step_key='BASE_PROJECT_TYPES';
 IF n=0 THEN
 INSERT INTO AIPS_P2_MIGRATION(step_key,object_type,object_name,script_hash,state,original_rows,applied_at)
 SELECT 'BASE_PROJECT_TYPES','BASELINE','PROJECT_TYPES','baseline','APPLIED',COUNT(*),SYSTIMESTAMP FROM AI_POD_STAFFING.PROJECT_TYPES; COMMIT;
 END IF;
 SELECT COUNT(*) INTO n FROM AIPS_P2_MIGRATION WHERE step_key='BASE_INTERESTS';
 IF n=0 THEN
 INSERT INTO AIPS_P2_MIGRATION(step_key,object_type,object_name,script_hash,state,original_rows,applied_at)
 SELECT 'BASE_INTERESTS','BASELINE','INTERESTS','baseline','APPLIED',COUNT(*),SYSTIMESTAMP FROM AI_POD_STAFFING.INTERESTS; COMMIT;
 END IF;
 SELECT COUNT(*) INTO n FROM AIPS_P2_MIGRATION WHERE step_key='BASE_PEOPLE';
 IF n=0 THEN
 INSERT INTO AIPS_P2_MIGRATION(step_key,object_type,object_name,script_hash,state,original_rows,applied_at)
 SELECT 'BASE_PEOPLE','BASELINE','PEOPLE','baseline','APPLIED',COUNT(*),SYSTIMESTAMP FROM AI_POD_STAFFING.PEOPLE; COMMIT;
 END IF;
 SELECT COUNT(*) INTO n FROM AIPS_P2_MIGRATION WHERE step_key='BASE_CUSTOMER_MAPPING';
 IF n=0 THEN
 INSERT INTO AIPS_P2_MIGRATION(step_key,object_type,object_name,script_hash,state,original_rows,applied_at)
 SELECT 'BASE_CUSTOMER_MAPPING','BASELINE','CUSTOMER_MAPPING','baseline','APPLIED',COUNT(*),SYSTIMESTAMP FROM AI_POD_STAFFING.CUSTOMER_MAPPING; COMMIT;
 END IF;
 SELECT COUNT(*) INTO n FROM AIPS_P2_MIGRATION WHERE step_key='BASE_DELIVERABLES';
 IF n=0 THEN
 INSERT INTO AIPS_P2_MIGRATION(step_key,object_type,object_name,script_hash,state,original_rows,applied_at)
 SELECT 'BASE_DELIVERABLES','BASELINE','DELIVERABLES','baseline','APPLIED',COUNT(*),SYSTIMESTAMP FROM AI_POD_STAFFING.DELIVERABLES; COMMIT;
 END IF;
 SELECT COUNT(*) INTO n FROM AIPS_P2_MIGRATION WHERE step_key='BASE_DELIVERABLE_SKILLS';
 IF n=0 THEN
 INSERT INTO AIPS_P2_MIGRATION(step_key,object_type,object_name,script_hash,state,original_rows,applied_at)
 SELECT 'BASE_DELIVERABLE_SKILLS','BASELINE','DELIVERABLE_SKILLS','baseline','APPLIED',COUNT(*),SYSTIMESTAMP FROM AI_POD_STAFFING.DELIVERABLE_SKILLS; COMMIT;
 END IF;
 SELECT COUNT(*) INTO n FROM AIPS_P2_MIGRATION WHERE step_key='BASE_PERSON_INTERESTS';
 IF n=0 THEN
 INSERT INTO AIPS_P2_MIGRATION(step_key,object_type,object_name,script_hash,state,original_rows,applied_at)
 SELECT 'BASE_PERSON_INTERESTS','BASELINE','PERSON_INTERESTS','baseline','APPLIED',COUNT(*),SYSTIMESTAMP FROM AI_POD_STAFFING.PERSON_INTERESTS; COMMIT;
 END IF;
 SELECT COUNT(*) INTO n FROM AIPS_P2_MIGRATION WHERE step_key='BASE_AVAILABILITY';
 IF n=0 THEN
 INSERT INTO AIPS_P2_MIGRATION(step_key,object_type,object_name,script_hash,state,original_rows,applied_at)
 SELECT 'BASE_AVAILABILITY','BASELINE','AVAILABILITY','baseline','APPLIED',COUNT(*),SYSTIMESTAMP FROM AI_POD_STAFFING.AVAILABILITY; COMMIT;
 END IF;
 SELECT COUNT(*) INTO n FROM AIPS_P2_MIGRATION WHERE step_key='BASE_REQUESTS';
 IF n=0 THEN
 INSERT INTO AIPS_P2_MIGRATION(step_key,object_type,object_name,script_hash,state,original_rows,applied_at)
 SELECT 'BASE_REQUESTS','BASELINE','REQUESTS','baseline','APPLIED',COUNT(*),SYSTIMESTAMP FROM AI_POD_STAFFING.REQUESTS; COMMIT;
 END IF;
 SELECT COUNT(*) INTO n FROM AIPS_P2_MIGRATION WHERE step_key='BASE_REQUIREMENTS';
 IF n=0 THEN
 INSERT INTO AIPS_P2_MIGRATION(step_key,object_type,object_name,script_hash,state,original_rows,applied_at)
 SELECT 'BASE_REQUIREMENTS','BASELINE','REQUIREMENTS','baseline','APPLIED',COUNT(*),SYSTIMESTAMP FROM AI_POD_STAFFING.REQUIREMENTS; COMMIT;
 END IF;
 SELECT COUNT(*) INTO n FROM AIPS_P2_MIGRATION WHERE step_key='BASE_RECOMMENDATIONS';
 IF n=0 THEN
 INSERT INTO AIPS_P2_MIGRATION(step_key,object_type,object_name,script_hash,state,original_rows,applied_at)
 SELECT 'BASE_RECOMMENDATIONS','BASELINE','RECOMMENDATIONS','baseline','APPLIED',COUNT(*),SYSTIMESTAMP FROM AI_POD_STAFFING.RECOMMENDATIONS; COMMIT;
 END IF;
 SELECT COUNT(*) INTO n FROM AIPS_P2_MIGRATION WHERE step_key='BASE_APP_ROLES';
 IF n=0 THEN
 INSERT INTO AIPS_P2_MIGRATION(step_key,object_type,object_name,script_hash,state,original_rows,applied_at)
 SELECT 'BASE_APP_ROLES','BASELINE','APP_ROLES','baseline','APPLIED',COUNT(*),SYSTIMESTAMP FROM AI_POD_STAFFING.APP_ROLES; COMMIT;
 END IF;
 SELECT COUNT(*) INTO n FROM AIPS_P2_MIGRATION WHERE step_key='BASE_ROLE_PERMISSIONS';
 IF n=0 THEN
 INSERT INTO AIPS_P2_MIGRATION(step_key,object_type,object_name,script_hash,state,original_rows,applied_at)
 SELECT 'BASE_ROLE_PERMISSIONS','BASELINE','ROLE_PERMISSIONS','baseline','APPLIED',COUNT(*),SYSTIMESTAMP FROM AI_POD_STAFFING.ROLE_PERMISSIONS; COMMIT;
 END IF;
 SELECT COUNT(*) INTO n FROM AIPS_P2_MIGRATION WHERE step_key='BASE_APP_USER_ROLES';
 IF n=0 THEN
 INSERT INTO AIPS_P2_MIGRATION(step_key,object_type,object_name,script_hash,state,original_rows,applied_at)
 SELECT 'BASE_APP_USER_ROLES','BASELINE','APP_USER_ROLES','baseline','APPLIED',COUNT(*),SYSTIMESTAMP FROM AI_POD_STAFFING.APP_USER_ROLES; COMMIT;
 END IF;

 apply_step('ALTER_PEOPLE','TABLE','PEOPLE',q'~ALTER TABLE AI_POD_STAFFING.PEOPLE ADD (
 weekly_work_hours NUMBER(5,2) CONSTRAINT p2_people_hours CHECK (weekly_work_hours > 0 AND weekly_work_hours <= 80),
 workload_version NUMBER(10) DEFAULT 0 NOT NULL CONSTRAINT p2_people_workver CHECK (workload_version >= 0),
 staffing_seed_batch VARCHAR2(60),
 availability_version NUMBER(10) DEFAULT 0 NOT NULL CONSTRAINT p2_people_availver CHECK (availability_version >= 0))~',TRUE);

 apply_step('ALTER_REQUESTS','TABLE','REQUESTS',q'~ALTER TABLE AI_POD_STAFFING.REQUESTS ADD (
 request_revision NUMBER(10) DEFAULT 1 NOT NULL CONSTRAINT p2_request_revision CHECK (request_revision >= 1),
 responsible_captain_id VARCHAR2(30) CONSTRAINT p2_request_captain REFERENCES PEOPLE(person_id),
 agent_enabled CHAR(1) DEFAULT 'N' NOT NULL CONSTRAINT p2_request_enabled CHECK (agent_enabled IN ('Y','N')),
 staffing_seed_batch VARCHAR2(60))~',TRUE);

 apply_step('ALTER_REQUIREMENTS','TABLE','REQUIREMENTS',q'~ALTER TABLE AI_POD_STAFFING.REQUIREMENTS ADD (
 mandatory_flag CHAR(1) DEFAULT 'Y' NOT NULL CONSTRAINT p2_requirement_required CHECK (mandatory_flag IN ('Y','N')))~',TRUE);

 apply_step('ALTER_AVAILABILITY','TABLE','AVAILABILITY',q'~ALTER TABLE AI_POD_STAFFING.AVAILABILITY ADD (
 capacity_kind VARCHAR2(16) DEFAULT 'UNKNOWN' NOT NULL CONSTRAINT p2_avail_kind CHECK (capacity_kind IN ('UNKNOWN','NON_AVAILABILITY','EXTERNAL_WORK')))~',TRUE);

 apply_step('STAFFING_POLICIES','TABLE','STAFFING_POLICIES',q'~CREATE TABLE AI_POD_STAFFING.STAFFING_POLICIES (
policy_version VARCHAR2(60) NOT NULL,
status VARCHAR2(12) DEFAULT 'DRAFT' NOT NULL,
description VARCHAR2(1000) NOT NULL,
created_by VARCHAR2(255) NOT NULL,
created_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
approved_by VARCHAR2(255),
approved_at TIMESTAMP WITH TIME ZONE,
CONSTRAINT p2_policy_pk PRIMARY KEY (policy_version),
CONSTRAINT p2_policy_ref UNIQUE (policy_version,status),
CONSTRAINT p2_policy_status CHECK (status IN ('DRAFT','APPROVED')),
CONSTRAINT p2_policy_approval CHECK ((status = 'DRAFT' AND approved_by IS NULL AND approved_at IS NULL) OR
(status = 'APPROVED' AND approved_by IS NOT NULL AND TRIM(approved_by) IS NOT NULL AND approved_at IS NOT NULL))
)~',FALSE);

 apply_step('ELIGIBILITY_RULES','TABLE','ELIGIBILITY_RULES',q'~CREATE TABLE AI_POD_STAFFING.ELIGIBILITY_RULES (
policy_version VARCHAR2(60) NOT NULL,
rule_code VARCHAR2(40) NOT NULL,
rule_value_json CLOB NOT NULL,
CONSTRAINT p2_rule_pk PRIMARY KEY (policy_version, rule_code),
CONSTRAINT p2_rule_policy FOREIGN KEY (policy_version) REFERENCES STAFFING_POLICIES(policy_version),
CONSTRAINT p2_rule_json CHECK (rule_value_json IS JSON STRICT WITH UNIQUE KEYS),
CONSTRAINT p2_rule_code CHECK (rule_code IN ('MINIMUM_STRENGTH','LEAD_ROLE','MEMBER_ROLES','MAX_AGENT_STEPS'))
)~',FALSE);

 apply_step('LOAD_GUARDRAILS','TABLE','LOAD_GUARDRAILS',q'~CREATE TABLE AI_POD_STAFFING.LOAD_GUARDRAILS (
policy_version VARCHAR2(60) NOT NULL,
default_weekly_hours NUMBER(5,2) DEFAULT 40 NOT NULL,
maximum_allocation_pct NUMBER(5,2) DEFAULT 100 NOT NULL,
scheduling_timezone VARCHAR2(80) DEFAULT 'Asia/Kolkata' NOT NULL,
CONSTRAINT p2_load_pk PRIMARY KEY (policy_version),
CONSTRAINT p2_load_policy FOREIGN KEY (policy_version) REFERENCES STAFFING_POLICIES(policy_version),
CONSTRAINT p2_load_hours CHECK (default_weekly_hours > 0 AND default_weekly_hours <= 80),
CONSTRAINT p2_load_pct CHECK (maximum_allocation_pct > 0 AND maximum_allocation_pct <= 100)
)~',FALSE);

 apply_step('SCORING_WEIGHTS','TABLE','SCORING_WEIGHTS',q'~CREATE TABLE AI_POD_STAFFING.SCORING_WEIGHTS (
policy_version VARCHAR2(60) NOT NULL,
skill_weight NUMBER(3) NOT NULL,
deliverable_weight NUMBER(3) NOT NULL,
capacity_weight NUMBER(3) NOT NULL,
interest_weight NUMBER(3) NOT NULL,
CONSTRAINT p2_weight_pk PRIMARY KEY (policy_version),
CONSTRAINT p2_weight_policy FOREIGN KEY (policy_version) REFERENCES STAFFING_POLICIES(policy_version),
CONSTRAINT p2_weight_total CHECK (skill_weight + deliverable_weight + capacity_weight + interest_weight = 100
AND skill_weight BETWEEN 0 AND 100 AND deliverable_weight BETWEEN 0 AND 100
AND capacity_weight BETWEEN 0 AND 100 AND interest_weight BETWEEN 0 AND 100)
)~',FALSE);

 apply_step('AGENT_EXECUTIONS','TABLE','AGENT_EXECUTIONS',q'~CREATE TABLE AI_POD_STAFFING.AGENT_EXECUTIONS (
execution_id VARCHAR2(64) NOT NULL,
request_id VARCHAR2(30) NOT NULL,
request_revision NUMBER(10) NOT NULL,
policy_version VARCHAR2(60) NOT NULL,
idempotency_key VARCHAR2(150) NOT NULL,
status VARCHAR2(24) DEFAULT 'QUEUED' NOT NULL,
attempt_count NUMBER(3) DEFAULT 0 NOT NULL,
max_attempts NUMBER(3) DEFAULT 3 NOT NULL,
available_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
lease_owner VARCHAR2(100),
lease_token VARCHAR2(64),
lease_expires_at TIMESTAMP WITH TIME ZONE,
heartbeat_at TIMESTAMP WITH TIME ZONE,
request_snapshot_json CLOB NOT NULL,
evidence_snapshot_json CLOB,
checkpoint_json CLOB,
checkpoint_version NUMBER(10) DEFAULT 0 NOT NULL,
model_id VARCHAR2(400),
prompt_version VARCHAR2(60),
last_error_code VARCHAR2(80),
last_error_summary VARCHAR2(1000),
created_by VARCHAR2(255) NOT NULL,
created_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
finished_at TIMESTAMP WITH TIME ZONE,
CONSTRAINT p2_execution_pk PRIMARY KEY (execution_id),
CONSTRAINT p2_execution_req FOREIGN KEY (request_id) REFERENCES REQUESTS(request_id),
CONSTRAINT p2_execution_policy FOREIGN KEY (policy_version) REFERENCES STAFFING_POLICIES(policy_version),
CONSTRAINT p2_execution_idem UNIQUE (idempotency_key),
CONSTRAINT p2_execution_ref UNIQUE (execution_id, request_id, request_revision, policy_version),
CONSTRAINT p2_execution_rev CHECK (request_revision >= 1 AND checkpoint_version >= 0),
CONSTRAINT p2_execution_attempt CHECK (max_attempts BETWEEN 1 AND 10 AND attempt_count BETWEEN 0 AND max_attempts),
CONSTRAINT p2_execution_status CHECK (status IN ('QUEUED','RUNNING','NEEDS_INFORMATION','READY_FOR_REVIEW',
'NO_FEASIBLE_POD','FAILED','SUPERSEDED','CANCELLED')),
CONSTRAINT p2_execution_lease CHECK ((status = 'RUNNING' AND lease_owner IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)
OR (status <> 'RUNNING' AND lease_owner IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL)),
CONSTRAINT p2_exec_req_json CHECK (request_snapshot_json IS JSON STRICT WITH UNIQUE KEYS),
CONSTRAINT p2_exec_evid_json CHECK (evidence_snapshot_json IS JSON STRICT WITH UNIQUE KEYS),
CONSTRAINT p2_exec_check_json CHECK (checkpoint_json IS JSON STRICT WITH UNIQUE KEYS)
)~',FALSE);

 apply_step('AGENT_EXECUTION_EVENTS','TABLE','AGENT_EXECUTION_EVENTS',q'~CREATE TABLE AI_POD_STAFFING.AGENT_EXECUTION_EVENTS (
execution_id VARCHAR2(64) NOT NULL,
event_sequence NUMBER(10) NOT NULL,
stage VARCHAR2(60) NOT NULL,
status VARCHAR2(30) NOT NULL,
summary VARCHAR2(2000) NOT NULL,
details_json CLOB,
created_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
CONSTRAINT p2_event_pk PRIMARY KEY (execution_id, event_sequence),
CONSTRAINT p2_event_execution FOREIGN KEY (execution_id) REFERENCES AGENT_EXECUTIONS(execution_id),
CONSTRAINT p2_event_sequence CHECK (event_sequence > 0),
CONSTRAINT p2_event_json CHECK (details_json IS JSON STRICT WITH UNIQUE KEYS)
)~',FALSE);

 apply_step('POD_PROPOSALS','TABLE','POD_PROPOSALS',q'~CREATE TABLE AI_POD_STAFFING.POD_PROPOSALS (
proposal_id VARCHAR2(30) NOT NULL,
request_id VARCHAR2(30) NOT NULL,
proposal_version NUMBER(10) NOT NULL,
request_revision NUMBER(10) NOT NULL,
execution_id VARCHAR2(64) NOT NULL,
policy_version VARCHAR2(60) NOT NULL,
responsible_captain_id VARCHAR2(30) NOT NULL,
status VARCHAR2(20) DEFAULT 'BUILDING' NOT NULL,
starts_on DATE NOT NULL,
ends_on DATE NOT NULL,
total_hours NUMBER(10,2) NOT NULL,
lead_count NUMBER(2) NOT NULL,
member_count NUMBER(2) NOT NULL,
rationale CLOB NOT NULL,
evidence_refs_json CLOB NOT NULL,
validation_json CLOB NOT NULL,
created_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
CONSTRAINT p2_proposal_pk PRIMARY KEY (proposal_id),
CONSTRAINT p2_proposal_policy_ref UNIQUE (proposal_id,policy_version),
CONSTRAINT p2_proposal_version UNIQUE (request_id, proposal_version),
CONSTRAINT p2_proposal_captain UNIQUE (proposal_id, request_id, responsible_captain_id),
CONSTRAINT p2_proposal_exec FOREIGN KEY (execution_id, request_id, request_revision, policy_version)
REFERENCES AGENT_EXECUTIONS(execution_id, request_id, request_revision, policy_version),
CONSTRAINT p2_proposal_person FOREIGN KEY (responsible_captain_id) REFERENCES PEOPLE(person_id),
CONSTRAINT p2_proposal_status CHECK (status IN ('BUILDING','READY_FOR_REVIEW','APPROVED','REJECTED','SUPERSEDED')),
CONSTRAINT p2_proposal_numbers CHECK (proposal_version > 0 AND request_revision > 0 AND total_hours > 0 AND total_hours <= 100000
AND lead_count BETWEEN 1 AND 5 AND member_count BETWEEN 0 AND 20),
CONSTRAINT p2_proposal_dates CHECK (starts_on = TRUNC(starts_on) AND ends_on = TRUNC(ends_on)
AND ends_on >= starts_on AND ends_on - starts_on <= 366),
CONSTRAINT p2_proposal_refs CHECK (evidence_refs_json IS JSON STRICT WITH UNIQUE KEYS),
CONSTRAINT p2_proposal_validation CHECK (validation_json IS JSON STRICT WITH UNIQUE KEYS)
)~',FALSE);

 apply_step('POD_PROPOSAL_MEMBERS','TABLE','POD_PROPOSAL_MEMBERS',q'~CREATE TABLE AI_POD_STAFFING.POD_PROPOSAL_MEMBERS (
proposal_id VARCHAR2(30) NOT NULL,
person_id VARCHAR2(30) NOT NULL,
role_in_pod VARCHAR2(12) NOT NULL,
selected_flag CHAR(1) DEFAULT 'N' NOT NULL,
planned_hours NUMBER(10,2),
score NUMBER(5,2) NOT NULL,
rank_position NUMBER(5) NOT NULL,
responsibilities VARCHAR2(2000) NOT NULL,
deliverable_ids_json CLOB NOT NULL,
evidence_json CLOB NOT NULL,
factors_json CLOB NOT NULL,
person_skills_version NUMBER(10) NOT NULL,
person_workload_version NUMBER(10) NOT NULL,
CONSTRAINT p2_member_pk PRIMARY KEY (proposal_id, person_id),
CONSTRAINT p2_member_proposal FOREIGN KEY (proposal_id) REFERENCES POD_PROPOSALS(proposal_id),
CONSTRAINT p2_member_person FOREIGN KEY (person_id) REFERENCES PEOPLE(person_id),
CONSTRAINT p2_member_selected UNIQUE (proposal_id, person_id, role_in_pod, selected_flag),
CONSTRAINT p2_member_role CHECK (role_in_pod IN ('POD_LEAD','POD_MEMBER')),
CONSTRAINT p2_member_hours CHECK ((selected_flag = 'Y' AND planned_hours IS NOT NULL AND planned_hours > 0 AND planned_hours <= 100000)
OR (selected_flag = 'N' AND planned_hours IS NULL)),
CONSTRAINT p2_member_score CHECK (score BETWEEN 0 AND 100 AND rank_position > 0 AND person_skills_version >= 0 AND person_workload_version >= 0),
CONSTRAINT p2_member_del_json CHECK (deliverable_ids_json IS JSON STRICT WITH UNIQUE KEYS),
CONSTRAINT p2_member_evid_json CHECK (evidence_json IS JSON STRICT WITH UNIQUE KEYS),
CONSTRAINT p2_member_factor_json CHECK (factors_json IS JSON STRICT WITH UNIQUE KEYS)
)~',FALSE);

 apply_step('APPROVAL_DECISIONS','TABLE','APPROVAL_DECISIONS',q'~CREATE TABLE AI_POD_STAFFING.APPROVAL_DECISIONS (
decision_id VARCHAR2(30) NOT NULL,
proposal_id VARCHAR2(30) NOT NULL,
request_id VARCHAR2(30) NOT NULL,
captain_person_id VARCHAR2(30) NOT NULL,
actor_subject VARCHAR2(255) NOT NULL,
action_type VARCHAR2(8) NOT NULL,
reason VARCHAR2(2000),
idempotency_key VARCHAR2(150) NOT NULL,
decided_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
CONSTRAINT p2_decision_pk PRIMARY KEY (decision_id),
CONSTRAINT p2_decision_once UNIQUE (proposal_id),
CONSTRAINT p2_decision_idem UNIQUE (idempotency_key),
CONSTRAINT p2_decision_approved UNIQUE (decision_id, proposal_id, request_id, action_type),
CONSTRAINT p2_decision_proposal FOREIGN KEY (proposal_id, request_id, captain_person_id)
REFERENCES POD_PROPOSALS(proposal_id, request_id, responsible_captain_id),
CONSTRAINT p2_decision_action CHECK (action_type IN ('APPROVED','REJECTED')),
CONSTRAINT p2_decision_reason CHECK (action_type <> 'REJECTED' OR
(reason IS NOT NULL AND REGEXP_LIKE(reason, '[^[:space:]]')))
)~',FALSE);

 apply_step('POD_ASSIGNMENTS','TABLE','POD_ASSIGNMENTS',q'~CREATE TABLE AI_POD_STAFFING.POD_ASSIGNMENTS (
assignment_id VARCHAR2(30) NOT NULL,
request_id VARCHAR2(30) NOT NULL,
proposal_id VARCHAR2(30) NOT NULL,
person_id VARCHAR2(30) NOT NULL,
role_in_pod VARCHAR2(12) NOT NULL,
selected_flag CHAR(1) DEFAULT 'Y' NOT NULL,
decision_id VARCHAR2(30) NOT NULL,
approval_action VARCHAR2(8) DEFAULT 'APPROVED' NOT NULL,
policy_version VARCHAR2(60) NOT NULL,
policy_status VARCHAR2(8) DEFAULT 'APPROVED' NOT NULL,
starts_on DATE NOT NULL,
ends_on DATE NOT NULL,
assigned_hours NUMBER(10,2) NOT NULL,
status VARCHAR2(12) DEFAULT 'CONFIRMED' NOT NULL,
closed_at TIMESTAMP WITH TIME ZONE,
close_reason VARCHAR2(2000),
created_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
CONSTRAINT p2_assignment_pk PRIMARY KEY (assignment_id),
CONSTRAINT p2_assignment_once UNIQUE (proposal_id, person_id),
CONSTRAINT p2_assignment_person UNIQUE (assignment_id, person_id),
CONSTRAINT p2_assignment_member FOREIGN KEY (proposal_id, person_id, role_in_pod, selected_flag)
REFERENCES POD_PROPOSAL_MEMBERS(proposal_id, person_id, role_in_pod, selected_flag),
CONSTRAINT p2_assignment_decision FOREIGN KEY (decision_id, proposal_id, request_id, approval_action)
REFERENCES APPROVAL_DECISIONS(decision_id, proposal_id, request_id, action_type),
CONSTRAINT p2_assignment_policy FOREIGN KEY (policy_version,policy_status) REFERENCES STAFFING_POLICIES(policy_version,status),
CONSTRAINT p2_assignment_prop_policy FOREIGN KEY (proposal_id,policy_version) REFERENCES POD_PROPOSALS(proposal_id,policy_version),
CONSTRAINT p2_assignment_final CHECK (approval_action = 'APPROVED' AND selected_flag = 'Y' AND policy_status = 'APPROVED'),
CONSTRAINT p2_assignment_hours CHECK (assigned_hours > 0 AND assigned_hours <= 100000),
CONSTRAINT p2_assignment_dates CHECK (starts_on = TRUNC(starts_on) AND ends_on = TRUNC(ends_on)
AND ends_on >= starts_on AND ends_on - starts_on <= 366),
CONSTRAINT p2_assignment_status CHECK ((status = 'CONFIRMED' AND closed_at IS NULL)
OR (status IN ('CLOSED','CANCELLED') AND closed_at IS NOT NULL AND TRIM(close_reason) IS NOT NULL))
)~',FALSE);

 apply_step('ASSIGNMENT_DAYS','TABLE','ASSIGNMENT_DAYS',q'~CREATE TABLE AI_POD_STAFFING.ASSIGNMENT_DAYS (
assignment_id VARCHAR2(30) NOT NULL,
person_id VARCHAR2(30) NOT NULL,
work_date DATE NOT NULL,
assigned_hours NUMBER(5,2) NOT NULL,
CONSTRAINT p2_assign_day_pk PRIMARY KEY (assignment_id, work_date),
CONSTRAINT p2_assign_day_parent FOREIGN KEY (assignment_id, person_id) REFERENCES POD_ASSIGNMENTS(assignment_id, person_id),
CONSTRAINT p2_assign_day_hours CHECK (assigned_hours > 0 AND assigned_hours <= 24),
CONSTRAINT p2_assign_day_date CHECK (work_date = TRUNC(work_date))
)~',FALSE);

 apply_step('PERSON_CAPACITY_DAYS','TABLE','PERSON_CAPACITY_DAYS',q'~CREATE TABLE AI_POD_STAFFING.PERSON_CAPACITY_DAYS (
availability_version NUMBER(10) NOT NULL,

person_id VARCHAR2(30) NOT NULL,
work_date DATE NOT NULL,
available_hours NUMBER(5,2) NOT NULL,
external_committed_hours NUMBER(5,2) DEFAULT 0 NOT NULL,
input_refs_json CLOB NOT NULL,
source_version VARCHAR2(60) NOT NULL,
verified_at TIMESTAMP WITH TIME ZONE NOT NULL,
verified_by VARCHAR2(255) NOT NULL,
CONSTRAINT p2_capacity_pk PRIMARY KEY (person_id, work_date),
CONSTRAINT p2_capacity_person FOREIGN KEY (person_id) REFERENCES PEOPLE(person_id),
CONSTRAINT p2_capacity_date CHECK (work_date = TRUNC(work_date)),
CONSTRAINT p2_capacity_hours CHECK (available_hours BETWEEN 0 AND 16 AND external_committed_hours BETWEEN 0 AND 24),
CONSTRAINT p2_capacity_refs CHECK (input_refs_json IS JSON STRICT WITH UNIQUE KEYS),
CONSTRAINT p2_capacity_version CHECK (availability_version >= 0)
)~',FALSE);

 apply_step('AUDIT_EVENTS','TABLE','AUDIT_EVENTS',q'~CREATE TABLE AI_POD_STAFFING.AUDIT_EVENTS (
audit_event_id VARCHAR2(64) NOT NULL,
entity_type VARCHAR2(60) NOT NULL,
entity_id VARCHAR2(100) NOT NULL,
action_type VARCHAR2(60) NOT NULL,
actor_subject VARCHAR2(255) NOT NULL,
correlation_id VARCHAR2(100) NOT NULL,
before_state_json CLOB,
after_state_json CLOB,
reason VARCHAR2(2000),
performed_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
CONSTRAINT p2_audit_pk PRIMARY KEY (audit_event_id),
CONSTRAINT p2_audit_before CHECK (before_state_json IS JSON STRICT WITH UNIQUE KEYS),
CONSTRAINT p2_audit_after CHECK (after_state_json IS JSON STRICT WITH UNIQUE KEYS)
)~',FALSE);

 apply_step('NOTIFICATION_OUTBOX','TABLE','NOTIFICATION_OUTBOX',q'~CREATE TABLE AI_POD_STAFFING.NOTIFICATION_OUTBOX (
notification_id VARCHAR2(64) NOT NULL,
decision_id VARCHAR2(30) NOT NULL,
proposal_id VARCHAR2(30) NOT NULL,
request_id VARCHAR2(30) NOT NULL,
approval_action VARCHAR2(8) DEFAULT 'APPROVED' NOT NULL,
recipient_person_id VARCHAR2(30) NOT NULL,
recipient_email VARCHAR2(320),
template_code VARCHAR2(60) DEFAULT 'POD_ASSIGNED' NOT NULL,
deduplication_key VARCHAR2(180) NOT NULL,
payload_json CLOB NOT NULL,
status VARCHAR2(12) DEFAULT 'DISABLED' NOT NULL,
attempt_count NUMBER(3) DEFAULT 0 NOT NULL,
available_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
sent_at TIMESTAMP WITH TIME ZONE,
provider_message_id VARCHAR2(200),
last_error_code VARCHAR2(80),
created_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
CONSTRAINT p2_outbox_pk PRIMARY KEY (notification_id),
CONSTRAINT p2_outbox_idem UNIQUE (deduplication_key),
CONSTRAINT p2_outbox_decision FOREIGN KEY (decision_id, proposal_id, request_id, approval_action)
REFERENCES APPROVAL_DECISIONS(decision_id, proposal_id, request_id, action_type),
CONSTRAINT p2_outbox_person FOREIGN KEY (recipient_person_id) REFERENCES PEOPLE(person_id),
CONSTRAINT p2_outbox_approved CHECK (approval_action = 'APPROVED'),
CONSTRAINT p2_outbox_status CHECK (status IN ('DISABLED','PENDING','SENDING','SENT','FAILED','CANCELLED')),
CONSTRAINT p2_outbox_sent CHECK (status <> 'SENT' OR (sent_at IS NOT NULL AND provider_message_id IS NOT NULL)),
CONSTRAINT p2_outbox_attempts CHECK (attempt_count BETWEEN 0 AND 10),
CONSTRAINT p2_outbox_json CHECK (payload_json IS JSON STRICT WITH UNIQUE KEYS)
)~',FALSE);

 apply_step('STAFFING_RUNTIME','TABLE','STAFFING_RUNTIME',q'~CREATE TABLE AI_POD_STAFFING.STAFFING_RUNTIME (
runtime_id NUMBER(1) DEFAULT 1 NOT NULL,
agents_enabled CHAR(1) DEFAULT 'N' NOT NULL,
notifications_enabled CHAR(1) DEFAULT 'N' NOT NULL,
updated_by VARCHAR2(255) NOT NULL,
updated_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
CONSTRAINT p2_runtime_pk PRIMARY KEY (runtime_id),
CONSTRAINT p2_runtime_single CHECK (runtime_id = 1),
CONSTRAINT p2_runtime_flags CHECK (agents_enabled IN ('Y','N') AND notifications_enabled IN ('Y','N'))
)~',FALSE);

 apply_step('P2_EXEC_QUEUE','INDEX','P2_EXEC_QUEUE',q'~CREATE INDEX AI_POD_STAFFING.P2_EXEC_QUEUE ON AI_POD_STAFFING.AGENT_EXECUTIONS(status, available_at, lease_expires_at)~',FALSE);

 apply_step('P2_EXEC_REQUEST','INDEX','P2_EXEC_REQUEST',q'~CREATE INDEX AI_POD_STAFFING.P2_EXEC_REQUEST ON AI_POD_STAFFING.AGENT_EXECUTIONS(request_id, request_revision)~',FALSE);

 apply_step('P2_EXEC_ACTIVE','INDEX','P2_EXEC_ACTIVE',q'~CREATE UNIQUE INDEX AI_POD_STAFFING.P2_EXEC_ACTIVE ON AI_POD_STAFFING.AGENT_EXECUTIONS(CASE WHEN status IN ('QUEUED','RUNNING') THEN request_id END, CASE WHEN status IN ('QUEUED','RUNNING') THEN request_revision END)~',FALSE);

 apply_step('P2_PROP_REVIEW','INDEX','P2_PROP_REVIEW',q'~CREATE UNIQUE INDEX AI_POD_STAFFING.P2_PROP_REVIEW ON AI_POD_STAFFING.POD_PROPOSALS(CASE WHEN status = 'READY_FOR_REVIEW' THEN request_id END)~',FALSE);

 apply_step('P2_ASSIGN_ACTIVE','INDEX','P2_ASSIGN_ACTIVE',q'~CREATE UNIQUE INDEX AI_POD_STAFFING.P2_ASSIGN_ACTIVE ON AI_POD_STAFFING.POD_ASSIGNMENTS(CASE WHEN status = 'CONFIRMED' THEN request_id END, CASE WHEN status = 'CONFIRMED' THEN person_id END)~',FALSE);

 apply_step('P2_ASSIGN_PERSON','INDEX','P2_ASSIGN_PERSON',q'~CREATE INDEX AI_POD_STAFFING.P2_ASSIGN_PERSON ON AI_POD_STAFFING.POD_ASSIGNMENTS(person_id, status, starts_on, ends_on)~',FALSE);

 apply_step('P2_ASSIGN_DATES','INDEX','P2_ASSIGN_DATES',q'~CREATE INDEX AI_POD_STAFFING.P2_ASSIGN_DATES ON AI_POD_STAFFING.ASSIGNMENT_DAYS(person_id, work_date)~',FALSE);

 apply_step('P2_OUTBOX_PENDING','INDEX','P2_OUTBOX_PENDING',q'~CREATE INDEX AI_POD_STAFFING.P2_OUTBOX_PENDING ON AI_POD_STAFFING.NOTIFICATION_OUTBOX(status, available_at)~',FALSE);

 apply_step('P2_AUDIT_ENTITY','INDEX','P2_AUDIT_ENTITY',q'~CREATE INDEX AI_POD_STAFFING.P2_AUDIT_ENTITY ON AI_POD_STAFFING.AUDIT_EVENTS(entity_type, entity_id, performed_at)~',FALSE);

 apply_step('P2_CAPTAIN_REQUEST','INDEX','P2_CAPTAIN_REQUEST',q'~CREATE INDEX AI_POD_STAFFING.P2_CAPTAIN_REQUEST ON AI_POD_STAFFING.REQUESTS(responsible_captain_id)~',FALSE);

 apply_step('P2_AUDIT_APPEND','TRIGGER','P2_AUDIT_APPEND',q'~CREATE TRIGGER AI_POD_STAFFING.P2_AUDIT_APPEND
BEFORE UPDATE OR DELETE ON AI_POD_STAFFING.AUDIT_EVENTS
BEGIN
  RAISE_APPLICATION_ERROR(-20140, 'AUDIT_EVENTS is append-only; preserve history.');
END;~',FALSE);

 apply_step('P2_DECISION_APPEND','TRIGGER','P2_DECISION_APPEND',q'~CREATE TRIGGER AI_POD_STAFFING.P2_DECISION_APPEND
BEFORE UPDATE OR DELETE ON AI_POD_STAFFING.APPROVAL_DECISIONS
BEGIN
  RAISE_APPLICATION_ERROR(-20140, 'APPROVAL_DECISIONS is append-only; preserve history.');
END;~',FALSE);

 apply_step('P2_EVENT_APPEND','TRIGGER','P2_EVENT_APPEND',q'~CREATE TRIGGER AI_POD_STAFFING.P2_EVENT_APPEND
BEFORE UPDATE OR DELETE ON AI_POD_STAFFING.AGENT_EXECUTION_EVENTS
BEGIN
  RAISE_APPLICATION_ERROR(-20140, 'AGENT_EXECUTION_EVENTS is append-only; preserve history.');
END;~',FALSE);

 apply_step('P2_RULE_FREEZE','TRIGGER','P2_RULE_FREEZE',q'~CREATE TRIGGER AI_POD_STAFFING.P2_RULE_FREEZE
BEFORE INSERT OR UPDATE OR DELETE ON AI_POD_STAFFING.ELIGIBILITY_RULES FOR EACH ROW
DECLARE v_status VARCHAR2(12);
BEGIN
  IF UPDATING AND :OLD.policy_version <> :NEW.policy_version THEN
    RAISE_APPLICATION_ERROR(-20141, 'Create a new policy version; do not move configuration rows.');
  END IF;
  SELECT status INTO v_status FROM AI_POD_STAFFING.STAFFING_POLICIES
    WHERE policy_version = COALESCE(:OLD.policy_version, :NEW.policy_version) FOR UPDATE;
  IF v_status = 'APPROVED' THEN RAISE_APPLICATION_ERROR(-20142, 'Approved policy configuration is frozen.'); END IF;
END;~',FALSE);

 apply_step('P2_LOAD_FREEZE','TRIGGER','P2_LOAD_FREEZE',q'~CREATE TRIGGER AI_POD_STAFFING.P2_LOAD_FREEZE
BEFORE INSERT OR UPDATE OR DELETE ON AI_POD_STAFFING.LOAD_GUARDRAILS FOR EACH ROW
DECLARE v_status VARCHAR2(12);
BEGIN
  IF UPDATING AND :OLD.policy_version <> :NEW.policy_version THEN
    RAISE_APPLICATION_ERROR(-20141, 'Create a new policy version; do not move configuration rows.');
  END IF;
  SELECT status INTO v_status FROM AI_POD_STAFFING.STAFFING_POLICIES
    WHERE policy_version = COALESCE(:OLD.policy_version, :NEW.policy_version) FOR UPDATE;
  IF v_status = 'APPROVED' THEN RAISE_APPLICATION_ERROR(-20142, 'Approved policy configuration is frozen.'); END IF;
END;~',FALSE);

 apply_step('P2_WEIGHT_FREEZE','TRIGGER','P2_WEIGHT_FREEZE',q'~CREATE TRIGGER AI_POD_STAFFING.P2_WEIGHT_FREEZE
BEFORE INSERT OR UPDATE OR DELETE ON AI_POD_STAFFING.SCORING_WEIGHTS FOR EACH ROW
DECLARE v_status VARCHAR2(12);
BEGIN
  IF UPDATING AND :OLD.policy_version <> :NEW.policy_version THEN
    RAISE_APPLICATION_ERROR(-20141, 'Create a new policy version; do not move configuration rows.');
  END IF;
  SELECT status INTO v_status FROM AI_POD_STAFFING.STAFFING_POLICIES
    WHERE policy_version = COALESCE(:OLD.policy_version, :NEW.policy_version) FOR UPDATE;
  IF v_status = 'APPROVED' THEN RAISE_APPLICATION_ERROR(-20142, 'Approved policy configuration is frozen.'); END IF;
END;~',FALSE);

 apply_step('P2_POLICY_FREEZE','TRIGGER','P2_POLICY_FREEZE',q'~CREATE TRIGGER AI_POD_STAFFING.P2_POLICY_FREEZE
BEFORE INSERT OR UPDATE OR DELETE ON AI_POD_STAFFING.STAFFING_POLICIES FOR EACH ROW
DECLARE n NUMBER;
BEGIN
  IF INSERTING AND :NEW.status <> 'DRAFT' THEN
    RAISE_APPLICATION_ERROR(-20143, 'Create and validate a draft before approving it.');
  END IF;
  IF UPDATING OR DELETING THEN
    IF :OLD.status = 'APPROVED' THEN RAISE_APPLICATION_ERROR(-20144, 'Approved policy is frozen; create a new version.'); END IF;
  END IF;
  IF UPDATING AND :NEW.status = 'APPROVED' THEN
    SELECT COUNT(*) INTO n FROM ELIGIBILITY_RULES WHERE policy_version = :OLD.policy_version;
    IF n <> 4 THEN RAISE_APPLICATION_ERROR(-20145, 'Policy requires all four rules.'); END IF;
    SELECT COUNT(*) INTO n FROM LOAD_GUARDRAILS WHERE policy_version = :OLD.policy_version;
    IF n <> 1 THEN RAISE_APPLICATION_ERROR(-20145, 'Policy load guardrail is missing.'); END IF;
    SELECT COUNT(*) INTO n FROM SCORING_WEIGHTS WHERE policy_version = :OLD.policy_version;
    IF n <> 1 THEN RAISE_APPLICATION_ERROR(-20145, 'Policy weights are missing.'); END IF;
  END IF;
END;~',FALSE);

 apply_step('P2_MEMBER_FREEZE','TRIGGER','P2_MEMBER_FREEZE',q'~CREATE TRIGGER AI_POD_STAFFING.P2_MEMBER_FREEZE
BEFORE INSERT OR UPDATE OR DELETE ON AI_POD_STAFFING.POD_PROPOSAL_MEMBERS FOR EACH ROW
DECLARE v_status VARCHAR2(20);
BEGIN
  IF UPDATING AND (:OLD.proposal_id <> :NEW.proposal_id OR :OLD.person_id <> :NEW.person_id) THEN
    RAISE_APPLICATION_ERROR(-20146, 'Proposal member keys are immutable.');
  END IF;
  SELECT status INTO v_status FROM AI_POD_STAFFING.POD_PROPOSALS
    WHERE proposal_id = COALESCE(:OLD.proposal_id, :NEW.proposal_id) FOR UPDATE;
  IF v_status <> 'BUILDING' THEN RAISE_APPLICATION_ERROR(-20147, 'Published candidates are frozen; create a new proposal version.'); END IF;
END;~',FALSE);

 apply_step('P2_REQUEST_REVISION','TRIGGER','P2_REQUEST_REVISION',q'~CREATE TRIGGER AI_POD_STAFFING.P2_REQUEST_REVISION
BEFORE UPDATE ON AI_POD_STAFFING.REQUESTS FOR EACH ROW
BEGIN
  :NEW.request_revision := :OLD.request_revision + 1;
END;~',FALSE);

 apply_step('P2_AVAIL_VERSION','TRIGGER','P2_AVAIL_VERSION',q'~CREATE TRIGGER AI_POD_STAFFING.P2_AVAIL_VERSION
AFTER INSERT OR UPDATE OR DELETE ON AI_POD_STAFFING.AVAILABILITY FOR EACH ROW
BEGIN
  -- Backend transactions must lock affected PEOPLE rows in sorted ID order.
  IF DELETING OR UPDATING THEN
    UPDATE AI_POD_STAFFING.PEOPLE SET workload_version = workload_version + 1, availability_version = availability_version + 1
      WHERE person_id = :OLD.person_id;
  END IF;
  IF INSERTING OR (UPDATING AND :OLD.person_id <> :NEW.person_id) THEN
    UPDATE AI_POD_STAFFING.PEOPLE SET workload_version = workload_version + 1, availability_version = availability_version + 1
      WHERE person_id = :NEW.person_id;
  END IF;
END;~',FALSE);

 apply_step('P2_CAPACITY_VERSION','TRIGGER','P2_CAPACITY_VERSION',q'~CREATE TRIGGER AI_POD_STAFFING.P2_CAPACITY_VERSION
AFTER INSERT OR UPDATE OR DELETE ON AI_POD_STAFFING.PERSON_CAPACITY_DAYS FOR EACH ROW
BEGIN
  -- Backend transactions must lock affected PEOPLE rows in sorted ID order.
  IF DELETING OR UPDATING THEN
    UPDATE AI_POD_STAFFING.PEOPLE SET workload_version = workload_version + 1
      WHERE person_id = :OLD.person_id;
  END IF;
  IF INSERTING OR (UPDATING AND :OLD.person_id <> :NEW.person_id) THEN
    UPDATE AI_POD_STAFFING.PEOPLE SET workload_version = workload_version + 1
      WHERE person_id = :NEW.person_id;
  END IF;
END;~',FALSE);

 apply_step('P2_DAY_VERSION','TRIGGER','P2_DAY_VERSION',q'~CREATE TRIGGER AI_POD_STAFFING.P2_DAY_VERSION
AFTER INSERT OR UPDATE OR DELETE ON AI_POD_STAFFING.ASSIGNMENT_DAYS FOR EACH ROW
BEGIN
  -- Backend transactions must lock affected PEOPLE rows in sorted ID order.
  IF DELETING OR UPDATING THEN
    UPDATE AI_POD_STAFFING.PEOPLE SET workload_version = workload_version + 1
      WHERE person_id = :OLD.person_id;
  END IF;
  IF INSERTING OR (UPDATING AND :OLD.person_id <> :NEW.person_id) THEN
    UPDATE AI_POD_STAFFING.PEOPLE SET workload_version = workload_version + 1
      WHERE person_id = :NEW.person_id;
  END IF;
END;~',FALSE);

 apply_step('P2_ASSIGN_VERSION','TRIGGER','P2_ASSIGN_VERSION',q'~CREATE TRIGGER AI_POD_STAFFING.P2_ASSIGN_VERSION
AFTER INSERT OR UPDATE OR DELETE ON AI_POD_STAFFING.POD_ASSIGNMENTS FOR EACH ROW
BEGIN
  -- Backend transactions must lock affected PEOPLE rows in sorted ID order.
  IF DELETING OR UPDATING THEN
    UPDATE AI_POD_STAFFING.PEOPLE SET workload_version = workload_version + 1
      WHERE person_id = :OLD.person_id;
  END IF;
  IF INSERTING OR (UPDATING AND :OLD.person_id <> :NEW.person_id) THEN
    UPDATE AI_POD_STAFFING.PEOPLE SET workload_version = workload_version + 1
      WHERE person_id = :NEW.person_id;
  END IF;
END;~',FALSE);

 apply_step('P2_PROPOSAL_FREEZE','TRIGGER','P2_PROPOSAL_FREEZE',q'~CREATE TRIGGER AI_POD_STAFFING.P2_PROPOSAL_FREEZE
BEFORE INSERT OR UPDATE OR DELETE ON AI_POD_STAFFING.POD_PROPOSALS FOR EACH ROW
DECLARE leads NUMBER; members NUMBER; hours NUMBER; n NUMBER;
BEGIN
  IF INSERTING AND :NEW.status <> 'BUILDING' THEN RAISE_APPLICATION_ERROR(-20155, 'Create a building proposal first.'); END IF;
  IF :OLD.status <> 'BUILDING' THEN
    IF DELETING THEN RAISE_APPLICATION_ERROR(-20148, 'Published proposal history cannot be deleted.'); END IF;
    IF :OLD.proposal_id <> :NEW.proposal_id OR :OLD.request_id <> :NEW.request_id
      OR :OLD.proposal_version <> :NEW.proposal_version OR :OLD.request_revision <> :NEW.request_revision
      OR :OLD.execution_id <> :NEW.execution_id OR :OLD.policy_version <> :NEW.policy_version
      OR :OLD.responsible_captain_id <> :NEW.responsible_captain_id
      OR :OLD.starts_on <> :NEW.starts_on OR :OLD.ends_on <> :NEW.ends_on
      OR :OLD.created_at <> :NEW.created_at OR :OLD.total_hours <> :NEW.total_hours OR :OLD.lead_count <> :NEW.lead_count OR :OLD.member_count <> :NEW.member_count
      OR DBMS_LOB.COMPARE(:OLD.rationale,:NEW.rationale) <> 0
      OR DBMS_LOB.COMPARE(:OLD.evidence_refs_json,:NEW.evidence_refs_json) <> 0
      OR DBMS_LOB.COMPARE(:OLD.validation_json,:NEW.validation_json) <> 0 THEN
      RAISE_APPLICATION_ERROR(-20149, 'Published proposal evidence is frozen.');
    END IF;
  END IF;
  IF UPDATING AND :OLD.status <> :NEW.status THEN
    IF NOT ((:OLD.status = 'BUILDING' AND :NEW.status IN ('READY_FOR_REVIEW','SUPERSEDED'))
      OR (:OLD.status = 'READY_FOR_REVIEW' AND :NEW.status IN ('APPROVED','REJECTED','SUPERSEDED'))) THEN
      RAISE_APPLICATION_ERROR(-20150, 'Invalid proposal state transition.');
    END IF;
    IF :NEW.status = 'READY_FOR_REVIEW' THEN
      SELECT NVL(SUM(CASE WHEN role_in_pod='POD_LEAD' THEN 1 ELSE 0 END),0),
        NVL(SUM(CASE WHEN role_in_pod='POD_MEMBER' THEN 1 ELSE 0 END),0), NVL(SUM(planned_hours),0)
        INTO leads,members,hours FROM POD_PROPOSAL_MEMBERS WHERE proposal_id=:OLD.proposal_id AND selected_flag='Y';
      IF leads <> :NEW.lead_count OR members <> :NEW.member_count OR hours <> :NEW.total_hours THEN
        RAISE_APPLICATION_ERROR(-20151, 'Proposal count or effort mismatch.');
      END IF;
    END IF;
    IF :NEW.status IN ('APPROVED','REJECTED') THEN
      SELECT COUNT(*) INTO n FROM APPROVAL_DECISIONS WHERE proposal_id=:OLD.proposal_id AND action_type=:NEW.status;
      IF n <> 1 THEN RAISE_APPLICATION_ERROR(-20152, 'Matching Captain decision required.'); END IF;
    END IF;
  END IF;
END;~',FALSE);

 apply_step('P2_DECISION_REVIEW','TRIGGER','P2_DECISION_REVIEW',q'~CREATE TRIGGER AI_POD_STAFFING.P2_DECISION_REVIEW
BEFORE INSERT ON AI_POD_STAFFING.APPROVAL_DECISIONS FOR EACH ROW
DECLARE s VARCHAR2(20); rev NUMBER; current_rev NUMBER; captain VARCHAR2(30);
BEGIN
  SELECT status, request_revision INTO s,rev FROM POD_PROPOSALS WHERE proposal_id=:NEW.proposal_id FOR UPDATE;
  SELECT request_revision, responsible_captain_id INTO current_rev,captain FROM REQUESTS WHERE request_id=:NEW.request_id;
  IF s <> 'READY_FOR_REVIEW' OR rev <> current_rev OR captain IS NULL OR captain <> :NEW.captain_person_id THEN
    RAISE_APPLICATION_ERROR(-20153, 'Proposal is stale, not in review or belongs to another Captain.');
  END IF;
END;~',FALSE);

 apply_step('P2_DAY_BOUNDS','TRIGGER','P2_DAY_BOUNDS',q'~CREATE TRIGGER AI_POD_STAFFING.P2_DAY_BOUNDS
BEFORE INSERT OR UPDATE ON AI_POD_STAFFING.ASSIGNMENT_DAYS FOR EACH ROW
DECLARE s DATE; e DATE;
BEGIN
  SELECT starts_on,ends_on INTO s,e FROM POD_ASSIGNMENTS WHERE assignment_id=:NEW.assignment_id;
  IF :NEW.work_date < s OR :NEW.work_date > e THEN
    RAISE_APPLICATION_ERROR(-20154, 'Assigned day falls outside assignment dates.');
  END IF;
END;~',FALSE);

EXCEPTION WHEN OTHERS THEN
 ROLLBACK;
 DBMS_OUTPUT.PUT_LINE('STOP: earlier DDL remains committed. Do not run setup.sql or drop tables.');
 DBMS_OUTPUT.PUT_LINE('Resolve the reported issue and rerun this script. See docs/backend-phase2.md.');
 RAISE;
END;
/

PROMPT Loading draft configuration only - no agents or email enabled
DECLARE n NUMBER;
BEGIN
 SELECT COUNT(*) INTO n FROM AIPS_P2_MIGRATION WHERE step_key='CONFIG_V1';
 IF n=0 THEN
   SELECT COUNT(*) INTO n FROM STAFFING_POLICIES WHERE policy_version='staffing-v1-draft';
   IF n<>0 THEN RAISE_APPLICATION_ERROR(-20102,'Unowned draft policy already exists. Stop.'); END IF;
   INSERT INTO STAFFING_POLICIES(policy_version,status,description,created_by)
     VALUES('staffing-v1-draft','DRAFT','Phase-1 staffing defaults awaiting business sign-off',USER);
   INSERT INTO ELIGIBILITY_RULES VALUES('staffing-v1-draft','MINIMUM_STRENGTH','{"value":3}');
   INSERT INTO ELIGIBILITY_RULES VALUES('staffing-v1-draft','LEAD_ROLE','{"value":"POD_LEAD"}');
   INSERT INTO ELIGIBILITY_RULES VALUES('staffing-v1-draft','MEMBER_ROLES','{"value":["POD_MEMBER","POD_LEAD"]}');
   INSERT INTO ELIGIBILITY_RULES VALUES('staffing-v1-draft','MAX_AGENT_STEPS','{"value":12}');
   INSERT INTO LOAD_GUARDRAILS(policy_version,default_weekly_hours,maximum_allocation_pct,scheduling_timezone)
     VALUES('staffing-v1-draft',40,100,'Asia/Kolkata');
   INSERT INTO SCORING_WEIGHTS VALUES('staffing-v1-draft',50,30,15,5);
   INSERT INTO STAFFING_RUNTIME(runtime_id,agents_enabled,notifications_enabled,updated_by) VALUES(1,'N','N',USER);
   INSERT INTO AIPS_P2_MIGRATION(step_key,object_type,object_name,script_hash,state,applied_at)
     VALUES('CONFIG_V1','CONFIG','STAFFING_POLICIES','config-v1','APPLIED',SYSTIMESTAMP);
   COMMIT;
 ELSE DBMS_OUTPUT.PUT_LINE('Configuration already installed; retaining current values.');
 END IF;
 DBMS_OUTPUT.PUT_LINE('SUCCESS: phase-2 schema installed. Run phase2_verify.sql next.');
 DBMS_OUTPUT.PUT_LINE('Existing data retained. Agent and email switches initially OFF. No test people loaded by this file.');
EXCEPTION WHEN OTHERS THEN ROLLBACK; RAISE;
END;
/
