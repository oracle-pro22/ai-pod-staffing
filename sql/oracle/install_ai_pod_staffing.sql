-- ============================================================================
-- AI Pod Staffing - Oracle AI Database 26ai installation
-- Creates 11 Excel-backed tables, 7 operational tables, and loads seed data.
-- Source workbook: data/ai-pod-staffing-prototype.xlsx
-- Generated for schema: AI_POD_STAFFING
-- Run in SQL Developer with F5 (Run Script), not Ctrl+Enter.
-- Safety: this script never drops or overwrites an existing target table.
-- ============================================================================

SET DEFINE OFF
SET SERVEROUTPUT ON SIZE UNLIMITED
SET SQLBLANKLINES ON
SET FEEDBACK ON
SET VERIFY OFF
WHENEVER OSERROR EXIT FAILURE ROLLBACK
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK

PROMPT Starting AI Pod Staffing installation
PROMPT Running pre-flight safety checks

DECLARE
  l_existing NUMBER;
BEGIN
  IF USER <> 'AI_POD_STAFFING' THEN
    RAISE_APPLICATION_ERROR(-20001, 'Wrong schema. Connect as AI_POD_STAFFING before running this script. Current user: ' || USER);
  END IF;

  SELECT COUNT(*)
    INTO l_existing
    FROM USER_TABLES
   WHERE TABLE_NAME IN ('PROJECT_TYPES', 'INTERESTS', 'PEOPLE', 'CUSTOMER_MAPPING', 'DELIVERABLES', 'DELIVERABLE_SKILLS', 'PERSON_INTERESTS', 'AVAILABILITY', 'REQUESTS', 'REQUIREMENTS', 'RECOMMENDATIONS', 'ELIGIBILITY_RULES', 'LOAD_GUARDRAILS', 'SCORING_WEIGHTS', 'AGENT_EXECUTIONS', 'APPROVAL_DECISIONS', 'POD_ASSIGNMENTS', 'AUDIT_EVENTS');

  IF l_existing > 0 THEN
    RAISE_APPLICATION_ERROR(-20002, 'Installation stopped: one or more AI Pod target tables already exist. No tables were dropped.');
  END IF;
END;
/

PROMPT Pre-flight checks passed
PROMPT Creating 11 Excel-backed tables and 7 operational tables


CREATE TABLE PROJECT_TYPES (
  project_type_id     VARCHAR2(30)   NOT NULL,
  project_name        VARCHAR2(250)  NOT NULL,
  project_description VARCHAR2(2000) NOT NULL,
  source_version      VARCHAR2(40)   NOT NULL,
  source_row          NUMBER(10)     NOT NULL,
  CONSTRAINT pk_project_types PRIMARY KEY (project_type_id)
);

CREATE TABLE INTERESTS (
  interest_id         VARCHAR2(30)  NOT NULL,
  interest_name       VARCHAR2(250) NOT NULL,
  category            VARCHAR2(150) NOT NULL,
  source              VARCHAR2(100) NOT NULL,
  source_version      VARCHAR2(40)  NOT NULL,
  customer_controlled VARCHAR2(3)   NOT NULL,
  CONSTRAINT pk_interests PRIMARY KEY (interest_id),
  CONSTRAINT ck_int_customer CHECK (customer_controlled IN ('Yes', 'No'))
);

CREATE TABLE PEOPLE (
  person_id      VARCHAR2(30)  NOT NULL,
  full_name      VARCHAR2(250) NOT NULL,
  initials       VARCHAR2(10)  NOT NULL,
  job_title      VARCHAR2(250) NOT NULL,
  location       VARCHAR2(150) NOT NULL,
  allocation_pct NUMBER(5,2)   NOT NULL,
  active_pods    NUMBER(5)     NOT NULL,
  CONSTRAINT pk_people PRIMARY KEY (person_id),
  CONSTRAINT ck_people_alloc CHECK (allocation_pct BETWEEN 0 AND 100),
  CONSTRAINT ck_people_pods CHECK (active_pods >= 0)
);

CREATE TABLE CUSTOMER_MAPPING (
  projects              VARCHAR2(250),
  project_description   VARCHAR2(2000),
  deliverables          VARCHAR2(500),
  skills_type_of_work   VARCHAR2(1000),
  note                  VARCHAR2(1000),
  source_version        VARCHAR2(40) NOT NULL,
  source_row            NUMBER(10)   NOT NULL,
  customer_controlled   VARCHAR2(3)  NOT NULL,
  CONSTRAINT pk_customer_mapping PRIMARY KEY (source_version, source_row),
  CONSTRAINT ck_map_customer CHECK (customer_controlled IN ('Yes', 'No'))
);

CREATE TABLE DELIVERABLES (
  deliverable_id   VARCHAR2(30)   NOT NULL,
  project_type_id  VARCHAR2(30)   NOT NULL,
  project_name     VARCHAR2(250)  NOT NULL,
  deliverable_name VARCHAR2(500)  NOT NULL,
  skills_raw       VARCHAR2(1000) NOT NULL,
  customer_note    VARCHAR2(1000),
  source_version   VARCHAR2(40)   NOT NULL,
  source_row       NUMBER(10)     NOT NULL,
  CONSTRAINT pk_deliverables PRIMARY KEY (deliverable_id),
  CONSTRAINT fk_del_project_type FOREIGN KEY (project_type_id)
    REFERENCES PROJECT_TYPES (project_type_id)
);

CREATE TABLE DELIVERABLE_SKILLS (
  deliverable_id VARCHAR2(30)  NOT NULL,
  skill_id       VARCHAR2(30)  NOT NULL,
  skill_name     VARCHAR2(250) NOT NULL,
  source_version VARCHAR2(40)  NOT NULL,
  source_row     NUMBER(10)    NOT NULL,
  CONSTRAINT pk_deliverable_skills PRIMARY KEY (deliverable_id, skill_id),
  CONSTRAINT fk_ds_deliverable FOREIGN KEY (deliverable_id)
    REFERENCES DELIVERABLES (deliverable_id),
  CONSTRAINT fk_ds_interest FOREIGN KEY (skill_id)
    REFERENCES INTERESTS (interest_id)
);

CREATE TABLE PERSON_INTERESTS (
  person_id     VARCHAR2(30)   NOT NULL,
  interest_id   VARCHAR2(30)   NOT NULL,
  strength      NUMBER(3,1)    NOT NULL,
  evidence_note VARCHAR2(2000) NOT NULL,
  source        VARCHAR2(100)  NOT NULL,
  CONSTRAINT pk_person_interests PRIMARY KEY (person_id, interest_id),
  CONSTRAINT fk_pi_person FOREIGN KEY (person_id)
    REFERENCES PEOPLE (person_id),
  CONSTRAINT fk_pi_interest FOREIGN KEY (interest_id)
    REFERENCES INTERESTS (interest_id),
  CONSTRAINT ck_pi_strength CHECK (strength BETWEEN 1 AND 5)
);

CREATE TABLE AVAILABILITY (
  person_id       VARCHAR2(30)  NOT NULL,
  event_type      VARCHAR2(50)  NOT NULL,
  starts_on       DATE          NOT NULL,
  ends_on         DATE          NOT NULL,
  title           VARCHAR2(250) NOT NULL,
  allocated_hours NUMBER(10,2)  NOT NULL,
  CONSTRAINT pk_availability PRIMARY KEY (person_id, event_type, starts_on, ends_on, title),
  CONSTRAINT fk_avail_person FOREIGN KEY (person_id)
    REFERENCES PEOPLE (person_id),
  CONSTRAINT ck_avail_dates CHECK (ends_on >= starts_on),
  CONSTRAINT ck_avail_hours CHECK (allocated_hours >= 0)
);

CREATE TABLE REQUESTS (
  request_id          VARCHAR2(30)   NOT NULL,
  title               VARCHAR2(500)  NOT NULL,
  project_type_id     VARCHAR2(30)   NOT NULL,
  project_type        VARCHAR2(250)  NOT NULL,
  deliverable_id      VARCHAR2(30)   NOT NULL,
  deliverable         VARCHAR2(500)  NOT NULL,
  skills_type_of_work VARCHAR2(1000) NOT NULL,
  owner_name          VARCHAR2(250)  NOT NULL,
  needed_by           DATE           NOT NULL,
  estimated_hours     NUMBER(10,2)   NOT NULL,
  priority            VARCHAR2(30)   NOT NULL,
  status              VARCHAR2(50)   NOT NULL,
  business_context    VARCHAR2(2000) NOT NULL,
  mapping_version     VARCHAR2(40)   NOT NULL,
  CONSTRAINT pk_requests PRIMARY KEY (request_id),
  CONSTRAINT fk_req_project_type FOREIGN KEY (project_type_id)
    REFERENCES PROJECT_TYPES (project_type_id),
  CONSTRAINT fk_req_deliverable FOREIGN KEY (deliverable_id)
    REFERENCES DELIVERABLES (deliverable_id),
  CONSTRAINT ck_req_hours CHECK (estimated_hours >= 0)
);

