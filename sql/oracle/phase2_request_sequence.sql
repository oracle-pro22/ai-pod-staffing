-- AI Pod Staffing Phase 2 prerequisite
-- Safe to run more than once while connected as AI_POD_STAFFING.

SET SERVEROUTPUT ON

DECLARE
  l_schema       VARCHAR2(128) := SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA');
  l_exists       NUMBER;
  l_max_request  NUMBER;
  l_start_with   NUMBER;
  l_last_number  NUMBER;
BEGIN
  IF l_schema <> 'AI_POD_STAFFING' THEN
    RAISE_APPLICATION_ERROR(-20001, 'Connect as AI_POD_STAFFING before running this script.');
  END IF;

  SELECT NVL(MAX(
           CASE
             WHEN REGEXP_LIKE(request_id, '^REQ-[0-9]+$')
             THEN TO_NUMBER(SUBSTR(request_id, 5))
           END
         ), 0)
    INTO l_max_request
    FROM requests;

  SELECT COUNT(*)
    INTO l_exists
    FROM user_sequences
   WHERE sequence_name = 'REQUEST_ID_SEQ';

  IF l_exists = 0 THEN
    l_start_with := GREATEST(l_max_request + 1, 1043);
    EXECUTE IMMEDIATE
      'CREATE SEQUENCE request_id_seq START WITH ' || TO_CHAR(l_start_with) ||
      ' INCREMENT BY 1 NOCACHE NOCYCLE';
    DBMS_OUTPUT.PUT_LINE('REQUEST_ID_SEQ created. Next request number: ' || l_start_with);
  ELSE
    SELECT last_number
      INTO l_last_number
      FROM user_sequences
     WHERE sequence_name = 'REQUEST_ID_SEQ';
    IF l_last_number <= l_max_request THEN
      RAISE_APPLICATION_ERROR(
        -20002,
        'REQUEST_ID_SEQ must be advanced above existing request number ' || l_max_request || '.'
      );
    END IF;
    DBMS_OUTPUT.PUT_LINE('REQUEST_ID_SEQ already exists and is safe. Next request number: ' || l_last_number);
  END IF;
END;
/
