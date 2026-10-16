-- Run with F5 as AI_POD_STAFFING. Additive; reruns preserve all saved notes.
-- Oracle DDL commits implicitly. This script does not modify staffing data or permissions.
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK
SET SERVEROUTPUT ON
DECLARE
  n NUMBER;
BEGIN
  IF USER <> 'AI_POD_STAFFING'
     OR SYS_CONTEXT('USERENV','SESSION_USER') <> 'AI_POD_STAFFING'
     OR SYS_CONTEXT('USERENV','CURRENT_SCHEMA') <> 'AI_POD_STAFFING' THEN
    RAISE_APPLICATION_ERROR(-20370, 'Run as AI_POD_STAFFING in its own schema.');
  END IF;
  SELECT COUNT(*) INTO n FROM user_tables WHERE table_name='ADMIN_ENHANCEMENT_NOTES';
  IF n=0 THEN
    EXECUTE IMMEDIATE 'CREATE TABLE admin_enhancement_notes (
      document_id NUMBER(1) PRIMARY KEY CHECK (document_id=1),
      content CLOB DEFAULT EMPTY_CLOB() NOT NULL,
      revision NUMBER(10) DEFAULT 1 NOT NULL CHECK (revision>=1),
      updated_by_person_id VARCHAR2(64),
      updated_by_name VARCHAR2(1000),
      updated_at TIMESTAMP WITH TIME ZONE)';
  END IF;
  SELECT COUNT(*) INTO n FROM user_tab_columns WHERE table_name='ADMIN_ENHANCEMENT_NOTES'
    AND ((column_name='DOCUMENT_ID' AND data_type='NUMBER')
      OR (column_name='CONTENT' AND data_type='CLOB')
      OR (column_name='REVISION' AND data_type='NUMBER')
      OR (column_name='UPDATED_BY_PERSON_ID' AND data_type='VARCHAR2')
      OR (column_name='UPDATED_BY_NAME' AND data_type='VARCHAR2')
      OR (column_name='UPDATED_AT' AND data_type LIKE 'TIMESTAMP%WITH TIME ZONE'));
  IF n<>6 THEN
    RAISE_APPLICATION_ERROR(-20371, 'Unexpected enhancement notepad schema. No existing notes overwritten.');
  END IF;
  EXECUTE IMMEDIATE 'MERGE INTO admin_enhancement_notes target
    USING (SELECT 1 document_id FROM dual) source ON (target.document_id=source.document_id)
    WHEN NOT MATCHED THEN INSERT (document_id,content,revision) VALUES (1,EMPTY_CLOB(),1)';
  COMMIT;
  DBMS_OUTPUT.PUT_LINE('Shared enhancement notepad installed. Existing notes preserved.');
END;
/
SELECT document_id,revision,DBMS_LOB.GETLENGTH(content) content_length,updated_at
FROM admin_enhancement_notes WHERE document_id=1;