CREATE TABLE REQUIREMENTS (
  request_id         VARCHAR2(30)  NOT NULL,
  deliverable_id     VARCHAR2(30)  NOT NULL,
  interest_id        VARCHAR2(30)  NOT NULL,
  skill_name         VARCHAR2(250) NOT NULL,
  required_strength  NUMBER(3,1),
  requirement_source VARCHAR2(100) NOT NULL,
  source_version     VARCHAR2(40)  NOT NULL,
  CONSTRAINT pk_requirements PRIMARY KEY (request_id, deliverable_id, interest_id),
  CONSTRAINT fk_rq_request FOREIGN KEY (request_id)
    REFERENCES REQUESTS (request_id),
  CONSTRAINT fk_rq_deliverable FOREIGN KEY (deliverable_id)
    REFERENCES DELIVERABLES (deliverable_id),
  CONSTRAINT fk_rq_interest FOREIGN KEY (interest_id)
    REFERENCES INTERESTS (interest_id),
  CONSTRAINT ck_rq_strength CHECK (required_strength IS NULL OR required_strength BETWEEN 1 AND 5)
);

CREATE TABLE RECOMMENDATIONS (
  request_id      VARCHAR2(30)   NOT NULL,
  person_id       VARCHAR2(30)   NOT NULL,
  role_in_pod     VARCHAR2(100)  NOT NULL,
  score           NUMBER(8,2)    NOT NULL,
  rationale       VARCHAR2(2000) NOT NULL,
  decision_status VARCHAR2(50)   NOT NULL,
  source          VARCHAR2(100)  NOT NULL,
  CONSTRAINT pk_recommendations PRIMARY KEY (request_id, person_id, role_in_pod),
  CONSTRAINT fk_rec_request FOREIGN KEY (request_id)
    REFERENCES REQUESTS (request_id),
  CONSTRAINT fk_rec_person FOREIGN KEY (person_id)
    REFERENCES PEOPLE (person_id),
  CONSTRAINT ck_rec_score CHECK (score BETWEEN 0 AND 100)
);

CREATE TABLE ELIGIBILITY_RULES (
  rule_id              NUMBER GENERATED BY DEFAULT ON NULL AS IDENTITY,
  rule_code            VARCHAR2(60)   NOT NULL,
  rule_name            VARCHAR2(250)  NOT NULL,
  rule_description     VARCHAR2(2000) NOT NULL,
  rule_type            VARCHAR2(30)   NOT NULL,
  rule_parameters_json CLOB,
  execution_order      NUMBER(5)      NOT NULL,
  rule_version         VARCHAR2(40)   NOT NULL,
  active_flag          CHAR(1) DEFAULT 'N' NOT NULL,
  effective_from       DATE,
  effective_to         DATE,
  CONSTRAINT pk_eligibility_rules PRIMARY KEY (rule_id),
  CONSTRAINT uq_elg_rule UNIQUE (rule_code, rule_version),
  CONSTRAINT ck_elg_active CHECK (active_flag IN ('Y', 'N')),
  CONSTRAINT ck_elg_dates CHECK (effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from),
  CONSTRAINT ck_elg_json CHECK (rule_parameters_json IS JSON)
);

CREATE TABLE LOAD_GUARDRAILS (
  guardrail_id      NUMBER GENERATED BY DEFAULT ON NULL AS IDENTITY,
  guardrail_code    VARCHAR2(60)  NOT NULL,
  guardrail_name    VARCHAR2(250) NOT NULL,
  guardrail_value   NUMBER(12,2)  NOT NULL,
  guardrail_unit    VARCHAR2(30)  NOT NULL,
  applies_to_role   VARCHAR2(100) DEFAULT 'ALL' NOT NULL,
  guardrail_version VARCHAR2(40)  NOT NULL,
  active_flag       CHAR(1) DEFAULT 'N' NOT NULL,
  effective_from    DATE,
  effective_to      DATE,
  CONSTRAINT pk_load_guardrails PRIMARY KEY (guardrail_id),
  CONSTRAINT uq_load_guard UNIQUE (guardrail_code, applies_to_role, guardrail_version),
  CONSTRAINT ck_lg_value CHECK (guardrail_value >= 0),
  CONSTRAINT ck_lg_unit CHECK (guardrail_unit IN ('PERCENT', 'COUNT', 'HOURS')),
  CONSTRAINT ck_lg_active CHECK (active_flag IN ('Y', 'N')),
  CONSTRAINT ck_lg_dates CHECK (effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from)
);

CREATE TABLE SCORING_WEIGHTS (
  weight_id        NUMBER GENERATED BY DEFAULT ON NULL AS IDENTITY,
  factor_code      VARCHAR2(60)  NOT NULL,
  factor_name      VARCHAR2(250) NOT NULL,
  weight_pct       NUMBER(5,2)   NOT NULL,
  role_in_pod      VARCHAR2(100) DEFAULT 'ALL' NOT NULL,
  weight_version   VARCHAR2(40)  NOT NULL,
  active_flag      CHAR(1) DEFAULT 'N' NOT NULL,
  effective_from   DATE,
  effective_to     DATE,
  CONSTRAINT pk_scoring_weights PRIMARY KEY (weight_id),
  CONSTRAINT uq_score_weight UNIQUE (factor_code, role_in_pod, weight_version),
  CONSTRAINT ck_sw_weight CHECK (weight_pct BETWEEN 0 AND 100),
  CONSTRAINT ck_sw_active CHECK (active_flag IN ('Y', 'N')),
  CONSTRAINT ck_sw_dates CHECK (effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from)
);

CREATE TABLE AGENT_EXECUTIONS (
  execution_id         NUMBER GENERATED BY DEFAULT ON NULL AS IDENTITY,
  request_id           VARCHAR2(30)  NOT NULL,
  agent_name           VARCHAR2(250) NOT NULL,
  agent_version        VARCHAR2(100),
  execution_status     VARCHAR2(30)  NOT NULL,
  started_at           TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
  completed_at         TIMESTAMP WITH TIME ZONE,
  rule_version         VARCHAR2(40),
  guardrail_version    VARCHAR2(40),
  weight_version       VARCHAR2(40),
  input_snapshot_json  CLOB,
  output_snapshot_json CLOB,
  error_message        CLOB,
  correlation_id       VARCHAR2(100),
  CONSTRAINT pk_agent_executions PRIMARY KEY (execution_id),
  CONSTRAINT fk_ae_request FOREIGN KEY (request_id)
    REFERENCES REQUESTS (request_id),
  CONSTRAINT uq_ae_correlation UNIQUE (correlation_id),
  CONSTRAINT ck_ae_status CHECK (execution_status IN ('QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')),
  CONSTRAINT ck_ae_dates CHECK (completed_at IS NULL OR completed_at >= started_at),
  CONSTRAINT ck_ae_input_json CHECK (input_snapshot_json IS JSON),
  CONSTRAINT ck_ae_output_json CHECK (output_snapshot_json IS JSON)
);

CREATE TABLE APPROVAL_DECISIONS (
  decision_id     NUMBER GENERATED BY DEFAULT ON NULL AS IDENTITY,
  request_id      VARCHAR2(30)   NOT NULL,
  person_id       VARCHAR2(30),
  role_in_pod     VARCHAR2(100),
  decision_type   VARCHAR2(30)   NOT NULL,
  decision_reason VARCHAR2(2000),
  decided_by      VARCHAR2(128)  NOT NULL,
  decided_at      TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
  CONSTRAINT pk_approval_decisions PRIMARY KEY (decision_id),
  CONSTRAINT fk_ad_request FOREIGN KEY (request_id)
    REFERENCES REQUESTS (request_id),
  CONSTRAINT fk_ad_recommendation FOREIGN KEY (request_id, person_id, role_in_pod)
    REFERENCES RECOMMENDATIONS (request_id, person_id, role_in_pod),
  CONSTRAINT ck_ad_target CHECK ((person_id IS NULL AND role_in_pod IS NULL) OR (person_id IS NOT NULL AND role_in_pod IS NOT NULL)),
  CONSTRAINT ck_ad_type CHECK (decision_type IN ('APPROVED', 'DECLINED', 'OVERRIDDEN'))
);

