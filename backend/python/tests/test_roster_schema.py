"""Offline schema-verifier and migration contracts, not a live Oracle DDL test."""

import unittest
from pathlib import Path
from unittest.mock import patch

from app.errors import ServiceError
from app.roster_schema import KEYS, trigger_source, verify


class RosterSchemaTests(unittest.TestCase):
    def query(self, _connection, sql, **binds):
        if "SELECT USER AS owner_name" in sql:
            return [{"owner_name": "AI_POD_STAFFING", "schema_name": "AI_POD_STAFFING"}]
        if "constraintName" in binds:
            table, kind, columns, parent, parent_columns = KEYS[binds["constraintName"]]
            return [
                {
                    "table_name": table,
                    "constraint_type": kind,
                    "columns_list": columns,
                    "parent_table": parent,
                    "parent_columns": parent_columns,
                    "status": "ENABLED",
                    "validated": "VALIDATED",
                    "r_owner": "AI_POD_STAFFING",
                    "delete_rule": "NO ACTION",
                }
            ]
        if "FROM user_triggers" in sql:
            return [{"status": "ENABLED", "table_name": "APPROVAL_DECISIONS"}]
        if "FROM user_source" in sql:
            return [{"text": trigger_source()}]
        if "FROM rm2_ddl_backup" in sql:
            return [
                {"object_name": name}
                for name in ("POD_PROPOSALS", "APPROVAL_DECISIONS", "P2_DECISION_REVIEW")
            ]
        return []

    def test_expected_schema_verifies_read_only(self):
        with patch("app.roster_schema.rows", side_effect=self.query):
            result = verify(None)
        self.assertTrue(result["verified"])
        self.assertEqual(result["writes"], 0)
        self.assertFalse(result["roster_imported"])
        self.assertFalse(result["history_archived"])

    def test_old_owner_fk_cannot_survive_verification(self):
        def read(c, sql, **b):
            if "constraint_name='P2_DECISION_PROPOSAL'" in sql:
                return [{"constraint_name": "P2_DECISION_PROPOSAL"}]
            return self.query(c, sql, **b)

        with patch("app.roster_schema.rows", side_effect=read), self.assertRaises(ServiceError):
            verify(None)

    def test_bad_parent_disabled_key_or_unvalidated_key_fails_closed(self):
        for change in (
            {"parent_table": "REQUESTS"},
            {"parent_columns": "REQUEST_ID"},
            {"status": "DISABLED"},
            {"validated": "NOT VALIDATED"},
            {"delete_rule": "CASCADE"},
        ):

            def read(c, sql, **b):
                result = self.query(c, sql, **b)
                if b.get("constraintName") == "RM2_DECISION_REQUEST":
                    result[0].update(change)
                return result

            with (
                self.subTest(change=change),
                patch("app.roster_schema.rows", side_effect=read),
                self.assertRaises(ServiceError),
            ):
                verify(None)

    def test_trigger_without_actor_validation_fails_closed(self):
        def read(c, sql, **b):
            if "FROM user_source" in sql:
                return [{"text": trigger_source().replace("ur.identity_subject=:NEW.actor_subject", "1=1")}]
            return self.query(c, sql, **b)

        with patch("app.roster_schema.rows", side_effect=read), self.assertRaises(ServiceError):
            verify(None)

    def test_migration_has_maintenance_guards_before_ddl_and_replacement_before_drop(self):
        sql = (Path(__file__).resolve().parents[3] / "sql/oracle/roster_multirole.sql").read_text(
            encoding="utf-8"
        )
        self.assertLess(sql.index("agents_enabled='N'"), sql.index("CREATE TABLE rm2_ddl_backup"))
        self.assertLess(sql.index("status IN ('QUEUED','RUNNING')"), sql.index("CREATE TABLE rm2_ddl_backup"))
        self.assertLess(
            sql.index("ensure_key('RM2_DECISION_REQUEST'"), sql.index("DROP CONSTRAINT p2_decision_proposal")
        )
        self.assertLess(
            sql.index("ensure_key('RM2_DECISION_ACTOR'"), sql.index("DROP CONSTRAINT p2_decision_proposal")
        )
        self.assertIn("demand(n=4,'Unexpected RM2_DDL_BACKUP column definitions.')", sql)
        self.assertIn("proposal_owner<>request_owner", trigger_source())
        self.assertNotIn("DELETE FROM ", sql.upper())
        self.assertNotIn("UPDATE PEOPLE", sql.upper())
        self.assertNotIn("UPDATE REQUESTS", sql.upper())


if __name__ == "__main__":
    unittest.main()
