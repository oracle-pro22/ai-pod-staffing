"""Read-only verification of the roster Phase 2 shared-Captain schema."""

import argparse
import json
import re
from pathlib import Path

from app.errors import ServiceError
from app.storage import rows

KEYS = {
    "RM2_PROPOSAL_REQUEST": ("POD_PROPOSALS", "U", "PROPOSAL_ID,REQUEST_ID", None, None),
    "RM2_DECISION_REQUEST": (
        "APPROVAL_DECISIONS",
        "R",
        "PROPOSAL_ID,REQUEST_ID",
        "POD_PROPOSALS",
        "PROPOSAL_ID,REQUEST_ID",
    ),
    "RM2_DECISION_ACTOR": ("APPROVAL_DECISIONS", "R", "CAPTAIN_PERSON_ID", "PEOPLE", "PERSON_ID"),
}


def trigger_source():
    migration = Path(__file__).resolve().parents[3] / "sql" / "oracle" / "roster_multirole.sql"
    sql = migration.read_text(encoding="utf-8")
    body = sql.split("CREATE OR REPLACE TRIGGER p2_decision_review\n", 1)[1].split("\n/", 1)[0]
    return "TRIGGER p2_decision_review\n" + body


def normalized(source):
    return re.sub(r"\s+", "", re.sub(r"--[^\n]*", "", source)).replace('"', "").upper()


def verify(connection):
    def demand(ok):
        if not ok:
            raise ServiceError(
                "ROSTER_SCHEMA_MISMATCH",
                "Roster Phase 2 schema differs from its migration. Keep services stopped; preserve data and inspect the mismatch.",
                409,
            )

    identity = rows(
        connection,
        "SELECT USER AS owner_name,SYS_CONTEXT('USERENV','CURRENT_SCHEMA') AS schema_name FROM dual",
    )
    demand(
        len(identity) == 1 and identity[0]["owner_name"] == identity[0]["schema_name"] == "AI_POD_STAFFING"
    )
    for name, expected in KEYS.items():
        found = rows(
            connection,
            """SELECT c.table_name,c.constraint_type,c.status,c.validated,c.r_owner,c.delete_rule,
            p.table_name AS parent_table,
            (SELECT LISTAGG(cc.column_name,',') WITHIN GROUP(ORDER BY cc.position)
             FROM user_cons_columns cc WHERE cc.constraint_name=c.constraint_name) AS columns_list,
            (SELECT LISTAGG(pc.column_name,',') WITHIN GROUP(ORDER BY pc.position)
             FROM user_cons_columns pc WHERE pc.constraint_name=p.constraint_name) AS parent_columns
            FROM user_constraints c LEFT JOIN user_constraints p ON c.r_constraint_name=p.constraint_name
            WHERE c.constraint_name=:constraintName""",
            constraintName=name,
        )
        demand(len(found) == 1)
        record = found[0]
        demand(
            tuple(
                record[key]
                for key in ("table_name", "constraint_type", "columns_list", "parent_table", "parent_columns")
            )
            == expected
            and record["status"] == "ENABLED"
            and record["validated"] == "VALIDATED"
        )
        if expected[3]:
            demand(record["r_owner"] == "AI_POD_STAFFING" and record["delete_rule"] == "NO ACTION")
    demand(
        not rows(
            connection,
            "SELECT constraint_name FROM user_constraints WHERE constraint_name='P2_DECISION_PROPOSAL'",
        )
    )
    found = rows(
        connection, "SELECT status,table_name FROM user_triggers WHERE trigger_name='P2_DECISION_REVIEW'"
    )
    demand(len(found) == 1 and found[0] == {"status": "ENABLED", "table_name": "APPROVAL_DECISIONS"})
    source = rows(
        connection,
        "SELECT text FROM user_source WHERE name='P2_DECISION_REVIEW' AND type='TRIGGER' ORDER BY line",
    )
    demand(normalized("".join(row["text"] for row in source)) == normalized(trigger_source()))
    demand(
        not rows(
            connection, "SELECT name FROM user_errors WHERE name='P2_DECISION_REVIEW' AND type='TRIGGER'"
        )
    )
    backups = rows(connection, "SELECT object_name FROM rm2_ddl_backup WHERE DBMS_LOB.GETLENGTH(ddl_text)>0")
    demand(
        {row["object_name"] for row in backups}
        >= {"POD_PROPOSALS", "APPROVAL_DECISIONS", "P2_DECISION_REVIEW"}
    )
    return {
        "verified": True,
        "shared_captain_decisions": True,
        "writes": 0,
        "model_calls": 0,
        "roster_imported": False,
        "history_archived": False,
    }


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