CREATE TABLE POD_ASSIGNMENTS (
  assignment_id      NUMBER GENERATED BY DEFAULT ON NULL AS IDENTITY,
  request_id         VARCHAR2(30)  NOT NULL,
  person_id          VARCHAR2(30)  NOT NULL,
  pod_role           VARCHAR2(100) NOT NULL,
  allocation_pct     NUMBER(5,2),
  allocated_hours    NUMBER(10,2),
  starts_on          DATE          NOT NULL,
  ends_on            DATE          NOT NULL,
  assignment_status  VARCHAR2(30) DEFAULT 'PLANNED' NOT NULL,
  assigned_by        VARCHAR2(128) NOT NULL,
  assigned_at        TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
  CONSTRAINT pk_pod_assignments PRIMARY KEY (assignment_id),
  CONSTRAINT uq_pod_assignment UNIQUE (request_id, person_id, pod_role, starts_on),
  CONSTRAINT fk_pa_request FOREIGN KEY (request_id)
    REFERENCES REQUESTS (request_id),
  CONSTRAINT fk_pa_person FOREIGN KEY (person_id)
    REFERENCES PEOPLE (person_id),
  CONSTRAINT ck_pa_alloc CHECK (allocation_pct IS NULL OR allocation_pct BETWEEN 0 AND 100),
  CONSTRAINT ck_pa_hours CHECK (allocated_hours IS NULL OR allocated_hours >= 0),
  CONSTRAINT ck_pa_dates CHECK (ends_on >= starts_on),
  CONSTRAINT ck_pa_status CHECK (assignment_status IN ('PLANNED', 'ACTIVE', 'COMPLETED', 'CANCELLED'))
);

CREATE BLOCKCHAIN TABLE AUDIT_EVENTS (
  audit_event_id   NUMBER GENERATED BY DEFAULT ON NULL AS IDENTITY,
  entity_type      VARCHAR2(60)  NOT NULL,
  entity_id        VARCHAR2(100) NOT NULL,
  action_type      VARCHAR2(60)  NOT NULL,
  performed_by     VARCHAR2(128) NOT NULL,
  performed_at     TIMESTAMP DEFAULT LOCALTIMESTAMP NOT NULL,
  correlation_id   VARCHAR2(100),
  before_state_json CLOB,
  after_state_json  CLOB,
  reason            VARCHAR2(2000),
  CONSTRAINT pk_audit_events PRIMARY KEY (audit_event_id),
  CONSTRAINT ck_audit_before_json CHECK (before_state_json IS JSON),
  CONSTRAINT ck_audit_after_json CHECK (after_state_json IS JSON)
)
NO DROP UNTIL 0 DAYS IDLE
NO DELETE LOCKED
HASHING USING SHA2_512 VERSION V2;

PROMPT All 18 tables created

PROMPT Loading 288 Excel source rows
PROMPT Loading Project Types: 11 rows
INSERT ALL
  INTO PROJECT_TYPES (project_type_id, project_name, project_description, source_version, source_row) VALUES ('PT-001', 'New Service Launch', 'New service launch (EA or GA) requiring GTM readiness and supporting assets.', 'v260810.1', 2)
  INTO PROJECT_TYPES (project_type_id, project_name, project_description, source_version, source_row) VALUES ('PT-002', 'Service Updates', 'Existing service updates, enhancements, expansions, maintenance, refreshes, pricing changes, EOL updates, name changes.', 'v260810.1', 11)
  INTO PROJECT_TYPES (project_type_id, project_name, project_description, source_version, source_row) VALUES ('PT-003', 'Demo Package', 'External content to promote AI use cases (OCAB style).  Demo package target audience is Customers, Sales, Executives.  Polished polished .ppt package with embedded videos (1 minute hook video and 5 min demo video)', 'v260810.1', 19)
  INTO PROJECT_TYPES (project_type_id, project_name, project_description, source_version, source_row) VALUES ('PT-004', 'Strategic Initiative Campaign Launch', 'Corporate initiatives or CSS Sales Plays aligned to strategic priorities (AI, Multicloud, SaaS, etc.).', 'v260810.1', 24)
  INTO PROJECT_TYPES (project_type_id, project_name, project_description, source_version, source_row) VALUES ('PT-005', 'Enablement', 'Training and field readiness activities not directly tied to a launch.', 'v260810.1', 33)
  INTO PROJECT_TYPES (project_type_id, project_name, project_description, source_version, source_row) VALUES ('PT-006', 'Executive Support', 'Executive requests and leadership communications.', 'v260810.1', 39)
  INTO PROJECT_TYPES (project_type_id, project_name, project_description, source_version, source_row) VALUES ('PT-007', 'Customer Story', 'Development and promotion of customer success stories, references, and long story decks', 'v260810.1', 44)
  INTO PROJECT_TYPES (project_type_id, project_name, project_description, source_version, source_row) VALUES ('PT-008', 'Use Case Content', 'Development of use case materials. Upload and maintain AI Use Cases artificats in AI Library/Innovation Portal.', 'v260810.1', 50)
  INTO PROJECT_TYPES (project_type_id, project_name, project_description, source_version, source_row) VALUES ('PT-009', 'Portal & Content Operations', 'Repository, Solution Matrix, SharePoint, and content management requests.', 'v260810.1', 54)
  INTO PROJECT_TYPES (project_type_id, project_name, project_description, source_version, source_row) VALUES ('PT-010', 'Reporting', 'Create/update  leadership reporting.  Examples include:  Monthly Gov. Package, Target Data, Pipeline and Booking, Enablement Metrics, Stories, References, etc.', 'v260810.1', 59)
  INTO PROJECT_TYPES (project_type_id, project_name, project_description, source_version, source_row) VALUES ('PT-011', 'Special Projects', 'Cross-functional initiatives that don''t fit into another category.', 'v260810.1', 64)
SELECT 1 FROM DUAL;

PROMPT Loading Interests: 13 rows
INSERT ALL
  INTO INTERESTS (interest_id, interest_name, category, source, source_version, customer_controlled) VALUES ('SK-001', 'Project Manager (GTM SME)', 'Project Management', 'Customer Mapping', 'v260810.1', 'Yes')
  INTO INTERESTS (interest_id, interest_name, category, source, source_version, customer_controlled) VALUES ('SK-002', 'GTM SME', 'Go-to-Market', 'Customer Mapping', 'v260810.1', 'Yes')
  INTO INTERESTS (interest_id, interest_name, category, source, source_version, customer_controlled) VALUES ('SK-003', 'Comms Review', 'Communications', 'Customer Mapping', 'v260810.1', 'Yes')
  INTO INTERESTS (interest_id, interest_name, category, source, source_version, customer_controlled) VALUES ('SK-004', 'Comms Plan', 'Communications', 'Customer Mapping', 'v260810.1', 'Yes')
  INTO INTERESTS (interest_id, interest_name, category, source, source_version, customer_controlled) VALUES ('SK-005', 'Portal SME', 'Portal Operations', 'Customer Mapping', 'v260810.1', 'Yes')
  INTO INTERESTS (interest_id, interest_name, category, source, source_version, customer_controlled) VALUES ('SK-006', 'GTM Buddy', 'Go-to-Market', 'Customer Mapping', 'v260810.1', 'Yes')
  INTO INTERESTS (interest_id, interest_name, category, source, source_version, customer_controlled) VALUES ('SK-007', 'Script writer (GTM SME)', 'Content Production', 'Customer Mapping', 'v260810.1', 'Yes')
  INTO INTERESTS (interest_id, interest_name, category, source, source_version, customer_controlled) VALUES ('SK-008', 'narration audio', 'Content Production', 'Customer Mapping', 'v260810.1', 'Yes')
  INTO INTERESTS (interest_id, interest_name, category, source, source_version, customer_controlled) VALUES ('SK-009', 'visual asset', 'Content Production', 'Customer Mapping', 'v260810.1', 'Yes')
  INTO INTERESTS (interest_id, interest_name, category, source, source_version, customer_controlled) VALUES ('SK-010', 'video creation', 'Content Production', 'Customer Mapping', 'v260810.1', 'Yes')
  INTO INTERESTS (interest_id, interest_name, category, source, source_version, customer_controlled) VALUES ('SK-011', 'GTM', 'Go-to-Market', 'Customer Mapping', 'v260810.1', 'Yes')
  INTO INTERESTS (interest_id, interest_name, category, source, source_version, customer_controlled) VALUES ('SK-012', 'GMT SME', 'Go-to-Market', 'Customer Mapping', 'v260810.1', 'Yes')
  INTO INTERESTS (interest_id, interest_name, category, source, source_version, customer_controlled) VALUES ('SK-013', 'Comms', 'Communications', 'Customer Mapping', 'v260810.1', 'Yes')
SELECT 1 FROM DUAL;

