-- OPTIONAL test fixtures. Run F5 AFTER phase2.sql and phase2_verify.sql.
-- Inserts new, explicitly tagged records only. Does not change existing people/requests/roles.
-- No assignments are fabricated; no policy is approved; no execution or email is triggered.
SET SERVEROUTPUT ON SIZE UNLIMITED
SET DEFINE OFF
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK
DECLARE
 n NUMBER; d_id VARCHAR2(30); d_name VARCHAR2(500); p_id VARCHAR2(30); p_name VARCHAR2(250);
 p_desc VARCHAR2(2000); src_version VARCHAR2(40); d_json CLOB; exp_json CLOB;
 start_day DATE:=TRUNC(SYSDATE,'IW')+7;
 person_id_value VARCHAR2(30); person_name VARCHAR2(250); role_value VARCHAR2(40);
 batch CONSTANT VARCHAR2(60):='AIPS_BACKEND_P2_SEED_V1';
 req_id VARCHAR2(30); req_title VARCHAR2(500); effort NUMBER;
 PROCEDURE demand(ok BOOLEAN,msg VARCHAR2) IS
 BEGIN IF ok IS NULL OR NOT ok THEN RAISE_APPLICATION_ERROR(-20170,msg); END IF; END;
BEGIN
 IF USER<>'AI_POD_STAFFING' OR SYS_CONTEXT('USERENV','SESSION_USER')<>'AI_POD_STAFFING'
 OR SYS_CONTEXT('USERENV','CURRENT_SCHEMA')<>'AI_POD_STAFFING' THEN
 RAISE_APPLICATION_ERROR(-20100,'Use AI_POD_STAFFING only.'); END IF;
 EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL DML';
 EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL QUERY';
 EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL DDL';
 SELECT COUNT(*) INTO n FROM STAFFING_RUNTIME WHERE runtime_id=1 AND agents_enabled='N' AND notifications_enabled='N';
 demand(n=1,'Stop the application and disable agent/email switches before seeding.');
 SELECT COUNT(*) INTO n FROM AIPS_P2_MIGRATION WHERE step_key='CONFIG_V1' AND state='APPLIED';
 demand(n=1,'Complete phase2.sql first.');
 SELECT COUNT(*) INTO n FROM AIPS_P2_MIGRATION WHERE step_key='SEED_V1';
 IF n<>0 THEN
   SELECT COUNT(*) INTO n FROM PEOPLE WHERE staffing_seed_batch=batch;
   demand(n=5,'Seed marker exists but people set changed. Do not overwrite it.');
   SELECT COUNT(*) INTO n FROM REQUESTS WHERE staffing_seed_batch=batch;
   demand(n=3,'Seed marker exists but request set changed. Do not overwrite it.');
   DBMS_OUTPUT.PUT_LINE('Seed already loaded; preserving current test records.'); RETURN;
 END IF;
 SELECT COUNT(*) INTO n FROM PEOPLE WHERE person_id IN ('P-900101','P-900102','P-900103','P-900104','P-900105')
 OR staffing_seed_batch=batch;
 demand(n=0,'Reserved seed people IDs already exist. Nothing overwritten.');
 SELECT COUNT(*) INTO n FROM REQUESTS WHERE request_id IN ('REQ-900101','REQ-900102','REQ-900103') OR staffing_seed_batch=batch;
 demand(n=0,'Reserved seed request IDs already exist. Nothing overwritten.');
 SELECT COUNT(*) INTO n FROM APP_USER_ROLES WHERE identity_subject LIKE 'seed:backend-p2:%';
 demand(n=0,'Reserved seed identity mappings already exist.');
 -- Use the real active catalogue, without guessing IDs or granting Project Manager by name.
 SELECT d.deliverable_id,d.deliverable_name,p.project_type_id,p.project_name,p.project_description,d.source_version
 INTO d_id,d_name,p_id,p_name,p_desc,src_version
 FROM DELIVERABLES d JOIN PROJECT_TYPES p ON p.project_type_id=d.project_type_id
 WHERE d.active_flag='Y'
 AND EXISTS (SELECT 1 FROM DELIVERABLE_SKILLS ds WHERE ds.deliverable_id=d.deliverable_id)
 AND NOT EXISTS (SELECT 1 FROM DELIVERABLE_SKILLS ds JOIN INTERESTS i ON i.interest_id=ds.skill_id
 WHERE ds.deliverable_id=d.deliverable_id AND i.assessment_type='ROLE_DERIVED')
 ORDER BY d.deliverable_id FETCH FIRST 1 ROW ONLY;
 SELECT JSON_ARRAY(JSON_OBJECT('id' VALUE d_id,'name' VALUE d_name,'note' VALUE '',
   'custom' VALUE 'false' FORMAT JSON RETURNING CLOB) RETURNING CLOB) INTO d_json FROM dual;
 FOR i IN 1..5 LOOP
   person_id_value:='P-'||TO_CHAR(900100+i,'FM999999');
   person_name:=CASE i WHEN 1 THEN 'Amelia Hart' WHEN 2 THEN 'Mara Bennett' WHEN 3 THEN 'Carlos Reed'
     WHEN 4 THEN 'Ava Morgan' ELSE 'Noah Foster' END;
   role_value:=CASE i WHEN 1 THEN 'POD_CAPTAIN' WHEN 2 THEN 'POD_LEAD' ELSE 'POD_MEMBER' END;
   SELECT JSON_ARRAY(JSON_OBJECT('deliverableId' VALUE d_id,
     'experienceLevel' VALUE CASE WHEN i=2 THEN 'MENTOR' WHEN i=5 THEN 'SUPPORTED' ELSE 'INDEPENDENT' END,
     'contributionScope' VALUE CASE WHEN i=5 THEN 'CONTRIBUTOR' ELSE 'END_TO_END' END,
     'interested' VALUE 'true' FORMAT JSON,
     'experience' VALUE CASE WHEN i=2 THEN 'Coordinated end-to-end delivery and guided contributors.'
       WHEN i=5 THEN 'Supported content preparation with guidance from a delivery lead.'
       ELSE 'Prepared and delivered customer-facing materials independently.' END
     RETURNING CLOB) RETURNING CLOB) INTO exp_json FROM dual;
   INSERT INTO PEOPLE(person_id,full_name,initials,job_title,location,allocation_pct,active_pods,
     email_address,active_flag,skills_version,deliverable_experience_json,weekly_work_hours,staffing_seed_batch)
   VALUES(person_id_value,person_name,
     CASE i WHEN 1 THEN 'AH' WHEN 2 THEN 'MB' WHEN 3 THEN 'CR' WHEN 4 THEN 'AM' ELSE 'NF' END,
     CASE i WHEN 1 THEN 'Programme Manager' WHEN 2 THEN 'Delivery Lead' ELSE 'Content Specialist' END,
     'Bengaluru',0,0,NULL,'Y',1,exp_json,40,batch);
   -- Synthetic non-login subjects. Do not substitute a colleague's real SSO subject here.
   INSERT INTO APP_USER_ROLES(identity_subject,role_code,person_id,active_flag,effective_from,assigned_by)
   VALUES('seed:backend-p2:'||person_id_value,role_value,person_id_value,'Y',TRUNC(SYSDATE),batch);
   IF i<>1 THEN
     FOR skill IN (SELECT ds.skill_id FROM DELIVERABLE_SKILLS ds JOIN INTERESTS x ON x.interest_id=ds.skill_id
       WHERE ds.deliverable_id=d_id AND x.assessment_type='SELF_RATED') LOOP
       INSERT INTO PERSON_INTERESTS(person_id,interest_id,strength,evidence_note,source,interested_flag,updated_at,updated_by)
       VALUES(person_id_value,skill.skill_id,CASE WHEN i=5 THEN 3 ELSE 4 END,
         'Contributed to customer-facing delivery using this capability.',batch,'Y',SYSTIMESTAMP,batch);
     END LOOP;
   END IF;
 END LOOP;
 -- A visible non-availability event; matching daily inputs record its effect exactly once.
 INSERT INTO AVAILABILITY(person_id,event_type,starts_on,ends_on,title,allocated_hours,capacity_kind,created_by)
 VALUES('P-900104','Travel',start_day+4,start_day+4,'Customer workshop',8,'NON_AVAILABILITY',batch);
 FOR person_row IN (SELECT person_id,availability_version FROM PEOPLE WHERE staffing_seed_batch=batch) LOOP
   FOR offset_day IN 0..13 LOOP
     INSERT INTO PERSON_CAPACITY_DAYS(person_id,work_date,available_hours,external_committed_hours,
       input_refs_json,source_version,verified_at,verified_by,availability_version)
     VALUES(person_row.person_id,start_day+offset_day,
       CASE WHEN MOD(offset_day,7) IN (5,6) OR (person_row.person_id='P-900104' AND offset_day=4) THEN 0 ELSE 8 END,
       CASE WHEN MOD(offset_day,7) IN (5,6) OR (person_row.person_id='P-900104' AND offset_day=4) THEN 0
         WHEN person_row.person_id='P-900102' THEN 1.6 WHEN person_row.person_id='P-900103' THEN 2.4 ELSE 0 END,
       '{"source":"AIPS_BACKEND_P2_SEED_V1","basis":"40h Mon-Fri; external commitments exclude POD assignments; workshop subtracted"}',
       batch,SYSTIMESTAMP,batch,person_row.availability_version);
   END LOOP;
 END LOOP;
 FOR request_number IN 1..3 LOOP
   req_id:='REQ-'||TO_CHAR(900100+request_number,'FM999999');
   req_title:=CASE request_number WHEN 1 THEN 'Customer delivery planning' WHEN 2 THEN 'Parallel delivery programme'
     ELSE 'Specialist delivery review' END;
   effort:=CASE WHEN request_number=2 THEN 120 ELSE 24 END;
   INSERT INTO REQUESTS(request_id,title,project_type_id,project_type,deliverable_id,deliverable,deliverables_json,
     owner_name,request_source,request_source_person_id,project_description,needed_by,estimated_start_date,
     estimated_completion_date,estimated_effort_value,estimated_effort_unit,estimated_hours,
     requested_lead_count,requested_contributor_count,priority,status,business_objectives,expected_outcomes,
     mapping_version,responsible_captain_id,agent_enabled,staffing_seed_batch,created_by,updated_by)
   VALUES(req_id,req_title,p_id,p_name,d_id,d_name,d_json,'Amelia Hart','Amelia Hart','P-900101',p_desc,
     start_day+4,start_day,start_day+4,effort,'HOURS',effort,1,2,'MEDIUM','NEEDS_RECOMMENDATION',
     'Prepare clear customer-facing materials using the agreed deliverables.',
     'Deliver a reviewed package within the planned effort and schedule.',src_version,'P-900101','N',batch,batch,batch);
   FOR skill IN (SELECT ds.skill_id,ds.skill_name FROM DELIVERABLE_SKILLS ds JOIN INTERESTS x ON x.interest_id=ds.skill_id
       WHERE ds.deliverable_id=d_id AND x.assessment_type='SELF_RATED') LOOP
     INSERT INTO REQUIREMENTS(request_id,deliverable_id,interest_id,skill_name,capability_source,required_strength,
       requirement_source,source_version,mandatory_flag,created_by)
     VALUES(req_id,d_id,skill.skill_id,skill.skill_name,'MAPPED',3,batch,src_version,'Y',batch);
   END LOOP;
   IF request_number=3 THEN
     INSERT INTO REQUIREMENTS(request_id,skill_name,custom_capability_name,capability_source,requirement_source,source_version,mandatory_flag,created_by)
     VALUES(req_id,'Specialist capability to clarify','Specialist capability to clarify','CUSTOM',batch,src_version,'Y',batch);
   END IF;
 END LOOP;
 INSERT INTO AIPS_P2_MIGRATION(step_key,object_type,object_name,script_hash,state,applied_at)
 VALUES('SEED_V1','SEED','PEOPLE','seed-v1','APPLIED',SYSTIMESTAMP);
 COMMIT;
 DBMS_OUTPUT.PUT_LINE('SUCCESS: 5 new people, 3 new requests, role/skill evidence, 1 availability event and 70 capacity-day rows.');
 DBMS_OUTPUT.PUT_LINE('No original data changed. No assignments, policy approval, queued jobs or emails created.');
 DBMS_OUTPUT.PUT_LINE('REQ-900101: feasible fixture; REQ-900102: capacity pressure; REQ-900103: unresolved mandatory capability.');
EXCEPTION WHEN OTHERS THEN
 ROLLBACK;
 DBMS_OUTPUT.PUT_LINE('Seed transaction rolled back. Identity sequence gaps are harmless. Do not rerun setup.sql.');
 RAISE;
END;
/
