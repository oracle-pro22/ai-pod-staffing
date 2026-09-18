"""Read-only structural verification of the additive MVP Phase 2 migration."""
import argparse
import json
import re

from app.errors import ServiceError
from app.storage import rows

TABLES = {
    "MVP_P2_REVIEWS": {"PROPOSAL_ID": ("VARCHAR2", 30, "N"), "REVIEW_JSON": ("CLOB", None, "N"),
                       "CREATED_AT": ("TIMESTAMP(6) WITH TIME ZONE", None, "N")},
    "MVP_P2_SELECTIONS": {"SELECTION_ID": ("VARCHAR2", 30, "N"), "PROPOSAL_ID": ("VARCHAR2", 30, "N"),
        "REVISION": ("NUMBER", 10, "N"), "ACTOR_SUBJECT": ("VARCHAR2", 255, "N"),
        "IDEMPOTENCY_KEY": ("VARCHAR2", 64, "N"), "BODY_HASH": ("VARCHAR2", 64, "N"),
        "REVIEW_JSON": ("CLOB", None, "N"), "CREATED_AT": ("TIMESTAMP(6) WITH TIME ZONE", None, "N")},
    "MVP_P2_DECISIONS": {"DECISION_ID": ("VARCHAR2", 30, "N"), "SOURCE_PROPOSAL_ID": ("VARCHAR2", 30, "N"),
        "SOURCE_PROPOSAL_VERSION": ("NUMBER", 10, "N"), "SELECTION_ID": ("VARCHAR2", 30, "Y")},
}
CONSTRAINTS = {
    "MP2_REVIEW_PK": ("P", "PROPOSAL_ID", None),
    "MP2_REVIEW_PROPOSAL": ("R", "PROPOSAL_ID", "P2_PROPOSAL_PK"),
    "MP2_SELECTION_PK": ("P", "SELECTION_ID", None),
    "MP2_SELECTION_PROPOSAL": ("R", "PROPOSAL_ID", "MP2_REVIEW_PK"),
    "MP2_SELECTION_REVISION": ("U", "PROPOSAL_ID,REVISION", None),
    "MP2_SELECTION_IDEM": ("U", "IDEMPOTENCY_KEY", None),
    "MP2_DECISION_PK": ("P", "DECISION_ID", None),
    "MP2_DECISION_PARENT": ("R", "DECISION_ID", "P2_DECISION_PK"),
    "MP2_DECISION_SOURCE": ("R", "SOURCE_PROPOSAL_ID", "P2_PROPOSAL_PK"),
    "MP2_DECISION_SELECTION": ("R", "SELECTION_ID", "MP2_SELECTION_PK"),
}
CHECKS = {"MP2_REVIEW_JSON": "REVIEW_JSON IS JSON STRICT WITH UNIQUE KEYS",
          "MP2_SELECTION_JSON": "REVIEW_JSON IS JSON STRICT WITH UNIQUE KEYS",
          "MP2_SELECTION_POSITIVE": "REVISION>0", "MP2_DECISION_VERSION": "SOURCE_PROPOSAL_VERSION>0"}
OWNER = "AI_POD_STAFFING"


def constraint_table(name):
    return {"REVIEW": "MVP_P2_REVIEWS", "SELECTION": "MVP_P2_SELECTIONS",
            "DECISION": "MVP_P2_DECISIONS"}[name.split("_")[1]]


def normalized(text):
    return re.sub(r'[\s"()]', '', text).upper()


def verify(connection):
    def require(ok):
        if not ok:
            raise ServiceError("SELECTION_SCHEMA_MISMATCH", "MVP Phase 2 schema is missing or differs from its migration. Keep services stopped and inspect; do not drop existing tables.", 409)
    identity = rows(connection, "SELECT USER AS owner_name,SYS_CONTEXT('USERENV','CURRENT_SCHEMA') AS schema_name FROM dual")
    require(len(identity) == 1 and identity[0]["owner_name"] == OWNER and identity[0]["schema_name"] == OWNER)
    for table, expected in TABLES.items():
        columns = rows(connection, "SELECT column_name,data_type,char_length,data_precision,data_scale,nullable FROM user_tab_columns WHERE table_name=:tableName", tableName=table)
        require({c["column_name"] for c in columns} == set(expected))
        for column in columns:
            dtype, size, nullable = expected[column["column_name"]]
            require(column["data_type"] == dtype and column["nullable"] == nullable)
            if size is not None:
                require((column["char_length"] if dtype == "VARCHAR2" else column["data_precision"]) == size)
            if dtype == "NUMBER":
                require(column["data_scale"] == 0)
    for name, (ctype, columns, parent) in CONSTRAINTS.items():
        records = rows(connection, """SELECT c.table_name,c.constraint_type,c.status,c.validated,c.r_owner,c.r_constraint_name,c.delete_rule,
            LISTAGG(cc.column_name,',') WITHIN GROUP(ORDER BY cc.position) AS columns_list
            FROM user_constraints c JOIN user_cons_columns cc ON cc.constraint_name=c.constraint_name
            WHERE c.constraint_name=:constraintName
            GROUP BY c.table_name,c.constraint_type,c.status,c.validated,c.r_owner,c.r_constraint_name,c.delete_rule""", constraintName=name)
        require(len(records) == 1)
        c = records[0]
        require((c["constraint_type"], c["columns_list"], c["r_constraint_name"]) == (ctype, columns, parent)
                and c["status"] == "ENABLED" and c["validated"] == "VALIDATED" and c["table_name"] == constraint_table(name))
        if parent:
            require(c["delete_rule"] == "NO ACTION" and c["r_owner"] == OWNER)
    for name, expression in CHECKS.items():
        found = rows(connection, "SELECT table_name,constraint_type,status,validated,search_condition_vc FROM user_constraints WHERE constraint_name=:constraintName", constraintName=name)
        require(len(found) == 1 and found[0]["status"] == "ENABLED" and found[0]["validated"] == "VALIDATED"
                and found[0]["table_name"] == constraint_table(name) and found[0]["constraint_type"] == "C"
                and normalized(found[0]["search_condition_vc"]) == normalized(expression))
    for name, table in (("MP2_REVIEW_FREEZE", "MVP_P2_REVIEWS"), ("MP2_SELECTION_FREEZE", "MVP_P2_SELECTIONS"), ("MP2_DECISION_FREEZE", "MVP_P2_DECISIONS")):
        found = rows(connection, "SELECT status,table_name FROM user_triggers WHERE trigger_name=:triggerName", triggerName=name)
        require(len(found) == 1 and found[0]["status"] == "ENABLED" and found[0]["table_name"] == table)
        source = rows(connection, "SELECT text FROM user_source WHERE name=:triggerName AND type='TRIGGER' ORDER BY line", triggerName=name)
        expected = f"TRIGGER {name} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW BEGIN RAISE_APPLICATION_ERROR(-20270,'Selection history is append-only.'); END;"
        require(normalized(''.join(r['text'] for r in source)) == normalized(expected))
        require(not rows(connection, "SELECT name FROM user_errors WHERE name=:triggerName", triggerName=name))
    return {"verified": True, "tables": list(TABLES), "writes": 0, "model_calls": 0}


def main():
    from app.config import Settings
    from app.database import OracleDatabase
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args()
    database = OracleDatabase(Settings(_env_file=args.env_file))
    try:
        with database.read() as connection:
            print(json.dumps(verify(connection), indent=2))
    except ServiceError as error:
        print(json.dumps({"error": error.code, "message": error.message}))
        raise SystemExit(1) from None
    finally:
        database.close()


if __name__ == "__main__":
    main()