PROMPT Loading People: 8 rows
INSERT ALL
  INTO PEOPLE (person_id, full_name, initials, job_title, location, allocation_pct, active_pods) VALUES ('P-001', 'Alex Rivera', 'AR', 'Senior Content Strategist', 'Austin', 68, 3)
  INTO PEOPLE (person_id, full_name, initials, job_title, location, allocation_pct, active_pods) VALUES ('P-002', 'Maya Chen', 'MC', 'Video Producer', 'Seattle', 84, 4)
  INTO PEOPLE (person_id, full_name, initials, job_title, location, allocation_pct, active_pods) VALUES ('P-003', 'Jordan Lee', 'JL', 'Technical Writer', 'Denver', 76, 3)
  INTO PEOPLE (person_id, full_name, initials, job_title, location, allocation_pct, active_pods) VALUES ('P-004', 'Priya Nair', 'PN', 'Enablement Lead', 'Bengaluru', 62, 2)
  INTO PEOPLE (person_id, full_name, initials, job_title, location, allocation_pct, active_pods) VALUES ('P-005', 'Sam Okafor', 'SO', 'Creative Director', 'London', 71, 3)
  INTO PEOPLE (person_id, full_name, initials, job_title, location, allocation_pct, active_pods) VALUES ('P-006', 'Elena Garcia', 'EG', 'Communications Manager', 'Madrid', 48, 2)
  INTO PEOPLE (person_id, full_name, initials, job_title, location, allocation_pct, active_pods) VALUES ('P-007', 'Noah Williams', 'NW', 'Video Editor', 'Chicago', 54, 2)
  INTO PEOPLE (person_id, full_name, initials, job_title, location, allocation_pct, active_pods) VALUES ('P-008', 'Aisha Patel', 'AP', 'Learning Designer', 'Atlanta', 39, 1)
SELECT 1 FROM DUAL;

PROMPT Loading Deliverables: 55 rows
INSERT ALL
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-001', 'PT-001', 'New Service Launch', 'Project Coordination', 'Project Manager (GTM SME)', NULL, 'v260810.1', 2)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-002', 'PT-001', 'New Service Launch', 'Sales Guide (deck)', 'GTM SME', NULL, 'v260810.1', 3)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-003', 'PT-001', 'New Service Launch', 'Customer Deck', 'GTM SME', NULL, 'v260810.1', 4)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-004', 'PT-001', 'New Service Launch', 'Training Deck', 'GTM SME', NULL, 'v260810.1', 5)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-005', 'PT-001', 'New Service Launch', 'Launch Communication', 'GTM SME, Comms Review, Comms Plan', NULL, 'v260810.1', 6)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-006', 'PT-001', 'New Service Launch', 'Solution Matrix Updates', 'GTM SME', NULL, 'v260810.1', 7)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-007', 'PT-001', 'New Service Launch', 'Internal Portal Updates', 'GTM SME, Portal SME', NULL, 'v260810.1', 8)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-008', 'PT-001', 'New Service Launch', 'Enablement Webinar', 'GTM SME, GTM Buddy', NULL, 'v260810.1', 9)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-009', 'PT-002', 'Service Updates', 'Project Coordination', 'Project Manager (GTM SME)', NULL, 'v260810.1', 11)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-010', 'PT-002', 'Service Updates', 'Sales Guide (deck)', 'GTM SME', NULL, 'v260810.1', 12)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-011', 'PT-002', 'Service Updates', 'Customer Deck', 'GTM SME', NULL, 'v260810.1', 13)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-012', 'PT-002', 'Service Updates', 'Training Deck', 'GTM SME', NULL, 'v260810.1', 14)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-013', 'PT-002', 'Service Updates', 'Launch Communication', 'GTM SME, Comms Review, Comms Plan', NULL, 'v260810.1', 15)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-014', 'PT-002', 'Service Updates', 'Solution Matrix Updates', 'GTM SME', NULL, 'v260810.1', 16)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-015', 'PT-002', 'Service Updates', 'Internal Portal Updates', 'GTM SME, Portal SME', NULL, 'v260810.1', 17)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-016', 'PT-003', 'Demo Package', 'Project', 'Project Manager (GTM SME)', 'PM is also GTM Lead', 'v260810.1', 19)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-017', 'PT-003', 'Demo Package', 'Demo Deck', 'GTM SME', NULL, 'v260810.1', 20)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-018', 'PT-003', 'Demo Package', 'Hook video', 'Script writer (GTM SME), Comms Review, narration audio, visual asset, video creation', NULL, 'v260810.1', 21)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-019', 'PT-003', 'Demo Package', 'Demo video', 'Script writer (GTM SME), Comms Review, narration audio, visual asset, video creation', NULL, 'v260810.1', 22)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-020', 'PT-004', 'Strategic Initiative Campaign Launch', 'Launch Communication', 'GTM SME, Comms Review, Comms Plan', NULL, 'v260810.1', 24)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-021', 'PT-004', 'Strategic Initiative Campaign Launch', 'Target Data', 'GTM SME', NULL, 'v260810.1', 25)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-022', 'PT-004', 'Strategic Initiative Campaign Launch', 'Training Deck', 'GTM SME', NULL, 'v260810.1', 26)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-023', 'PT-004', 'Strategic Initiative Campaign Launch', 'Reporting', 'GTM SME', 'eg., update monthly Gov Package', 'v260810.1', 27)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-024', 'PT-004', 'Strategic Initiative Campaign Launch', 'Messaging', 'GTM SME', NULL, 'v260810.1', 28)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-025', 'PT-004', 'Strategic Initiative Campaign Launch', 'Sale sPlays', 'GTM SME', NULL, 'v260810.1', 29)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-026', 'PT-004', 'Strategic Initiative Campaign Launch', 'Customer Assets', 'GTM SME', NULL, 'v260810.1', 30)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-027', 'PT-004', 'Strategic Initiative Campaign Launch', 'Enablement Webinar', 'GTM SME, GTM Buddy', NULL, 'v260810.1', 31)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-028', 'PT-005', 'Enablement', 'Prepare for Live Session', 'GTM SME', NULL, 'v260810.1', 33)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-029', 'PT-005', 'Enablement', 'Create recorded training', 'GTM SME', NULL, 'v260810.1', 34)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-030', 'PT-005', 'Enablement', 'Create Training Deck', 'GTM', NULL, 'v260810.1', 35)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-031', 'PT-005', 'Enablement', 'Post Replay Assets', 'GMT SME', NULL, 'v260810.1', 36)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-032', 'PT-005', 'Enablement', 'Conduct Enablement Webinar', 'GTM SME, GTM Buddy', NULL, 'v260810.1', 37)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-033', 'PT-006', 'Executive Support', 'Executive Decks', 'GTM SME, Comms Review, Comms Plan', NULL, 'v260810.1', 39)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-034', 'PT-006', 'Executive Support', 'QBRs', 'GTM SME, Comms Review, Comms Plan', NULL, 'v260810.1', 40)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-035', 'PT-006', 'Executive Support', 'All Hands Content', 'GTM SME, Comms Review, Comms Plan', NULL, 'v260810.1', 41)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-036', 'PT-006', 'Executive Support', 'Executive Messaging', 'GTM SME, Comms Review, Comms Plan', NULL, 'v260810.1', 42)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-037', 'PT-007', 'Customer Story', 'Story Creation', 'GTM SME', NULL, 'v260810.1', 44)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-038', 'PT-007', 'Customer Story', 'Reference Content', 'GTM SME', NULL, 'v260810.1', 45)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-039', 'PT-007', 'Customer Story', 'Interviews', 'GTM SME', NULL, 'v260810.1', 46)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-040', 'PT-007', 'Customer Story', 'Videos', 'GTM SME', NULL, 'v260810.1', 47)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-041', 'PT-007', 'Customer Story', 'Amplification', 'GTM SME, Comms Review, Comms Plan', NULL, 'v260810.1', 48)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-042', 'PT-008', 'Use Case Content', 'Create AI Use Case Content', 'GTM SME', 'Exec 1-Pager, Demo Package, Videos (Hook and Demo)', 'v260810.1', 50)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-043', 'PT-008', 'Use Case Content', 'Upload / Maintain AI Use Artifacts to AI Library / Innovation Portal', 'GTM SME', 'Exec 1-Pager, Demo Package, Videos (Hook and Demo)', 'v260810.1', 51)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-044', 'PT-008', 'Use Case Content', 'Amplification', 'GTM SME, Comms Review, Comms Plan', NULL, 'v260810.1', 52)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-045', 'PT-009', 'Portal & Content Operations', 'Portal Updates', 'GTM SME', NULL, 'v260810.1', 54)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-046', 'PT-009', 'Portal & Content Operations', 'Solution Matrix Administration', 'GTM SME', NULL, 'v260810.1', 55)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-047', 'PT-009', 'Portal & Content Operations', 'Asset Publishing', 'GTM SME', NULL, 'v260810.1', 56)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-048', 'PT-009', 'Portal & Content Operations', 'File Management', 'GTM SME', NULL, 'v260810.1', 57)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-049', 'PT-010', 'Reporting', 'Pipeline and Booking', 'Comms, GTM SME', 'Dragos (primary); Indranie (support)', 'v260810.1', 59)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-050', 'PT-010', 'Reporting', 'Target Data', 'GTM SME', 'e.g., Monthly Gov Package', 'v260810.1', 60)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-051', 'PT-011', 'Special Projects', 'Research', 'GTM SME', NULL, 'v260810.1', 64)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-052', 'PT-011', 'Special Projects', 'Content Strategy', 'GTM SME', NULL, 'v260810.1', 65)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-053', 'PT-011', 'Special Projects', 'COE Support', 'GTM SME', NULL, 'v260810.1', 66)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-054', 'PT-011', 'Special Projects', 'AI World', 'GTM SME', 'e.g, Casey, Indranie, Dragos', 'v260810.1', 67)
  INTO DELIVERABLES (deliverable_id, project_type_id, project_name, deliverable_name, skills_raw, customer_note, source_version, source_row) VALUES ('DEL-055', 'PT-011', 'Special Projects', 'Process Improvement', 'GTM SME', NULL, 'v260810.1', 68)
