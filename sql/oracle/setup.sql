-- ============================================================================
-- AI Pod Staffing - Fresh Oracle AI Database 26ai setup
-- File: setup.sql
-- Schema: AI_POD_STAFFING
--
-- Creates:
--   * 11 enhanced business tables based on the Excel model
--   * 3 application role-based access-control tables
--   * 288 original Excel rows
--   * 6 application roles and their screen permissions
--
-- Deliberately NOT created in this release:
--   ELIGIBILITY_RULES, LOAD_GUARDRAILS, SCORING_WEIGHTS,
--   AGENT_EXECUTIONS, APPROVAL_DECISIONS, POD_ASSIGNMENTS, AUDIT_EVENTS
--
-- Run in Oracle SQL Developer using F5 (Run Script).
-- Safety: this installer never drops, truncates, or overwrites a table.
-- ============================================================================

SET DEFINE OFF
SET SERVEROUTPUT ON SIZE UNLIMITED
SET SQLBLANKLINES ON
SET FEEDBACK ON
SET VERIFY OFF
WHENEVER OSERROR EXIT FAILURE ROLLBACK
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK

PROMPT ============================================================
PROMPT Starting AI Pod Staffing fresh setup
PROMPT Running schema and object safety checks

DECLARE
  l_existing NUMBER;
  l_session_user VARCHAR2(128);
  l_current_schema VARCHAR2(128);
