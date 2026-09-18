"""Read-only Phase 3 verification. Does not enable agents or apply DDL."""
import argparse
import json
from app.errors import ServiceError
from app.selection_schema import normalized, verify as verify_phase2
from app.storage import rows

TABLES = {
 'MVP_P3_DRAFTS': {'DRAFT_ID': ('VARCHAR2',30,'N'), 'REQUEST_ID': ('VARCHAR2',30,'N'),
    'REQUEST_REVISION': ('NUMBER',10,'N'), 'REVISION': ('NUMBER',10,'N'), 'POLICY_VERSION': ('VARCHAR2',60,'N'),
    'ACTOR_SUBJECT': ('VARCHAR2',255,'N'), 'IDEMPOTENCY_KEY': ('VARCHAR2',64,'N'), 'BODY_HASH': ('VARCHAR2',64,'N'),
    'PREVIEW_JSON': ('CLOB',None,'N'), 'CREATED_AT': ('TIMESTAMP(6) WITH TIME ZONE',None,'N')},
 'MVP_P3_RESOLUTIONS': {'DRAFT_ID': ('VARCHAR2',30,'N'), 'REQUEST_ID': ('VARCHAR2',30,'N'),
    'ACTION_TYPE': ('VARCHAR2',12,'N'), 'PROPOSAL_ID': ('VARCHAR2',30,'Y'), 'DECISION_ID': ('VARCHAR2',30,'Y'),
    'ACTOR_SUBJECT': ('VARCHAR2',255,'N'), 'IDEMPOTENCY_KEY': ('VARCHAR2',64,'N'), 'BODY_HASH': ('VARCHAR2',64,'N'),
    'REASON': ('VARCHAR2',2000,'Y'), 'CREATED_AT': ('TIMESTAMP(6) WITH TIME ZONE',None,'N')},
}
KEYS = {
 'MP3_DRAFT_PK': ('MVP_P3_DRAFTS','P','DRAFT_ID',None),
 'MP3_DRAFT_REF': ('MVP_P3_DRAFTS','U','DRAFT_ID,REQUEST_ID',None),
 'MP3_DRAFT_VERSION': ('MVP_P3_DRAFTS','U','REQUEST_ID,REVISION',None),
 'MP3_DRAFT_IDEM': ('MVP_P3_DRAFTS','U','IDEMPOTENCY_KEY',None),
 'MP3_DRAFT_REQUEST': ('MVP_P3_DRAFTS','R','REQUEST_ID','REQUESTS'),
 'MP3_DRAFT_POLICY': ('MVP_P3_DRAFTS','R','POLICY_VERSION','STAFFING_POLICIES'),
 'MP3_RESOLUTION_PK': ('MVP_P3_RESOLUTIONS','P','DRAFT_ID',None),
 'MP3_RESOLUTION_IDEM': ('MVP_P3_RESOLUTIONS','U','IDEMPOTENCY_KEY',None),
 'MP3_RESOLUTION_DRAFT': ('MVP_P3_RESOLUTIONS','R','DRAFT_ID,REQUEST_ID','MVP_P3_DRAFTS'),
 'MP3_RESOLUTION_DECISION': ('MVP_P3_RESOLUTIONS','R','DECISION_ID,PROPOSAL_ID,REQUEST_ID,ACTION_TYPE','APPROVAL_DECISIONS'),
 'MP3_PROPOSAL_REQUEST': ('POD_PROPOSALS','R','REQUEST_ID','REQUESTS'),
}
CHECKS = {
 'MP3_DRAFT_JSON': ('MVP_P3_DRAFTS','preview_json IS JSON STRICT WITH UNIQUE KEYS'),
 'MP3_DRAFT_POSITIVE': ('MVP_P3_DRAFTS','request_revision>0 AND revision>0'),
 'MP3_RESOLUTION_ACTION': ('MVP_P3_RESOLUTIONS',"(action_type='DISCARDED' AND proposal_id IS NULL AND decision_id IS NULL) OR (action_type IN ('APPROVED','REJECTED') AND proposal_id IS NOT NULL AND decision_id IS NOT NULL)"),
 'MP3_RESOLUTION_REASON': ('MVP_P3_RESOLUTIONS',"action_type<>'REJECTED' OR (reason IS NOT NULL AND REGEXP_LIKE(reason,'[^[:space:]]'))"),
 'MP3_PROPOSAL_ORIGIN': ('POD_PROPOSALS',"(origin_type='AGENT' AND execution_id IS NOT NULL) OR (origin_type='MANUAL' AND execution_id IS NULL)"),
 'MP3_MEMBER_SCORE': ('POD_PROPOSAL_MEMBERS',"(manual_flag='Y' AND score IS NULL) OR (manual_flag='N' AND score IS NOT NULL)"),
}
TRIGGERS = {
 'MP3_DRAFT_FREEZE': ('MVP_P3_DRAFTS', "BEFORE UPDATE OR DELETE ON mvp_p3_drafts FOR EACH ROW BEGIN RAISE_APPLICATION_ERROR(-20280,'Manual history is append-only.'); END;"),
 'MP3_RESOLUTION_FREEZE': ('MVP_P3_RESOLUTIONS', "BEFORE UPDATE OR DELETE ON mvp_p3_resolutions FOR EACH ROW BEGIN RAISE_APPLICATION_ERROR(-20280,'Manual history is append-only.'); END;"),
 'MP3_ORIGIN_FREEZE': ('POD_PROPOSALS', "BEFORE UPDATE ON pod_proposals FOR EACH ROW BEGIN IF :OLD.status<>'BUILDING' AND (:OLD.origin_type<>:NEW.origin_type OR NVL(:OLD.execution_id,'!')<>NVL(:NEW.execution_id,'!')) THEN RAISE_APPLICATION_ERROR(-20281,'Published origin is frozen.'); END IF; END;"),
 'MP3_MEMBER_ORIGIN': ('POD_PROPOSAL_MEMBERS', "BEFORE INSERT OR UPDATE ON pod_proposal_members FOR EACH ROW DECLARE origin_ VARCHAR2(8); BEGIN SELECT origin_type INTO origin_ FROM pod_proposals WHERE proposal_id=:NEW.proposal_id; IF :NEW.manual_flag='Y' AND origin_<>'MANUAL' THEN RAISE_APPLICATION_ERROR(-20282,'Manual members need Captain manual origin.'); END IF; END;"),
}