SELECT 1 FROM DUAL;

PROMPT Loading Deliverable Skills: 87 rows
INSERT ALL
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-001', 'SK-001', 'Project Manager (GTM SME)', 'v260810.1', 2)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-002', 'SK-002', 'GTM SME', 'v260810.1', 3)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-003', 'SK-002', 'GTM SME', 'v260810.1', 4)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-004', 'SK-002', 'GTM SME', 'v260810.1', 5)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-005', 'SK-002', 'GTM SME', 'v260810.1', 6)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-005', 'SK-003', 'Comms Review', 'v260810.1', 6)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-005', 'SK-004', 'Comms Plan', 'v260810.1', 6)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-006', 'SK-002', 'GTM SME', 'v260810.1', 7)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-007', 'SK-002', 'GTM SME', 'v260810.1', 8)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-007', 'SK-005', 'Portal SME', 'v260810.1', 8)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-008', 'SK-002', 'GTM SME', 'v260810.1', 9)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-008', 'SK-006', 'GTM Buddy', 'v260810.1', 9)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-009', 'SK-001', 'Project Manager (GTM SME)', 'v260810.1', 11)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-010', 'SK-002', 'GTM SME', 'v260810.1', 12)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-011', 'SK-002', 'GTM SME', 'v260810.1', 13)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-012', 'SK-002', 'GTM SME', 'v260810.1', 14)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-013', 'SK-002', 'GTM SME', 'v260810.1', 15)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-013', 'SK-003', 'Comms Review', 'v260810.1', 15)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-013', 'SK-004', 'Comms Plan', 'v260810.1', 15)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-014', 'SK-002', 'GTM SME', 'v260810.1', 16)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-015', 'SK-002', 'GTM SME', 'v260810.1', 17)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-015', 'SK-005', 'Portal SME', 'v260810.1', 17)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-016', 'SK-001', 'Project Manager (GTM SME)', 'v260810.1', 19)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-017', 'SK-002', 'GTM SME', 'v260810.1', 20)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-018', 'SK-007', 'Script writer (GTM SME)', 'v260810.1', 21)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-018', 'SK-003', 'Comms Review', 'v260810.1', 21)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-018', 'SK-008', 'narration audio', 'v260810.1', 21)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-018', 'SK-009', 'visual asset', 'v260810.1', 21)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-018', 'SK-010', 'video creation', 'v260810.1', 21)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-019', 'SK-007', 'Script writer (GTM SME)', 'v260810.1', 22)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-019', 'SK-003', 'Comms Review', 'v260810.1', 22)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-019', 'SK-008', 'narration audio', 'v260810.1', 22)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-019', 'SK-009', 'visual asset', 'v260810.1', 22)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-019', 'SK-010', 'video creation', 'v260810.1', 22)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-020', 'SK-002', 'GTM SME', 'v260810.1', 24)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-020', 'SK-003', 'Comms Review', 'v260810.1', 24)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-020', 'SK-004', 'Comms Plan', 'v260810.1', 24)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-021', 'SK-002', 'GTM SME', 'v260810.1', 25)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-022', 'SK-002', 'GTM SME', 'v260810.1', 26)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-023', 'SK-002', 'GTM SME', 'v260810.1', 27)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-024', 'SK-002', 'GTM SME', 'v260810.1', 28)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-025', 'SK-002', 'GTM SME', 'v260810.1', 29)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-026', 'SK-002', 'GTM SME', 'v260810.1', 30)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-027', 'SK-002', 'GTM SME', 'v260810.1', 31)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-027', 'SK-006', 'GTM Buddy', 'v260810.1', 31)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-028', 'SK-002', 'GTM SME', 'v260810.1', 33)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-029', 'SK-002', 'GTM SME', 'v260810.1', 34)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-030', 'SK-011', 'GTM', 'v260810.1', 35)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-031', 'SK-012', 'GMT SME', 'v260810.1', 36)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-032', 'SK-002', 'GTM SME', 'v260810.1', 37)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-032', 'SK-006', 'GTM Buddy', 'v260810.1', 37)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-033', 'SK-002', 'GTM SME', 'v260810.1', 39)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-033', 'SK-003', 'Comms Review', 'v260810.1', 39)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-033', 'SK-004', 'Comms Plan', 'v260810.1', 39)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-034', 'SK-002', 'GTM SME', 'v260810.1', 40)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-034', 'SK-003', 'Comms Review', 'v260810.1', 40)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-034', 'SK-004', 'Comms Plan', 'v260810.1', 40)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-035', 'SK-002', 'GTM SME', 'v260810.1', 41)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-035', 'SK-003', 'Comms Review', 'v260810.1', 41)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-035', 'SK-004', 'Comms Plan', 'v260810.1', 41)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-036', 'SK-002', 'GTM SME', 'v260810.1', 42)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-036', 'SK-003', 'Comms Review', 'v260810.1', 42)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-036', 'SK-004', 'Comms Plan', 'v260810.1', 42)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-037', 'SK-002', 'GTM SME', 'v260810.1', 44)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-038', 'SK-002', 'GTM SME', 'v260810.1', 45)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-039', 'SK-002', 'GTM SME', 'v260810.1', 46)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-040', 'SK-002', 'GTM SME', 'v260810.1', 47)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-041', 'SK-002', 'GTM SME', 'v260810.1', 48)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-041', 'SK-003', 'Comms Review', 'v260810.1', 48)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-041', 'SK-004', 'Comms Plan', 'v260810.1', 48)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-042', 'SK-002', 'GTM SME', 'v260810.1', 50)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-043', 'SK-002', 'GTM SME', 'v260810.1', 51)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-044', 'SK-002', 'GTM SME', 'v260810.1', 52)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-044', 'SK-003', 'Comms Review', 'v260810.1', 52)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-044', 'SK-004', 'Comms Plan', 'v260810.1', 52)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-045', 'SK-002', 'GTM SME', 'v260810.1', 54)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-046', 'SK-002', 'GTM SME', 'v260810.1', 55)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-047', 'SK-002', 'GTM SME', 'v260810.1', 56)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-048', 'SK-002', 'GTM SME', 'v260810.1', 57)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-049', 'SK-013', 'Comms', 'v260810.1', 59)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-049', 'SK-002', 'GTM SME', 'v260810.1', 59)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-050', 'SK-002', 'GTM SME', 'v260810.1', 60)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-051', 'SK-002', 'GTM SME', 'v260810.1', 64)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-052', 'SK-002', 'GTM SME', 'v260810.1', 65)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-053', 'SK-002', 'GTM SME', 'v260810.1', 66)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-054', 'SK-002', 'GTM SME', 'v260810.1', 67)
  INTO DELIVERABLE_SKILLS (deliverable_id, skill_id, skill_name, source_version, source_row) VALUES ('DEL-055', 'SK-002', 'GTM SME', 'v260810.1', 68)
SELECT 1 FROM DUAL;

