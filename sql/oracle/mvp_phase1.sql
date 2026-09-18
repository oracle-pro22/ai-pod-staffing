-- Phase 1 additive schema only. Does not load accounts or change business/catalogue data.
-- Run as AI_POD_STAFFING in SQL Developer with F5. Oracle DDL auto-commits.
SET SERVEROUTPUT ON
SET DEFINE OFF
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK
DECLARE
  n NUMBER;
  PROCEDURE install(name VARCHAR2, ddl VARCHAR2) IS
  BEGIN
    SELECT COUNT(*) INTO n FROM user_objects WHERE object_name=name;
    IF n=0 THEN EXECUTE IMMEDIATE ddl; DBMS_OUTPUT.PUT_LINE('Created '||name);
    ELSE
      SELECT COUNT(*) INTO n FROM user_tables WHERE table_name=name;
      IF n<>1 THEN RAISE_APPLICATION_ERROR(-20001,'Unexpected existing object: '||name); END IF;
      DBMS_OUTPUT.PUT_LINE('Retained '||name||'; verify its schema before loading accounts.');
    END IF;
  END;
BEGIN
  IF USER<>'AI_POD_STAFFING' OR SYS_CONTEXT('USERENV','CURRENT_SCHEMA')<>'AI_POD_STAFFING' THEN
    RAISE_APPLICATION_ERROR(-20001,'Use AI_POD_STAFFING only.');
  END IF;
  EXECUTE IMMEDIATE 'ALTER SESSION DISABLE PARALLEL DDL';
  install('APP_ACCOUNTS',q'~CREATE TABLE app_accounts (
    account_id VARCHAR2(40) PRIMARY KEY,
    person_id VARCHAR2(30) NOT NULL UNIQUE REFERENCES people(person_id),
    identity_subject VARCHAR2(255) NOT NULL UNIQUE,
    login_email VARCHAR2(320) NOT NULL UNIQUE,
    password_hash VARCHAR2(255) NOT NULL,
    active_flag CHAR(1) DEFAULT 'Y' NOT NULL CHECK(active_flag IN ('Y','N')),
    failed_attempts NUMBER(3) DEFAULT 0 NOT NULL CHECK(failed_attempts BETWEEN 0 AND 4),
    locked_until TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    created_by VARCHAR2(255) NOT NULL,
    CONSTRAINT mp1_email CHECK(login_email=LOWER(TRIM(login_email)))
  )~');
  install('APP_SESSIONS',q'~CREATE TABLE app_sessions (
    token_hash VARCHAR2(64) PRIMARY KEY,
    account_id VARCHAR2(40) NOT NULL REFERENCES app_accounts(account_id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    revoked_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT mp1_session_dates CHECK(expires_at>created_at)
  )~');
  install('MVP_P1_ARCHIVE',q'~CREATE TABLE mvp_p1_archive (
    batch_id VARCHAR2(40) NOT NULL,
    table_name VARCHAR2(128) NOT NULL,
    row_key VARCHAR2(64) NOT NULL,
    row_json CLOB NOT NULL CHECK(row_json IS JSON),
    archived_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    operator_name VARCHAR2(255) NOT NULL,
    PRIMARY KEY(batch_id,table_name,row_key)
  )~');
  install('MVP_P1_RUNS',q'~CREATE TABLE mvp_p1_runs (
    batch_id VARCHAR2(40) PRIMARY KEY,
    manifest_hash VARCHAR2(64) NOT NULL,
    status VARCHAR2(16) NOT NULL CHECK(status IN ('PREPARED','APPLIED','RESTORED')),
    metadata_json CLOB NOT NULL CHECK(metadata_json IS JSON),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT SYSTIMESTAMP NOT NULL,
    operator_name VARCHAR2(255) NOT NULL
  )~');
  DBMS_OUTPUT.PUT_LINE('Schema prepared. Catalogue, people, roles, requests and runtime switches unchanged.');
END;
/