def verify(c):
    verify_phase2(c)
    def demand(ok):
        if not ok:
            raise ServiceError('MANUAL_SCHEMA_MISMATCH', 'Phase 3 schema differs from the migration. Keep services stopped; retain history and inspect the mismatch.', 409)
    tables = {**TABLES, 'POD_PROPOSALS': {'EXECUTION_ID': ('VARCHAR2',64,'Y'), 'ORIGIN_TYPE': ('VARCHAR2',8,'N')},
              'POD_PROPOSAL_MEMBERS': {'SCORE': ('NUMBER',5,'Y'), 'MANUAL_FLAG': ('CHAR',1,'N')}}
    for table, expected in tables.items():
        columns = rows(c, 'SELECT column_name,data_type,char_length,data_precision,data_scale,nullable,data_default FROM user_tab_columns WHERE table_name=:tableName', tableName=table)
        by_name = {r['column_name']: r for r in columns}
        demand(set(by_name) == set(expected) if table in TABLES else set(expected) <= set(by_name))
        for name, (dtype, size, nullable) in expected.items():
            actual = by_name[name]
            demand(actual['data_type'] == dtype and actual['nullable'] == nullable)
            if size is not None:
                demand(actual['data_precision' if dtype == 'NUMBER' else 'char_length'] == size)
            if dtype == 'NUMBER':
                demand(actual['data_scale'] == (2 if name == 'SCORE' else 0))
            if name in ('ORIGIN_TYPE','MANUAL_FLAG'):
                demand(normalized(actual['data_default']) == ("'AGENT'" if name == 'ORIGIN_TYPE' else "'N'"))
    for name, (table, kind, columns, parent) in KEYS.items():
        found = rows(c, """SELECT c.table_name,c.constraint_type,c.status,c.validated,c.r_owner,c.delete_rule,p.table_name AS parent_table,
            (SELECT LISTAGG(cc.column_name,',') WITHIN GROUP(ORDER BY cc.position) FROM user_cons_columns cc WHERE cc.constraint_name=c.constraint_name) AS columns_list,
            (SELECT LISTAGG(pc.column_name,',') WITHIN GROUP(ORDER BY pc.position) FROM user_cons_columns pc WHERE pc.constraint_name=p.constraint_name) AS parent_columns
            FROM user_constraints c LEFT JOIN user_constraints p ON c.r_constraint_name=p.constraint_name
            WHERE c.constraint_name=:constraintName""", constraintName=name)
        demand(len(found) == 1)
        r = found[0]
        demand((r['table_name'],r['constraint_type'],r['columns_list'],r['parent_table']) == (table,kind,columns,parent)
               and r['status']=='ENABLED' and r['validated']=='VALIDATED')
        if parent:
            demand(r['r_owner']=='AI_POD_STAFFING' and r['delete_rule']=='NO ACTION' and r['parent_columns']==columns)
    for name, (table, expression) in CHECKS.items():
        found = rows(c, 'SELECT table_name,constraint_type,status,validated,search_condition_vc FROM user_constraints WHERE constraint_name=:constraintName', constraintName=name)
        demand(len(found)==1 and found[0]['table_name']==table and found[0]['constraint_type']=='C'
               and found[0]['status']=='ENABLED' and found[0]['validated']=='VALIDATED'
               and normalized(found[0]['search_condition_vc'])==normalized(expression))
    for name, (table, body) in TRIGGERS.items():
        found = rows(c, 'SELECT status,table_name FROM user_triggers WHERE trigger_name=:triggerName', triggerName=name)
        demand(len(found)==1 and found[0]['status']=='ENABLED' and found[0]['table_name']==table)
        source = rows(c, "SELECT text FROM user_source WHERE name=:triggerName AND type='TRIGGER' ORDER BY line", triggerName=name)
        demand(normalized(''.join(r['text'] for r in source)) == normalized(f'TRIGGER {name} {body}'))
        demand(not rows(c, 'SELECT name FROM user_errors WHERE name=:triggerName', triggerName=name))
    # Existing immutability/decision/assignment protections must remain enabled.
    for name in ('P2_PROPOSAL_FREEZE','P2_MEMBER_FREEZE','P2_DECISION_REVIEW','P2_DECISION_APPEND','P2_DAY_BOUNDS','P2_AUDIT_APPEND'):
        found = rows(c, 'SELECT status FROM user_triggers WHERE trigger_name=:triggerName', triggerName=name)
        demand(len(found)==1 and found[0]['status']=='ENABLED')
    backups = rows(c, "SELECT object_name FROM mvp_p3_ddl_backup WHERE object_name IN ('POD_PROPOSALS','POD_PROPOSAL_MEMBERS') AND DBMS_LOB.GETLENGTH(ddl_text)>0")
    demand(len(backups)==2)
    return {'verified': True, 'tables': list(TABLES), 'manual_limit_pct': 100, 'basis': '(existing POD hours + new POD hours) / contracted hours * 100', 'writes': 0, 'model_calls': 0}


def main():
    from app.config import Settings
    from app.database import OracleDatabase
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', default='.env')
    args = parser.parse_args()
    db = OracleDatabase(Settings(_env_file=args.env_file))
    try:
        with db.read() as c:
            print(json.dumps(verify(c), indent=2))
    except ServiceError as error:
        print(json.dumps({'error': error.code, 'message': error.message}))
        raise SystemExit(1) from None
    finally:
        db.close()


if __name__ == '__main__':
    main()