PROMPT Loading Person Interests: 27 rows
INSERT ALL
  INTO PERSON_INTERESTS (person_id, interest_id, strength, evidence_note, source) VALUES ('P-001', 'SK-002', 5, 'Customer story and launch narrative support', 'Prototype/Demo')
  INTO PERSON_INTERESTS (person_id, interest_id, strength, evidence_note, source) VALUES ('P-001', 'SK-004', 5, 'Executive campaign communication planning', 'Prototype/Demo')
  INTO PERSON_INTERESTS (person_id, interest_id, strength, evidence_note, source) VALUES ('P-001', 'SK-007', 4, 'Executive video script development', 'Prototype/Demo')
  INTO PERSON_INTERESTS (person_id, interest_id, strength, evidence_note, source) VALUES ('P-002', 'SK-010', 5, 'Product launch video production', 'Prototype/Demo')
  INTO PERSON_INTERESTS (person_id, interest_id, strength, evidence_note, source) VALUES ('P-002', 'SK-009', 5, 'Demo and launch visual development', 'Prototype/Demo')
  INTO PERSON_INTERESTS (person_id, interest_id, strength, evidence_note, source) VALUES ('P-002', 'SK-008', 4, 'Narration production coordination', 'Prototype/Demo')
  INTO PERSON_INTERESTS (person_id, interest_id, strength, evidence_note, source) VALUES ('P-003', 'SK-002', 4, 'Technical customer-facing content', 'Prototype/Demo')
  INTO PERSON_INTERESTS (person_id, interest_id, strength, evidence_note, source) VALUES ('P-003', 'SK-003', 4, 'Structured editorial and communications review', 'Prototype/Demo')
  INTO PERSON_INTERESTS (person_id, interest_id, strength, evidence_note, source) VALUES ('P-003', 'SK-007', 4, 'Technical demo scripting', 'Prototype/Demo')
  INTO PERSON_INTERESTS (person_id, interest_id, strength, evidence_note, source) VALUES ('P-004', 'SK-002', 5, 'Enablement and field readiness leadership', 'Prototype/Demo')
  INTO PERSON_INTERESTS (person_id, interest_id, strength, evidence_note, source) VALUES ('P-004', 'SK-006', 5, 'Enablement webinar delivery support', 'Prototype/Demo')
  INTO PERSON_INTERESTS (person_id, interest_id, strength, evidence_note, source) VALUES ('P-004', 'SK-011', 5, 'Training deck creation', 'Prototype/Demo')
  INTO PERSON_INTERESTS (person_id, interest_id, strength, evidence_note, source) VALUES ('P-004', 'SK-012', 4, 'Post replay asset support — exact customer label retained', 'Prototype/Demo')
  INTO PERSON_INTERESTS (person_id, interest_id, strength, evidence_note, source) VALUES ('P-005', 'SK-003', 5, 'Executive and customer asset review', 'Prototype/Demo')
  INTO PERSON_INTERESTS (person_id, interest_id, strength, evidence_note, source) VALUES ('P-005', 'SK-004', 4, 'Creative campaign planning', 'Prototype/Demo')
  INTO PERSON_INTERESTS (person_id, interest_id, strength, evidence_note, source) VALUES ('P-005', 'SK-009', 5, 'Creative direction for customer assets', 'Prototype/Demo')
  INTO PERSON_INTERESTS (person_id, interest_id, strength, evidence_note, source) VALUES ('P-006', 'SK-001', 5, 'Cross-functional launch coordination', 'Prototype/Demo')
  INTO PERSON_INTERESTS (person_id, interest_id, strength, evidence_note, source) VALUES ('P-006', 'SK-002', 5, 'Go-to-market leadership', 'Prototype/Demo')
  INTO PERSON_INTERESTS (person_id, interest_id, strength, evidence_note, source) VALUES ('P-006', 'SK-003', 5, 'Leadership communication review', 'Prototype/Demo')
  INTO PERSON_INTERESTS (person_id, interest_id, strength, evidence_note, source) VALUES ('P-006', 'SK-004', 5, 'Launch communication planning', 'Prototype/Demo')
  INTO PERSON_INTERESTS (person_id, interest_id, strength, evidence_note, source) VALUES ('P-006', 'SK-013', 5, 'Leadership reporting communications', 'Prototype/Demo')
  INTO PERSON_INTERESTS (person_id, interest_id, strength, evidence_note, source) VALUES ('P-007', 'SK-010', 5, 'Demo and hook video editing', 'Prototype/Demo')
  INTO PERSON_INTERESTS (person_id, interest_id, strength, evidence_note, source) VALUES ('P-007', 'SK-009', 4, 'Video visual production', 'Prototype/Demo')
  INTO PERSON_INTERESTS (person_id, interest_id, strength, evidence_note, source) VALUES ('P-007', 'SK-008', 4, 'Narration synchronization and finishing', 'Prototype/Demo')
  INTO PERSON_INTERESTS (person_id, interest_id, strength, evidence_note, source) VALUES ('P-008', 'SK-002', 4, 'Learning and enablement content', 'Prototype/Demo')
  INTO PERSON_INTERESTS (person_id, interest_id, strength, evidence_note, source) VALUES ('P-008', 'SK-006', 4, 'Live enablement session support', 'Prototype/Demo')
  INTO PERSON_INTERESTS (person_id, interest_id, strength, evidence_note, source) VALUES ('P-008', 'SK-005', 3, 'Training asset publishing and portal maintenance', 'Prototype/Demo')
SELECT 1 FROM DUAL;

PROMPT Loading Availability: 4 rows
INSERT ALL
  INTO AVAILABILITY (person_id, event_type, starts_on, ends_on, title, allocated_hours) VALUES ('P-005', 'Travel', DATE '2026-07-28', DATE '2026-07-30', 'Customer workshop', 24)
  INTO AVAILABILITY (person_id, event_type, starts_on, ends_on, title, allocated_hours) VALUES ('P-002', 'Travel', DATE '2026-07-23', DATE '2026-07-23', 'Production travel', 8)
  INTO AVAILABILITY (person_id, event_type, starts_on, ends_on, title, allocated_hours) VALUES ('P-006', 'Commitment', DATE '2026-07-24', DATE '2026-07-24', 'AI adoption video', 8)
  INTO AVAILABILITY (person_id, event_type, starts_on, ends_on, title, allocated_hours) VALUES ('P-007', 'Commitment', DATE '2026-07-21', DATE '2026-07-21', 'Video edit review', 6)
SELECT 1 FROM DUAL;

PROMPT Loading Requests: 3 rows
INSERT ALL
  INTO REQUESTS (request_id, title, project_type_id, project_type, deliverable_id, deliverable, skills_type_of_work, owner_name, needed_by, estimated_hours, priority, status, business_context, mapping_version) VALUES ('REQ-1042', 'AI service launch communication', 'PT-001', 'New Service Launch', 'DEL-005', 'Launch Communication', 'GTM SME, Comms Review, Comms Plan', 'Amy Lawrence', DATE '2026-08-07', 72, 'High', 'Needs recommendation', 'New service launch (EA or GA) requiring GTM readiness and supporting assets.', 'v260810.1')
  INTO REQUESTS (request_id, title, project_type_id, project_type, deliverable_id, deliverable, skills_type_of_work, owner_name, needed_by, estimated_hours, priority, status, business_context, mapping_version) VALUES ('REQ-1041', 'Customer AI demo package', 'PT-003', 'Demo Package', 'DEL-019', 'Demo video', 'Script writer (GTM SME), Comms Review, narration audio, visual asset, video creation', 'Rohan Shah', DATE '2026-08-03', 48, 'High', 'In review', 'External content to promote AI use cases (OCAB style).  Demo package target audience is Customers, Sales, Executives.  Polished polished .ppt package with embedded videos (1 minute hook video and 5 min demo video)', 'v260810.1')
  INTO REQUESTS (request_id, title, project_type_id, project_type, deliverable_id, deliverable, skills_type_of_work, owner_name, needed_by, estimated_hours, priority, status, business_context, mapping_version) VALUES ('REQ-1039', 'Partner enablement webinar', 'PT-005', 'Enablement', 'DEL-032', 'Conduct Enablement Webinar', 'GTM SME, GTM Buddy', 'Marta Ruiz', DATE '2026-08-14', 64, 'Normal', 'Staffed', 'Training and field readiness activities not directly tied to a launch.', 'v260810.1')
SELECT 1 FROM DUAL;

PROMPT Loading Requirements: 10 rows
INSERT ALL
  INTO REQUIREMENTS (request_id, deliverable_id, interest_id, skill_name, required_strength, requirement_source, source_version) VALUES ('REQ-1042', 'DEL-005', 'SK-002', 'GTM SME', NULL, 'Customer Mapping', 'v260810.1')
  INTO REQUIREMENTS (request_id, deliverable_id, interest_id, skill_name, required_strength, requirement_source, source_version) VALUES ('REQ-1042', 'DEL-005', 'SK-003', 'Comms Review', NULL, 'Customer Mapping', 'v260810.1')
  INTO REQUIREMENTS (request_id, deliverable_id, interest_id, skill_name, required_strength, requirement_source, source_version) VALUES ('REQ-1042', 'DEL-005', 'SK-004', 'Comms Plan', NULL, 'Customer Mapping', 'v260810.1')
  INTO REQUIREMENTS (request_id, deliverable_id, interest_id, skill_name, required_strength, requirement_source, source_version) VALUES ('REQ-1041', 'DEL-019', 'SK-007', 'Script writer (GTM SME)', NULL, 'Customer Mapping', 'v260810.1')
  INTO REQUIREMENTS (request_id, deliverable_id, interest_id, skill_name, required_strength, requirement_source, source_version) VALUES ('REQ-1041', 'DEL-019', 'SK-003', 'Comms Review', NULL, 'Customer Mapping', 'v260810.1')
  INTO REQUIREMENTS (request_id, deliverable_id, interest_id, skill_name, required_strength, requirement_source, source_version) VALUES ('REQ-1041', 'DEL-019', 'SK-008', 'narration audio', NULL, 'Customer Mapping', 'v260810.1')
  INTO REQUIREMENTS (request_id, deliverable_id, interest_id, skill_name, required_strength, requirement_source, source_version) VALUES ('REQ-1041', 'DEL-019', 'SK-009', 'visual asset', NULL, 'Customer Mapping', 'v260810.1')
  INTO REQUIREMENTS (request_id, deliverable_id, interest_id, skill_name, required_strength, requirement_source, source_version) VALUES ('REQ-1041', 'DEL-019', 'SK-010', 'video creation', NULL, 'Customer Mapping', 'v260810.1')
  INTO REQUIREMENTS (request_id, deliverable_id, interest_id, skill_name, required_strength, requirement_source, source_version) VALUES ('REQ-1039', 'DEL-032', 'SK-002', 'GTM SME', NULL, 'Customer Mapping', 'v260810.1')
  INTO REQUIREMENTS (request_id, deliverable_id, interest_id, skill_name, required_strength, requirement_source, source_version) VALUES ('REQ-1039', 'DEL-032', 'SK-006', 'GTM Buddy', NULL, 'Customer Mapping', 'v260810.1')