BEGIN
  l_session_user := UPPER(SYS_CONTEXT('USERENV', 'SESSION_USER'));
  l_current_schema := UPPER(SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA'));

  IF l_session_user <> 'AI_POD_STAFFING' THEN
    RAISE_APPLICATION_ERROR(-20001,
      'Wrong session user. Expected AI_POD_STAFFING; found ' || l_session_user);
  END IF;

  IF l_current_schema <> 'AI_POD_STAFFING' THEN
    RAISE_APPLICATION_ERROR(-20002,
      'Wrong current schema. Expected AI_POD_STAFFING; found ' || l_current_schema);
  END IF;

  SELECT COUNT(DISTINCT OBJECT_NAME)
    INTO l_existing
    FROM USER_OBJECTS
   WHERE OBJECT_NAME IN (
     'PROJECT_TYPES', 'INTERESTS', 'PEOPLE', 'CUSTOMER_MAPPING',
     'DELIVERABLES', 'DELIVERABLE_SKILLS', 'PERSON_INTERESTS',
     'AVAILABILITY', 'REQUESTS', 'REQUIREMENTS', 'RECOMMENDATIONS',
     'APP_ROLES', 'ROLE_PERMISSIONS', 'APP_USER_ROLES',
     'ELIGIBILITY_RULES', 'LOAD_GUARDRAILS', 'SCORING_WEIGHTS',
     'AGENT_EXECUTIONS', 'APPROVAL_DECISIONS', 'POD_ASSIGNMENTS',
     'AUDIT_EVENTS'
   );

  IF l_existing > 0 THEN
    RAISE_APPLICATION_ERROR(-20003,
      'Setup stopped: ' || l_existing ||
      ' AI Pod table(s) already exist. No existing object was changed.');
  END IF;
END;
/

PROMPT Safety checks passed
PROMPT Creating the enhanced 11-table business model

CREATE TABLE PROJECT_TYPES (
  project_type_id     VARCHAR2(30)   NOT NULL,
  project_name        VARCHAR2(250)  NOT NULL,
  project_description VARCHAR2(2000) NOT NULL,
  source_version      VARCHAR2(40)   NOT NULL,
  source_row          NUMBER(10)     NOT NULL,
  CONSTRAINT pk_project_types PRIMARY KEY (project_type_id),
  CONSTRAINT uq_project_type_name UNIQUE (project_name)
);

CREATE TABLE INTERESTS (
  interest_id         VARCHAR2(30)  NOT NULL,
  interest_name       VARCHAR2(250) NOT NULL,
  category            VARCHAR2(150) NOT NULL,
  source              VARCHAR2(100) NOT NULL,
  source_version      VARCHAR2(40)  NOT NULL,
  customer_controlled VARCHAR2(3)   NOT NULL,
  CONSTRAINT pk_interests PRIMARY KEY (interest_id),
  CONSTRAINT uq_interest_name UNIQUE (interest_name),
  CONSTRAINT ck_int_customer CHECK (customer_controlled IN ('Yes', 'No'))
);

CREATE TABLE PEOPLE (
  person_id                 VARCHAR2(30)  NOT NULL,
  full_name                 VARCHAR2(250) NOT NULL,
  initials                  VARCHAR2(10)  NOT NULL,
  job_title                 VARCHAR2(250) NOT NULL,
  location                  VARCHAR2(150) NOT NULL,
  allocation_pct            NUMBER(5,2)   NOT NULL,
  active_pods               NUMBER(5)     NOT NULL,
  external_identity_subject VARCHAR2(255),
  email_address             VARCHAR2(320),
  active_flag               CHAR(1) DEFAULT 'Y' NOT NULL,
  created_at                TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
  updated_at                TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
  CONSTRAINT pk_people PRIMARY KEY (person_id),
  CONSTRAINT uq_people_identity UNIQUE (external_identity_subject),
  CONSTRAINT uq_people_email UNIQUE (email_address),
  CONSTRAINT ck_people_alloc CHECK (allocation_pct BETWEEN 0 AND 100),
  CONSTRAINT ck_people_pods CHECK (active_pods >= 0),
  CONSTRAINT ck_people_active CHECK (active_flag IN ('Y', 'N'))
);

CREATE TABLE CUSTOMER_MAPPING (
  projects            VARCHAR2(250),
  project_description VARCHAR2(2000),
  deliverables        VARCHAR2(500),
  skills_type_of_work VARCHAR2(1000),
  note                VARCHAR2(1000),
  source_version      VARCHAR2(40) NOT NULL,
  source_row          NUMBER(10)   NOT NULL,
  customer_controlled VARCHAR2(3)  NOT NULL,
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
    REFERENCES PROJECT_TYPES (project_type_id),
  CONSTRAINT uq_del_project_name UNIQUE (project_type_id, deliverable_name)
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
  availability_id NUMBER GENERATED BY DEFAULT ON NULL AS IDENTITY,
  person_id        VARCHAR2(30)  NOT NULL,
  event_type       VARCHAR2(60)  NOT NULL,
  starts_on        DATE          NOT NULL,
  ends_on          DATE          NOT NULL,
  title            VARCHAR2(500) NOT NULL,
  allocated_hours  NUMBER(10,2)  NOT NULL,
  created_by       VARCHAR2(128) DEFAULT USER NOT NULL,
  created_at       TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
  updated_at       TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
  CONSTRAINT pk_availability PRIMARY KEY (availability_id),
  CONSTRAINT uq_avail_event UNIQUE (person_id, event_type, starts_on, ends_on, title),
  CONSTRAINT fk_avail_person FOREIGN KEY (person_id)
    REFERENCES PEOPLE (person_id),
  CONSTRAINT ck_avail_dates CHECK (ends_on >= starts_on),
  CONSTRAINT ck_avail_hours CHECK (allocated_hours >= 0)
);

CREATE TABLE REQUESTS (
  request_id                   VARCHAR2(30)   NOT NULL,
  title                        VARCHAR2(500)  NOT NULL,
  project_type_id              VARCHAR2(30)   NOT NULL,
  project_type                 VARCHAR2(250)  NOT NULL,
  deliverable_id               VARCHAR2(30),
  deliverable                  VARCHAR2(500),
  deliverables_json            CLOB           NOT NULL,
  skills_type_of_work          VARCHAR2(1000),
  owner_name                   VARCHAR2(250)  NOT NULL,
  request_source               VARCHAR2(250)  NOT NULL,
  project_description          VARCHAR2(4000) NOT NULL,
  needed_by                    DATE           NOT NULL,
  estimated_start_date         DATE,
  estimated_completion_date    DATE,
  estimated_effort_value       NUMBER(10,2)  NOT NULL,
  estimated_effort_unit        VARCHAR2(20)  NOT NULL,
  estimated_hours              NUMBER(10,2)  NOT NULL,
  requested_lead_count         NUMBER(2),
  requested_contributor_count  NUMBER(2),
  priority                     VARCHAR2(30)  NOT NULL,
  status                       VARCHAR2(50)  NOT NULL,
  business_context             VARCHAR2(2000),
  business_objectives          CLOB          NOT NULL,
  expected_outcomes            CLOB,
  mapping_version              VARCHAR2(40)  NOT NULL,
  created_by                   VARCHAR2(128) DEFAULT USER NOT NULL,
  created_at                   TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
  updated_by                   VARCHAR2(128) DEFAULT USER NOT NULL,
  updated_at                   TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
  CONSTRAINT pk_requests PRIMARY KEY (request_id),
  CONSTRAINT fk_req_project_type FOREIGN KEY (project_type_id)
    REFERENCES PROJECT_TYPES (project_type_id),
  CONSTRAINT fk_req_deliverable FOREIGN KEY (deliverable_id)
    REFERENCES DELIVERABLES (deliverable_id),
  CONSTRAINT ck_req_deliverables_json CHECK (deliverables_json IS JSON),
  CONSTRAINT ck_req_effort CHECK (estimated_effort_value >= 0 AND estimated_hours >= 0),
  CONSTRAINT ck_req_effort_unit CHECK (estimated_effort_unit IN ('HOURS', 'DAYS', 'WEEKS', 'MONTHS')),
  CONSTRAINT ck_req_pod_counts CHECK (
    (requested_lead_count IS NULL OR requested_lead_count >= 0) AND
    (requested_contributor_count IS NULL OR requested_contributor_count >= 0)
  ),
  CONSTRAINT ck_req_priority CHECK (priority IN ('LOW', 'MEDIUM', 'HIGH')),
  CONSTRAINT ck_req_status CHECK (status IN ('DRAFT', 'NEEDS_RECOMMENDATION', 'IN_REVIEW', 'STAFFED', 'CLOSED')),
  CONSTRAINT ck_req_schedule CHECK (
    estimated_completion_date IS NULL OR estimated_start_date IS NULL OR
    estimated_completion_date >= estimated_start_date
  )
);

CREATE TABLE REQUIREMENTS (
  requirement_id         NUMBER GENERATED BY DEFAULT ON NULL AS IDENTITY,
  request_id             VARCHAR2(30)   NOT NULL,
  deliverable_id         VARCHAR2(30),
  interest_id            VARCHAR2(30),
  skill_name             VARCHAR2(500)  NOT NULL,
  custom_capability_name VARCHAR2(500),
  capability_source      VARCHAR2(30) DEFAULT 'MAPPED' NOT NULL,
  required_strength      NUMBER(3,1),
  display_order          NUMBER(5) DEFAULT 1 NOT NULL,
  requirement_source     VARCHAR2(250) NOT NULL,
  source_version         VARCHAR2(40)  NOT NULL,
  created_by             VARCHAR2(128) DEFAULT USER NOT NULL,
  created_at             TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
  CONSTRAINT pk_requirements PRIMARY KEY (requirement_id),
  CONSTRAINT fk_rq_request FOREIGN KEY (request_id)
    REFERENCES REQUESTS (request_id),
  CONSTRAINT fk_rq_deliverable FOREIGN KEY (deliverable_id)
    REFERENCES DELIVERABLES (deliverable_id),
  CONSTRAINT fk_rq_interest FOREIGN KEY (interest_id)
    REFERENCES INTERESTS (interest_id),
  CONSTRAINT ck_rq_strength CHECK (required_strength IS NULL OR required_strength BETWEEN 1 AND 5),
  CONSTRAINT ck_rq_source CHECK (capability_source IN ('MAPPED', 'CATALOGUE', 'CUSTOM')),
  CONSTRAINT ck_rq_capability CHECK (
    (capability_source = 'CUSTOM' AND interest_id IS NULL AND custom_capability_name IS NOT NULL) OR
    (capability_source IN ('MAPPED', 'CATALOGUE') AND interest_id IS NOT NULL AND custom_capability_name IS NULL)
  )
);

CREATE TABLE RECOMMENDATIONS (
  request_id                 VARCHAR2(30)   NOT NULL,
  person_id                  VARCHAR2(30)   NOT NULL,
  role_in_pod                VARCHAR2(100)  NOT NULL,
  score                      NUMBER(8,2)    NOT NULL,
  rank_position              NUMBER(5)      NOT NULL,
  rationale                  VARCHAR2(2000) NOT NULL,
  factor_breakdown_json      CLOB           NOT NULL,
  matching_capabilities_json CLOB           NOT NULL,
  selected_flag              CHAR(1) DEFAULT 'N' NOT NULL,
  decision_status            VARCHAR2(50)   NOT NULL,
  source                     VARCHAR2(100)  NOT NULL,
  generated_at               TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
  CONSTRAINT pk_recommendations PRIMARY KEY (request_id, person_id, role_in_pod),
  CONSTRAINT fk_rec_request FOREIGN KEY (request_id)
    REFERENCES REQUESTS (request_id),
  CONSTRAINT fk_rec_person FOREIGN KEY (person_id)
    REFERENCES PEOPLE (person_id),
  CONSTRAINT ck_rec_score CHECK (score BETWEEN 0 AND 100),
  CONSTRAINT ck_rec_rank CHECK (rank_position > 0),
  CONSTRAINT ck_rec_selected CHECK (selected_flag IN ('Y', 'N')),
  CONSTRAINT ck_rec_factors_json CHECK (factor_breakdown_json IS JSON),
  CONSTRAINT ck_rec_caps_json CHECK (matching_capabilities_json IS JSON)
);

PROMPT Creating application role-based access-control tables

CREATE TABLE APP_ROLES (
  role_code        VARCHAR2(40)   NOT NULL,
  role_name        VARCHAR2(100)  NOT NULL,
  role_description VARCHAR2(1000),
  active_flag      CHAR(1) DEFAULT 'Y' NOT NULL,
  created_at       TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
  CONSTRAINT pk_app_roles PRIMARY KEY (role_code),
  CONSTRAINT uq_app_role_name UNIQUE (role_name),
  CONSTRAINT ck_app_role_active CHECK (active_flag IN ('Y', 'N'))
);

CREATE TABLE ROLE_PERMISSIONS (
  role_code       VARCHAR2(40) NOT NULL,
  resource_code   VARCHAR2(60) NOT NULL,
  access_scope    VARCHAR2(20) NOT NULL,
  can_view        CHAR(1) DEFAULT 'N' NOT NULL,
  can_create      CHAR(1) DEFAULT 'N' NOT NULL,
  can_update      CHAR(1) DEFAULT 'N' NOT NULL,
  can_approve     CHAR(1) DEFAULT 'N' NOT NULL,
  can_export      CHAR(1) DEFAULT 'N' NOT NULL,
  can_administer  CHAR(1) DEFAULT 'N' NOT NULL,
  CONSTRAINT pk_role_permissions PRIMARY KEY (role_code, resource_code),
  CONSTRAINT fk_rp_role FOREIGN KEY (role_code)
    REFERENCES APP_ROLES (role_code),
  CONSTRAINT ck_rp_scope CHECK (access_scope IN ('FULL', 'SCOPED', 'OWN', 'LOCKED')),
  CONSTRAINT ck_rp_flags CHECK (
    can_view IN ('Y', 'N') AND can_create IN ('Y', 'N') AND
    can_update IN ('Y', 'N') AND can_approve IN ('Y', 'N') AND
    can_export IN ('Y', 'N') AND can_administer IN ('Y', 'N')
  ),
  CONSTRAINT ck_rp_locked CHECK (
    access_scope <> 'LOCKED' OR
    (can_view = 'N' AND can_create = 'N' AND can_update = 'N' AND
     can_approve = 'N' AND can_export = 'N' AND can_administer = 'N')
  )
);

CREATE TABLE APP_USER_ROLES (
  identity_subject VARCHAR2(255) NOT NULL,
  role_code        VARCHAR2(40)  NOT NULL,
  person_id        VARCHAR2(30),
  active_flag      CHAR(1) DEFAULT 'Y' NOT NULL,
  effective_from   DATE DEFAULT TRUNC(SYSDATE) NOT NULL,
  effective_to     DATE,
  assigned_by      VARCHAR2(128) DEFAULT USER NOT NULL,
  assigned_at      TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
  CONSTRAINT pk_app_user_roles PRIMARY KEY (identity_subject, role_code),
  CONSTRAINT fk_aur_role FOREIGN KEY (role_code)
    REFERENCES APP_ROLES (role_code),
  CONSTRAINT fk_aur_person FOREIGN KEY (person_id)
    REFERENCES PEOPLE (person_id),
  CONSTRAINT ck_aur_active CHECK (active_flag IN ('Y', 'N')),
  CONSTRAINT ck_aur_dates CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

PROMPT Creating query indexes

CREATE INDEX idx_del_project_type ON DELIVERABLES (project_type_id);
CREATE INDEX idx_ds_skill ON DELIVERABLE_SKILLS (skill_id);
CREATE INDEX idx_pi_interest ON PERSON_INTERESTS (interest_id);
CREATE INDEX idx_avail_person_dates ON AVAILABILITY (person_id, starts_on, ends_on);
CREATE INDEX idx_req_project ON REQUESTS (project_type_id);
CREATE INDEX idx_req_status_priority ON REQUESTS (status, priority);
CREATE INDEX idx_req_needed_by ON REQUESTS (needed_by);
CREATE INDEX idx_rq_request ON REQUIREMENTS (request_id);
CREATE INDEX idx_rq_interest ON REQUIREMENTS (interest_id);
CREATE INDEX idx_rec_request_score ON RECOMMENDATIONS (request_id, score DESC);
CREATE INDEX idx_rp_resource ON ROLE_PERMISSIONS (resource_code);
CREATE INDEX idx_aur_person ON APP_USER_ROLES (person_id);

PROMPT All 14 current-scope tables created

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
-- Keep these as separate statements. In an Oracle multi-table INSERT ALL, an
-- identity default can be evaluated once for the source row and reused by all
-- INTO clauses, which would give every availability row the same primary key.
INSERT INTO AVAILABILITY (person_id, event_type, starts_on, ends_on, title, allocated_hours)
VALUES ('P-005', 'Travel', DATE '2026-07-28', DATE '2026-07-30', 'Customer workshop', 24);

INSERT INTO AVAILABILITY (person_id, event_type, starts_on, ends_on, title, allocated_hours)
VALUES ('P-002', 'Travel', DATE '2026-07-23', DATE '2026-07-23', 'Production travel', 8);

INSERT INTO AVAILABILITY (person_id, event_type, starts_on, ends_on, title, allocated_hours)
VALUES ('P-006', 'Commitment', DATE '2026-07-24', DATE '2026-07-24', 'AI adoption video', 8);

INSERT INTO AVAILABILITY (person_id, event_type, starts_on, ends_on, title, allocated_hours)
VALUES ('P-007', 'Commitment', DATE '2026-07-21', DATE '2026-07-21', 'Video edit review', 6);

PROMPT Loading Requests: 3 rows with frontend-compatible fields
INSERT ALL
  INTO REQUESTS (
    request_id, title, project_type_id, project_type, deliverable_id, deliverable,
    deliverables_json, skills_type_of_work, owner_name, request_source,
    project_description, needed_by, estimated_start_date, estimated_completion_date,
    estimated_effort_value, estimated_effort_unit, estimated_hours,
    requested_lead_count, requested_contributor_count, priority, status,
    business_context, business_objectives, expected_outcomes, mapping_version,
    created_by, updated_by
  ) VALUES (
    'REQ-1042', 'AI service launch communication', 'PT-001', 'New Service Launch',
    'DEL-005', 'Launch Communication',
    q'~[{"deliverableId":"DEL-005","name":"Launch Communication","note":"","custom":false}]~',
    'GTM SME, Comms Review, Comms Plan', 'Amy Lawrence', 'Amy Lawrence',
    'New service launch (EA or GA) requiring GTM readiness and supporting assets.',
    DATE '2026-08-07', NULL, NULL, 72, 'HOURS', 72, NULL, NULL,
    'HIGH', 'NEEDS_RECOMMENDATION',
    'New service launch (EA or GA) requiring GTM readiness and supporting assets.',
    'New service launch (EA or GA) requiring GTM readiness and supporting assets.',
    NULL, 'v260810.1', 'EXCEL_IMPORT', 'EXCEL_IMPORT'
  )
  INTO REQUESTS (
    request_id, title, project_type_id, project_type, deliverable_id, deliverable,
    deliverables_json, skills_type_of_work, owner_name, request_source,
    project_description, needed_by, estimated_start_date, estimated_completion_date,
    estimated_effort_value, estimated_effort_unit, estimated_hours,
    requested_lead_count, requested_contributor_count, priority, status,
    business_context, business_objectives, expected_outcomes, mapping_version,
    created_by, updated_by
  ) VALUES (
    'REQ-1041', 'Customer AI demo package', 'PT-003', 'Demo Package',
    'DEL-019', 'Demo video',
    q'~[{"deliverableId":"DEL-019","name":"Demo video","note":"","custom":false}]~',
    'Script writer (GTM SME), Comms Review, narration audio, visual asset, video creation',
    'Rohan Shah', 'Rohan Shah',
    'External content to promote AI use cases (OCAB style). Demo package target audience is Customers, Sales, Executives.',
    DATE '2026-08-03', NULL, NULL, 48, 'HOURS', 48, NULL, NULL,
    'HIGH', 'IN_REVIEW',
    'External content to promote AI use cases (OCAB style). Demo package target audience is Customers, Sales, Executives.',
    'Create a polished external demo package for customers, sales, and executive audiences.',
    NULL, 'v260810.1', 'EXCEL_IMPORT', 'EXCEL_IMPORT'
  )
  INTO REQUESTS (
    request_id, title, project_type_id, project_type, deliverable_id, deliverable,
    deliverables_json, skills_type_of_work, owner_name, request_source,
    project_description, needed_by, estimated_start_date, estimated_completion_date,
    estimated_effort_value, estimated_effort_unit, estimated_hours,
    requested_lead_count, requested_contributor_count, priority, status,
    business_context, business_objectives, expected_outcomes, mapping_version,
    created_by, updated_by
  ) VALUES (
    'REQ-1039', 'Partner enablement webinar', 'PT-005', 'Enablement',
    'DEL-032', 'Conduct Enablement Webinar',
    q'~[{"deliverableId":"DEL-032","name":"Conduct Enablement Webinar","note":"","custom":false}]~',
    'GTM SME, GTM Buddy', 'Marta Ruiz', 'Marta Ruiz',
    'Training and field readiness activities not directly tied to a launch.',
    DATE '2026-08-14', NULL, NULL, 64, 'HOURS', 64, NULL, NULL,
    'MEDIUM', 'STAFFED',
    'Training and field readiness activities not directly tied to a launch.',
    'Prepare partners for effective field execution through a structured enablement webinar.',
    NULL, 'v260810.1', 'EXCEL_IMPORT', 'EXCEL_IMPORT'
  )
SELECT 1 FROM DUAL;

PROMPT Loading Requirements: 10 rows
-- REQUIREMENT_ID is also identity-backed, so use one statement per row for the
-- same reason as AVAILABILITY above.
INSERT INTO REQUIREMENTS (request_id, deliverable_id, interest_id, skill_name, required_strength, display_order, requirement_source, source_version)
VALUES ('REQ-1042', 'DEL-005', 'SK-002', 'GTM SME', NULL, 1, 'Customer Mapping', 'v260810.1');

INSERT INTO REQUIREMENTS (request_id, deliverable_id, interest_id, skill_name, required_strength, display_order, requirement_source, source_version)
VALUES ('REQ-1042', 'DEL-005', 'SK-003', 'Comms Review', NULL, 2, 'Customer Mapping', 'v260810.1');

INSERT INTO REQUIREMENTS (request_id, deliverable_id, interest_id, skill_name, required_strength, display_order, requirement_source, source_version)
VALUES ('REQ-1042', 'DEL-005', 'SK-004', 'Comms Plan', NULL, 3, 'Customer Mapping', 'v260810.1');

INSERT INTO REQUIREMENTS (request_id, deliverable_id, interest_id, skill_name, required_strength, display_order, requirement_source, source_version)
VALUES ('REQ-1041', 'DEL-019', 'SK-007', 'Script writer (GTM SME)', NULL, 1, 'Customer Mapping', 'v260810.1');

INSERT INTO REQUIREMENTS (request_id, deliverable_id, interest_id, skill_name, required_strength, display_order, requirement_source, source_version)
VALUES ('REQ-1041', 'DEL-019', 'SK-003', 'Comms Review', NULL, 2, 'Customer Mapping', 'v260810.1');

INSERT INTO REQUIREMENTS (request_id, deliverable_id, interest_id, skill_name, required_strength, display_order, requirement_source, source_version)
VALUES ('REQ-1041', 'DEL-019', 'SK-008', 'narration audio', NULL, 3, 'Customer Mapping', 'v260810.1');

INSERT INTO REQUIREMENTS (request_id, deliverable_id, interest_id, skill_name, required_strength, display_order, requirement_source, source_version)
VALUES ('REQ-1041', 'DEL-019', 'SK-009', 'visual asset', NULL, 4, 'Customer Mapping', 'v260810.1');

INSERT INTO REQUIREMENTS (request_id, deliverable_id, interest_id, skill_name, required_strength, display_order, requirement_source, source_version)
VALUES ('REQ-1041', 'DEL-019', 'SK-010', 'video creation', NULL, 5, 'Customer Mapping', 'v260810.1');

INSERT INTO REQUIREMENTS (request_id, deliverable_id, interest_id, skill_name, required_strength, display_order, requirement_source, source_version)
VALUES ('REQ-1039', 'DEL-032', 'SK-002', 'GTM SME', NULL, 1, 'Customer Mapping', 'v260810.1');

INSERT INTO REQUIREMENTS (request_id, deliverable_id, interest_id, skill_name, required_strength, display_order, requirement_source, source_version)
VALUES ('REQ-1039', 'DEL-032', 'SK-006', 'GTM Buddy', NULL, 2, 'Customer Mapping', 'v260810.1');

PROMPT Loading Recommendations: 3 rows with frontend evidence
INSERT ALL
  INTO RECOMMENDATIONS (
    request_id, person_id, role_in_pod, score, rank_position, rationale,
    factor_breakdown_json, matching_capabilities_json, selected_flag,
    decision_status, source
  ) VALUES (
    'REQ-1042', 'P-006', 'Pod lead', 94, 1,
    'Covers GTM SME, Comms Review and Comms Plan with strong launch coordination evidence.',
    q'~[{"factorCode":"INTEREST_STRENGTH","factorName":"Interest strength","weightPct":35,"evidenceScore":92},{"factorCode":"DELIVERY_HISTORY","factorName":"Relevant delivery history","weightPct":25,"evidenceScore":84},{"factorCode":"AVAILABLE_CAPACITY","factorName":"Available capacity","weightPct":25,"evidenceScore":76},{"factorCode":"GROWTH_PREFERENCE","factorName":"Growth preference","weightPct":10,"evidenceScore":61},{"factorCode":"TEAM_CONTINUITY","factorName":"Team continuity","weightPct":5,"evidenceScore":48}]~',
    q'~["GTM SME","Comms Review","Comms Plan"]~', 'N', 'Pending review', 'Prototype/Demo'
  )
  INTO RECOMMENDATIONS (
    request_id, person_id, role_in_pod, score, rank_position, rationale,
    factor_breakdown_json, matching_capabilities_json, selected_flag,
    decision_status, source
  ) VALUES (
    'REQ-1042', 'P-001', 'Contributor', 89, 1,
    'Strong GTM SME and Comms Plan evidence for customer-facing launch messaging.',
    q'~[{"factorCode":"INTEREST_STRENGTH","factorName":"Interest strength","weightPct":35,"evidenceScore":88},{"factorCode":"DELIVERY_HISTORY","factorName":"Relevant delivery history","weightPct":25,"evidenceScore":82},{"factorCode":"AVAILABLE_CAPACITY","factorName":"Available capacity","weightPct":25,"evidenceScore":70},{"factorCode":"GROWTH_PREFERENCE","factorName":"Growth preference","weightPct":10,"evidenceScore":68},{"factorCode":"TEAM_CONTINUITY","factorName":"Team continuity","weightPct":5,"evidenceScore":55}]~',
    q'~["GTM SME","Comms Plan"]~', 'N', 'Pending review', 'Prototype/Demo'
  )
  INTO RECOMMENDATIONS (
    request_id, person_id, role_in_pod, score, rank_position, rationale,
    factor_breakdown_json, matching_capabilities_json, selected_flag,
    decision_status, source
  ) VALUES (
    'REQ-1042', 'P-005', 'Contributor', 86, 2,
    'Provides Comms Review and Comms Plan coverage for the launch communication deliverable.',
    q'~[{"factorCode":"INTEREST_STRENGTH","factorName":"Interest strength","weightPct":35,"evidenceScore":85},{"factorCode":"DELIVERY_HISTORY","factorName":"Relevant delivery history","weightPct":25,"evidenceScore":78},{"factorCode":"AVAILABLE_CAPACITY","factorName":"Available capacity","weightPct":25,"evidenceScore":66},{"factorCode":"GROWTH_PREFERENCE","factorName":"Growth preference","weightPct":10,"evidenceScore":63},{"factorCode":"TEAM_CONTINUITY","factorName":"Team continuity","weightPct":5,"evidenceScore":58}]~',
    q'~["Comms Review","Comms Plan"]~', 'N', 'Pending review', 'Prototype/Demo'
  )
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

PROMPT Loading application roles and screen permissions
INSERT ALL
  INTO APP_ROLES (role_code, role_name, role_description) VALUES ('OPERATIONS_LEAD', 'Operations Lead', 'Full operational staffing oversight and administration.')
  INTO APP_ROLES (role_code, role_name, role_description) VALUES ('REQUEST_LEAD', 'Request Lead', 'Creates and manages requests, fitment review, allocation, and reporting.')
  INTO APP_ROLES (role_code, role_name, role_description) VALUES ('POD_LEAD', 'Pod Lead', 'Scoped access to assigned requests, recommendations, profiles, and own availability.')
  INTO APP_ROLES (role_code, role_name, role_description) VALUES ('POD_MEMBER', 'POD Member', 'Own and scoped access to assignments, capability profile, and availability.')
  INTO APP_ROLES (role_code, role_name, role_description) VALUES ('EXECUTIVE', 'Executive', 'Read-only command-center, request, and report access.')
  INTO APP_ROLES (role_code, role_name, role_description) VALUES ('SYSTEM_ADMINISTRATOR', 'System Administrator', 'Full application and access administration.')
SELECT 1 FROM DUAL;

INSERT ALL
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('OPERATIONS_LEAD', 'DASHBOARD', 'FULL', 'Y', 'N', 'N', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('OPERATIONS_LEAD', 'REQUESTS', 'FULL', 'Y', 'Y', 'Y', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('OPERATIONS_LEAD', 'AI_FITMENT', 'FULL', 'Y', 'Y', 'Y', 'Y', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('OPERATIONS_LEAD', 'ALLOCATION_CALENDAR', 'FULL', 'Y', 'Y', 'Y', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('OPERATIONS_LEAD', 'TEAM_SKILLS', 'FULL', 'Y', 'Y', 'Y', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('OPERATIONS_LEAD', 'MY_AVAILABILITY', 'OWN', 'Y', 'Y', 'Y', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('OPERATIONS_LEAD', 'AGENT_EXECUTION', 'FULL', 'Y', 'Y', 'Y', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('OPERATIONS_LEAD', 'REPORTS', 'FULL', 'Y', 'N', 'N', 'N', 'Y', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('OPERATIONS_LEAD', 'ADMINISTRATION', 'FULL', 'Y', 'Y', 'Y', 'Y', 'Y', 'Y')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('REQUEST_LEAD', 'DASHBOARD', 'FULL', 'Y', 'N', 'N', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('REQUEST_LEAD', 'REQUESTS', 'FULL', 'Y', 'Y', 'Y', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('REQUEST_LEAD', 'AI_FITMENT', 'FULL', 'Y', 'Y', 'Y', 'Y', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('REQUEST_LEAD', 'ALLOCATION_CALENDAR', 'FULL', 'Y', 'Y', 'Y', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('REQUEST_LEAD', 'TEAM_SKILLS', 'FULL', 'Y', 'N', 'N', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('REQUEST_LEAD', 'MY_AVAILABILITY', 'OWN', 'Y', 'Y', 'Y', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('REQUEST_LEAD', 'AGENT_EXECUTION', 'FULL', 'Y', 'Y', 'N', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('REQUEST_LEAD', 'REPORTS', 'FULL', 'Y', 'N', 'N', 'N', 'Y', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('REQUEST_LEAD', 'ADMINISTRATION', 'LOCKED', 'N', 'N', 'N', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('POD_LEAD', 'DASHBOARD', 'SCOPED', 'Y', 'N', 'N', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('POD_LEAD', 'REQUESTS', 'SCOPED', 'Y', 'Y', 'Y', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('POD_LEAD', 'AI_FITMENT', 'SCOPED', 'Y', 'Y', 'Y', 'Y', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('POD_LEAD', 'ALLOCATION_CALENDAR', 'LOCKED', 'N', 'N', 'N', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('POD_LEAD', 'TEAM_SKILLS', 'SCOPED', 'Y', 'N', 'N', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('POD_LEAD', 'MY_AVAILABILITY', 'OWN', 'Y', 'Y', 'Y', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('POD_LEAD', 'AGENT_EXECUTION', 'LOCKED', 'N', 'N', 'N', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('POD_LEAD', 'REPORTS', 'LOCKED', 'N', 'N', 'N', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('POD_LEAD', 'ADMINISTRATION', 'LOCKED', 'N', 'N', 'N', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('POD_MEMBER', 'DASHBOARD', 'SCOPED', 'Y', 'N', 'N', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('POD_MEMBER', 'REQUESTS', 'SCOPED', 'Y', 'N', 'N', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('POD_MEMBER', 'AI_FITMENT', 'OWN', 'Y', 'N', 'N', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('POD_MEMBER', 'ALLOCATION_CALENDAR', 'LOCKED', 'N', 'N', 'N', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('POD_MEMBER', 'TEAM_SKILLS', 'OWN', 'Y', 'N', 'N', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('POD_MEMBER', 'MY_AVAILABILITY', 'OWN', 'Y', 'Y', 'Y', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('POD_MEMBER', 'AGENT_EXECUTION', 'LOCKED', 'N', 'N', 'N', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('POD_MEMBER', 'REPORTS', 'LOCKED', 'N', 'N', 'N', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('POD_MEMBER', 'ADMINISTRATION', 'LOCKED', 'N', 'N', 'N', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('EXECUTIVE', 'DASHBOARD', 'FULL', 'Y', 'N', 'N', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('EXECUTIVE', 'REQUESTS', 'FULL', 'Y', 'N', 'N', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('EXECUTIVE', 'AI_FITMENT', 'LOCKED', 'N', 'N', 'N', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('EXECUTIVE', 'ALLOCATION_CALENDAR', 'LOCKED', 'N', 'N', 'N', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('EXECUTIVE', 'TEAM_SKILLS', 'LOCKED', 'N', 'N', 'N', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('EXECUTIVE', 'MY_AVAILABILITY', 'LOCKED', 'N', 'N', 'N', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('EXECUTIVE', 'AGENT_EXECUTION', 'LOCKED', 'N', 'N', 'N', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('EXECUTIVE', 'REPORTS', 'FULL', 'Y', 'N', 'N', 'N', 'Y', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('EXECUTIVE', 'ADMINISTRATION', 'LOCKED', 'N', 'N', 'N', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('SYSTEM_ADMINISTRATOR', 'DASHBOARD', 'FULL', 'Y', 'N', 'N', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('SYSTEM_ADMINISTRATOR', 'REQUESTS', 'FULL', 'Y', 'Y', 'Y', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('SYSTEM_ADMINISTRATOR', 'AI_FITMENT', 'FULL', 'Y', 'Y', 'Y', 'Y', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('SYSTEM_ADMINISTRATOR', 'ALLOCATION_CALENDAR', 'FULL', 'Y', 'Y', 'Y', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('SYSTEM_ADMINISTRATOR', 'TEAM_SKILLS', 'FULL', 'Y', 'Y', 'Y', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('SYSTEM_ADMINISTRATOR', 'MY_AVAILABILITY', 'FULL', 'Y', 'Y', 'Y', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('SYSTEM_ADMINISTRATOR', 'AGENT_EXECUTION', 'FULL', 'Y', 'Y', 'Y', 'N', 'N', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('SYSTEM_ADMINISTRATOR', 'REPORTS', 'FULL', 'Y', 'N', 'N', 'N', 'Y', 'N')
  INTO ROLE_PERMISSIONS (role_code, resource_code, access_scope, can_view, can_create, can_update, can_approve, can_export, can_administer) VALUES ('SYSTEM_ADMINISTRATOR', 'ADMINISTRATION', 'FULL', 'Y', 'Y', 'Y', 'Y', 'Y', 'Y')
SELECT 1 FROM DUAL;

PROMPT APP_USER_ROLES intentionally starts empty
PROMPT Add real OCI identity-subject mappings after identity integration.

PROMPT Verifying table structure and loaded data

DECLARE
  l_actual NUMBER;
  l_excel_total NUMBER := 0;
  l_held_count NUMBER;

  PROCEDURE assert_count(p_table VARCHAR2, p_expected NUMBER, p_excel BOOLEAN DEFAULT TRUE) IS
  BEGIN
    EXECUTE IMMEDIATE 'SELECT COUNT(*) FROM ' || DBMS_ASSERT.SIMPLE_SQL_NAME(p_table)
      INTO l_actual;
    IF l_actual <> p_expected THEN
      RAISE_APPLICATION_ERROR(-20100,
        p_table || ': expected ' || p_expected || ' rows; found ' || l_actual);
    END IF;
    IF p_excel THEN
      l_excel_total := l_excel_total + l_actual;
    END IF;
    DBMS_OUTPUT.PUT_LINE(RPAD(p_table, 26) || ' PASS  ' || l_actual || ' rows');
  END;
BEGIN
  SELECT COUNT(*) INTO l_actual
    FROM USER_TABLES
   WHERE TABLE_NAME IN (
     'PROJECT_TYPES', 'INTERESTS', 'PEOPLE', 'CUSTOMER_MAPPING',
     'DELIVERABLES', 'DELIVERABLE_SKILLS', 'PERSON_INTERESTS',
     'AVAILABILITY', 'REQUESTS', 'REQUIREMENTS', 'RECOMMENDATIONS',
     'APP_ROLES', 'ROLE_PERMISSIONS', 'APP_USER_ROLES'
   );

  IF l_actual <> 14 THEN
    RAISE_APPLICATION_ERROR(-20101,
      'Expected 14 current-scope tables; found ' || l_actual);
  END IF;

  SELECT COUNT(*) INTO l_held_count
    FROM USER_TABLES
   WHERE TABLE_NAME IN (
     'ELIGIBILITY_RULES', 'LOAD_GUARDRAILS', 'SCORING_WEIGHTS',
     'AGENT_EXECUTIONS', 'APPROVAL_DECISIONS', 'POD_ASSIGNMENTS',
     'AUDIT_EVENTS'
   );

  IF l_held_count <> 0 THEN
    RAISE_APPLICATION_ERROR(-20102,
      'One or more held operational/governance tables unexpectedly exist.');
  END IF;

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
    RAISE_APPLICATION_ERROR(-20103,
      'Expected 288 Excel rows; found ' || l_excel_total);
  END IF;

  assert_count('APP_ROLES', 6, FALSE);
  assert_count('ROLE_PERMISSIONS', 54, FALSE);
  assert_count('APP_USER_ROLES', 0, FALSE);

  SELECT COUNT(*) INTO l_actual
    FROM REQUESTS
   WHERE deliverables_json IS JSON
     AND estimated_effort_unit IN ('HOURS', 'DAYS', 'WEEKS', 'MONTHS')
     AND priority IN ('LOW', 'MEDIUM', 'HIGH')
     AND status IN ('DRAFT', 'NEEDS_RECOMMENDATION', 'IN_REVIEW', 'STAFFED', 'CLOSED');
  IF l_actual <> 3 THEN
    RAISE_APPLICATION_ERROR(-20104,
      'Frontend request-field verification failed.');
  END IF;

  SELECT COUNT(*) INTO l_actual
    FROM RECOMMENDATIONS
   WHERE factor_breakdown_json IS JSON
     AND matching_capabilities_json IS JSON;
  IF l_actual <> 3 THEN
    RAISE_APPLICATION_ERROR(-20105,
      'Recommendation JSON verification failed.');
  END IF;

  DBMS_OUTPUT.PUT_LINE('--------------------------------------------------');
  DBMS_OUTPUT.PUT_LINE('14 current-scope tables verified');
  DBMS_OUTPUT.PUT_LINE('11 enhanced business tables contain 288 Excel rows');
  DBMS_OUTPUT.PUT_LINE('3 RBAC tables contain 6 roles and 54 permissions');
  DBMS_OUTPUT.PUT_LINE('7 operational/governance tables remain on hold');
END;
/

COMMIT;

PROMPT ============================================================
PROMPT AI POD STAFFING SETUP COMPLETED SUCCESSFULLY
PROMPT 11 enhanced business tables created
PROMPT 3 RBAC tables created
PROMPT 288 Excel rows loaded
PROMPT 6 roles and 54 screen permissions loaded
PROMPT 7 operational/governance tables not created
PROMPT ============================================================