SELECT 1 FROM DUAL;

PROMPT Loading Recommendations: 3 rows
INSERT ALL
  INTO RECOMMENDATIONS (request_id, person_id, role_in_pod, score, rationale, decision_status, source) VALUES ('REQ-1042', 'P-006', 'Pod lead', 94, 'Covers GTM SME, Comms Review and Comms Plan with strong launch coordination evidence.', 'Pending review', 'Prototype/Demo')
  INTO RECOMMENDATIONS (request_id, person_id, role_in_pod, score, rationale, decision_status, source) VALUES ('REQ-1042', 'P-001', 'Contributor', 89, 'Strong GTM SME and Comms Plan evidence for customer-facing launch messaging.', 'Pending review', 'Prototype/Demo')
  INTO RECOMMENDATIONS (request_id, person_id, role_in_pod, score, rationale, decision_status, source) VALUES ('REQ-1042', 'P-005', 'Contributor', 86, 'Provides Comms Review and Comms Plan coverage for the launch communication deliverable.', 'Pending review', 'Prototype/Demo')
SELECT 1 FROM DUAL;

PROMPT Loading Customer Mapping: 67 rows
INSERT ALL
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES ('New Service Launch', 'New service launch (EA or GA) requiring GTM readiness and supporting assets.', 'Project Coordination', 'Project Manager (GTM SME)', NULL, 'v260810.1', 2, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Sales Guide (deck)', 'GTM SME', NULL, 'v260810.1', 3, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Customer Deck', 'GTM SME', NULL, 'v260810.1', 4, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Training Deck', 'GTM SME', NULL, 'v260810.1', 5, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Launch Communication', 'GTM SME, Comms Review, Comms Plan', NULL, 'v260810.1', 6, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Solution Matrix Updates', 'GTM SME', NULL, 'v260810.1', 7, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Internal Portal Updates', 'GTM SME, Portal SME', NULL, 'v260810.1', 8, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Enablement Webinar', 'GTM SME, GTM Buddy', NULL, 'v260810.1', 9, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, NULL, NULL, NULL, 'v260810.1', 10, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES ('Service Updates', 'Existing service updates, enhancements, expansions, maintenance, refreshes, pricing changes, EOL updates, name changes.', 'Project Coordination', 'Project Manager (GTM SME)', NULL, 'v260810.1', 11, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Sales Guide (deck)', 'GTM SME', NULL, 'v260810.1', 12, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Customer Deck', 'GTM SME', NULL, 'v260810.1', 13, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Training Deck', 'GTM SME', NULL, 'v260810.1', 14, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Launch Communication', 'GTM SME, Comms Review, Comms Plan', NULL, 'v260810.1', 15, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Solution Matrix Updates', 'GTM SME', NULL, 'v260810.1', 16, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Internal Portal Updates', 'GTM SME, Portal SME', NULL, 'v260810.1', 17, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, NULL, NULL, NULL, 'v260810.1', 18, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES ('Demo Package', 'External content to promote AI use cases (OCAB style).  Demo package target audience is Customers, Sales, Executives.  Polished polished .ppt package with embedded videos (1 minute hook video and 5 min demo video)', 'Project', 'Project Manager (GTM SME)', 'PM is also GTM Lead', 'v260810.1', 19, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Demo Deck', 'GTM SME', NULL, 'v260810.1', 20, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Hook video', 'Script writer (GTM SME), Comms Review, narration audio, visual asset, video creation', NULL, 'v260810.1', 21, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Demo video', 'Script writer (GTM SME), Comms Review, narration audio, visual asset, video creation', NULL, 'v260810.1', 22, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, NULL, NULL, NULL, 'v260810.1', 23, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES ('Strategic Initiative Campaign Launch', 'Corporate initiatives or CSS Sales Plays aligned to strategic priorities (AI, Multicloud, SaaS, etc.).', 'Launch Communication', 'GTM SME, Comms Review, Comms Plan', NULL, 'v260810.1', 24, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Target Data', 'GTM SME', NULL, 'v260810.1', 25, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Training Deck', 'GTM SME', NULL, 'v260810.1', 26, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Reporting', 'GTM SME', 'eg., update monthly Gov Package', 'v260810.1', 27, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Messaging', 'GTM SME', NULL, 'v260810.1', 28, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Sale sPlays', 'GTM SME', NULL, 'v260810.1', 29, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Customer Assets', 'GTM SME', NULL, 'v260810.1', 30, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Enablement Webinar', 'GTM SME, GTM Buddy', NULL, 'v260810.1', 31, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, NULL, NULL, NULL, 'v260810.1', 32, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES ('Enablement', 'Training and field readiness activities not directly tied to a launch.', 'Prepare for Live Session', 'GTM SME', NULL, 'v260810.1', 33, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Create recorded training', 'GTM SME', NULL, 'v260810.1', 34, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Create Training Deck', 'GTM', NULL, 'v260810.1', 35, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Post Replay Assets', 'GMT SME', NULL, 'v260810.1', 36, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Conduct Enablement Webinar', 'GTM SME, GTM Buddy', NULL, 'v260810.1', 37, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, NULL, NULL, NULL, 'v260810.1', 38, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES ('Executive Support', 'Executive requests and leadership communications.', 'Executive Decks', 'GTM SME, Comms Review, Comms Plan', NULL, 'v260810.1', 39, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'QBRs', 'GTM SME, Comms Review, Comms Plan', NULL, 'v260810.1', 40, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'All Hands Content', 'GTM SME, Comms Review, Comms Plan', NULL, 'v260810.1', 41, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Executive Messaging', 'GTM SME, Comms Review, Comms Plan', NULL, 'v260810.1', 42, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, NULL, NULL, NULL, 'v260810.1', 43, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES ('Customer Story', 'Development and promotion of customer success stories, references, and long story decks', 'Story Creation', 'GTM SME', NULL, 'v260810.1', 44, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Reference Content', 'GTM SME', NULL, 'v260810.1', 45, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Interviews', 'GTM SME', NULL, 'v260810.1', 46, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Videos', 'GTM SME', NULL, 'v260810.1', 47, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Amplification', 'GTM SME, Comms Review, Comms Plan', NULL, 'v260810.1', 48, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, NULL, NULL, NULL, 'v260810.1', 49, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES ('Use Case Content', 'Development of use case materials. Upload and maintain AI Use Cases artificats in AI Library/Innovation Portal.', 'Create AI Use Case Content', 'GTM SME', 'Exec 1-Pager, Demo Package, Videos (Hook and Demo)', 'v260810.1', 50, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Upload / Maintain AI Use Artifacts to AI Library / Innovation Portal', 'GTM SME', 'Exec 1-Pager, Demo Package, Videos (Hook and Demo)', 'v260810.1', 51, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Amplification', 'GTM SME, Comms Review, Comms Plan', NULL, 'v260810.1', 52, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, NULL, NULL, NULL, 'v260810.1', 53, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES ('Portal & Content Operations', 'Repository, Solution Matrix, SharePoint, and content management requests.', 'Portal Updates', 'GTM SME', NULL, 'v260810.1', 54, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Solution Matrix Administration', 'GTM SME', NULL, 'v260810.1', 55, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Asset Publishing', 'GTM SME', NULL, 'v260810.1', 56, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'File Management', 'GTM SME', NULL, 'v260810.1', 57, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, NULL, NULL, NULL, 'v260810.1', 58, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES ('Reporting', 'Create/update  leadership reporting.  Examples include:  Monthly Gov. Package, Target Data, Pipeline and Booking, Enablement Metrics, Stories, References, etc.', 'Pipeline and Booking', 'Comms, GTM SME', 'Dragos (primary); Indranie (support)', 'v260810.1', 59, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Target Data', 'GTM SME', 'e.g., Monthly Gov Package', 'v260810.1', 60, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, NULL, NULL, NULL, 'v260810.1', 61, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, NULL, NULL, NULL, 'v260810.1', 62, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, NULL, NULL, NULL, 'v260810.1', 63, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES ('Special Projects', 'Cross-functional initiatives that don''t fit into another category.', 'Research', 'GTM SME', NULL, 'v260810.1', 64, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Content Strategy', 'GTM SME', NULL, 'v260810.1', 65, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'COE Support', 'GTM SME', NULL, 'v260810.1', 66, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'AI World', 'GTM SME', 'e.g, Casey, Indranie, Dragos', 'v260810.1', 67, 'Yes')
  INTO CUSTOMER_MAPPING (projects, project_description, deliverables, skills_type_of_work, note, source_version, source_row, customer_controlled) VALUES (NULL, NULL, 'Process Improvement', 'GTM SME', NULL, 'v260810.1', 68, 'Yes')
SELECT 1 FROM DUAL;

PROMPT Loading draft operational configuration

PROMPT Loading draft eligibility rules: 4 rows
INSERT INTO ELIGIBILITY_RULES (rule_code, rule_name, rule_description, rule_type, rule_parameters_json, execution_order, rule_version, active_flag, effective_from)
VALUES ('REQUIRED_CAPABILITY', 'Required capability coverage', 'Candidate must cover the capabilities required by the request.', 'HARD', '{"requireAll":true,"minimumStrength":null}', 10, 'DRAFT_V1', 'N', TRUNC(SYSDATE));
INSERT INTO ELIGIBILITY_RULES (rule_code, rule_name, rule_description, rule_type, rule_parameters_json, execution_order, rule_version, active_flag, effective_from)
VALUES ('DATE_AVAILABILITY', 'Availability during request window', 'Candidate must not have a blocking availability event during the requested period.', 'HARD', '{"blockingEventTypes":["Leave","Travel"]}', 20, 'DRAFT_V1', 'N', TRUNC(SYSDATE));
INSERT INTO ELIGIBILITY_RULES (rule_code, rule_name, rule_description, rule_type, rule_parameters_json, execution_order, rule_version, active_flag, effective_from)
VALUES ('MAX_ALLOCATION', 'Maximum allocation', 'Candidate allocation must remain within the configured maximum.', 'HARD', '{"guardrailCode":"MAX_ALLOCATION_PCT"}', 30, 'DRAFT_V1', 'N', TRUNC(SYSDATE));
INSERT INTO ELIGIBILITY_RULES (rule_code, rule_name, rule_description, rule_type, rule_parameters_json, execution_order, rule_version, active_flag, effective_from)
VALUES ('MAX_ACTIVE_PODS', 'Maximum active pods', 'Candidate active-pod count must remain within the configured maximum.', 'HARD', '{"guardrailCode":"MAX_ACTIVE_PODS"}', 40, 'DRAFT_V1', 'N', TRUNC(SYSDATE));

PROMPT Loading draft load guardrails: 3 rows
INSERT INTO LOAD_GUARDRAILS (guardrail_code, guardrail_name, guardrail_value, guardrail_unit, applies_to_role, guardrail_version, active_flag, effective_from)
VALUES ('MAX_ALLOCATION_PCT', 'Maximum allocation percentage', 85, 'PERCENT', 'ALL', 'DRAFT_V1', 'N', TRUNC(SYSDATE));
INSERT INTO LOAD_GUARDRAILS (guardrail_code, guardrail_name, guardrail_value, guardrail_unit, applies_to_role, guardrail_version, active_flag, effective_from)
VALUES ('RESERVED_CAPACITY_PCT', 'Reserved operational capacity', 15, 'PERCENT', 'ALL', 'DRAFT_V1', 'N', TRUNC(SYSDATE));
INSERT INTO LOAD_GUARDRAILS (guardrail_code, guardrail_name, guardrail_value, guardrail_unit, applies_to_role, guardrail_version, active_flag, effective_from)
VALUES ('MAX_ACTIVE_PODS', 'Maximum active pods', 3, 'COUNT', 'ALL', 'DRAFT_V1', 'N', TRUNC(SYSDATE));

PROMPT Loading draft scoring weights: 5 rows
INSERT INTO SCORING_WEIGHTS (factor_code, factor_name, weight_pct, role_in_pod, weight_version, active_flag, effective_from)
VALUES ('INTEREST_STRENGTH', 'Interest strength', 35, 'ALL', 'DRAFT_V1', 'N', TRUNC(SYSDATE));
INSERT INTO SCORING_WEIGHTS (factor_code, factor_name, weight_pct, role_in_pod, weight_version, active_flag, effective_from)
VALUES ('DELIVERY_HISTORY', 'Relevant delivery history', 25, 'ALL', 'DRAFT_V1', 'N', TRUNC(SYSDATE));
INSERT INTO SCORING_WEIGHTS (factor_code, factor_name, weight_pct, role_in_pod, weight_version, active_flag, effective_from)
VALUES ('AVAILABLE_CAPACITY', 'Available capacity', 25, 'ALL', 'DRAFT_V1', 'N', TRUNC(SYSDATE));
INSERT INTO SCORING_WEIGHTS (factor_code, factor_name, weight_pct, role_in_pod, weight_version, active_flag, effective_from)
VALUES ('GROWTH_PREFERENCE', 'Growth preference', 10, 'ALL', 'DRAFT_V1', 'N', TRUNC(SYSDATE));
INSERT INTO SCORING_WEIGHTS (factor_code, factor_name, weight_pct, role_in_pod, weight_version, active_flag, effective_from)
VALUES ('TEAM_CONTINUITY', 'Team continuity', 5, 'ALL', 'DRAFT_V1', 'N', TRUNC(SYSDATE));


PROMPT Verifying installation
DECLARE
  l_actual      NUMBER;
  l_excel_total NUMBER := 0;
  l_weight_sum  NUMBER;

  PROCEDURE assert_count(p_table VARCHAR2, p_expected NUMBER, p_excel BOOLEAN DEFAULT TRUE) IS
  BEGIN
    EXECUTE IMMEDIATE 'SELECT COUNT(*) FROM ' || p_table INTO l_actual;
    IF l_actual <> p_expected THEN
      RAISE_APPLICATION_ERROR(-20010, p_table || ': expected ' || p_expected || ' rows but found ' || l_actual);
    END IF;
    IF p_excel THEN
      l_excel_total := l_excel_total + l_actual;
    END IF;
    DBMS_OUTPUT.PUT_LINE(RPAD(p_table, 26) || ' PASS  ' || l_actual || ' rows');
  END;
BEGIN
  assert_count('PROJECT_TYPES', 11);
  assert_count('INTERESTS', 13);
  assert_count('PEOPLE', 8);
  assert_count('DELIVERABLES', 55);
  assert_count('DELIVERABLE_SKILLS', 87);
  assert_count('PERSON_INTERESTS', 27);
  assert_count('AVAILABILITY', 4);
  assert_count('REQUESTS', 3);
  assert_count('REQUIREMENTS', 10);
  assert_count('RECOMMENDATIONS', 3);
  assert_count('CUSTOMER_MAPPING', 67);

  IF l_excel_total <> 288 THEN
    RAISE_APPLICATION_ERROR(-20011, 'Expected 288 Excel rows but found ' || l_excel_total);
  END IF;

  assert_count('ELIGIBILITY_RULES', 4, FALSE);
  assert_count('LOAD_GUARDRAILS', 3, FALSE);
  assert_count('SCORING_WEIGHTS', 5, FALSE);
  assert_count('AGENT_EXECUTIONS', 0, FALSE);
  assert_count('APPROVAL_DECISIONS', 0, FALSE);
  assert_count('POD_ASSIGNMENTS', 0, FALSE);
  assert_count('AUDIT_EVENTS', 0, FALSE);

  SELECT COUNT(*)
    INTO l_actual
    FROM USER_BLOCKCHAIN_TABLES
   WHERE TABLE_NAME = 'AUDIT_EVENTS';

  IF l_actual <> 1 THEN
    RAISE_APPLICATION_ERROR(-20013, 'AUDIT_EVENTS was not created as an Oracle blockchain table');
  END IF;
  DBMS_OUTPUT.PUT_LINE(RPAD('AUDIT_EVENTS TYPE', 26) || ' PASS  BLOCKCHAIN V2');

  SELECT SUM(weight_pct)
    INTO l_weight_sum
    FROM SCORING_WEIGHTS
   WHERE weight_version = 'DRAFT_V1'
     AND role_in_pod = 'ALL';

  IF l_weight_sum <> 100 THEN
    RAISE_APPLICATION_ERROR(-20012, 'DRAFT_V1 scoring weights must total 100; found ' || l_weight_sum);
  END IF;

  DBMS_OUTPUT.PUT_LINE('--------------------------------------------------');
  DBMS_OUTPUT.PUT_LINE('11 Excel-backed tables: 288 rows verified');
  DBMS_OUTPUT.PUT_LINE('7 operational tables: structure verified');
  DBMS_OUTPUT.PUT_LINE('12 draft policy/configuration rows verified');
  DBMS_OUTPUT.PUT_LINE('Draft policies remain inactive until business approval');
END;
/

COMMIT;

PROMPT ============================================================
PROMPT AI POD STAFFING DATABASE INSTALLATION COMPLETED SUCCESSFULLY
PROMPT 18 tables created
PROMPT 288 Excel rows loaded
PROMPT 12 draft configuration rows loaded (inactive)
PROMPT ============================================================
