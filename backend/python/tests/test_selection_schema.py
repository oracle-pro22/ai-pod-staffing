"""Offline migration checks; live Oracle acceptance remains a separate step."""
from pathlib import Path
import unittest
from unittest.mock import patch

from app import selection_schema as schema
from app.errors import ServiceError


class SelectionSchemaTests(unittest.TestCase):
    def metadata(self, _connection, sql, **binds):
        if "FROM dual" in sql:
            return [{"owner_name": schema.OWNER, "schema_name": schema.OWNER}]
        if "FROM user_tab_columns" in sql:
            return [{"column_name": name, "data_type": dtype, "char_length": size,
                     "data_precision": size, "data_scale": 0, "nullable": nullable}
                    for name, (dtype, size, nullable) in schema.TABLES[binds["tableName"]].items()]
        if "JOIN user_cons_columns" in sql:
            name = binds["constraintName"]
            kind, columns, parent = schema.CONSTRAINTS[name]
            return [{"constraint_type": kind, "columns_list": columns, "r_constraint_name": parent,
                     "r_owner": schema.OWNER if parent else None, "delete_rule": "NO ACTION",
                     "status": "ENABLED", "validated": "VALIDATED", "table_name": schema.constraint_table(name)}]
        if "FROM user_constraints" in sql:
            name = binds["constraintName"]
            return [{"table_name": schema.constraint_table(name), "constraint_type": "C", "status": "ENABLED",
                     "validated": "VALIDATED", "search_condition_vc": schema.CHECKS[name]}]
        if "FROM user_errors" in sql:
            return []
        name = binds["triggerName"]
        table = schema.constraint_table(name)
        if "FROM user_triggers" in sql:
            return [{"status": "ENABLED", "table_name": table}]
        if "FROM user_source" in sql:
            return [{"text": f"TRIGGER {name} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW "
                             "BEGIN RAISE_APPLICATION_ERROR(-20270,'Selection history is append-only.'); END;"}]
        raise AssertionError(sql)

    def test_exact_schema_is_read_only_and_passes(self):
        def read(connection, sql, **binds):
            self.assertTrue(sql.lstrip().startswith("SELECT "))
            return self.metadata(connection, sql, **binds)
        with patch.object(schema, "rows", side_effect=read):
            result = schema.verify(object())
        self.assertTrue(result["verified"])
        self.assertEqual(result["writes"], 0)
        self.assertEqual(result["model_calls"], 0)

    def assert_mismatch(self, target, mutate):
        def read(connection, sql, **binds):
            data = self.metadata(connection, sql, **binds)
            if target in sql:
                mutate(data)
            return data
        with patch.object(schema, "rows", side_effect=read), self.assertRaises(ServiceError) as error:
            schema.verify(object())
        self.assertEqual(error.exception.code, "SELECTION_SCHEMA_MISMATCH")

    def test_wrong_owner_or_current_schema_rejected(self):
        for field in ("owner_name", "schema_name"):
            with self.subTest(field=field):
                self.assert_mismatch("FROM dual", lambda data: data[0].update({field: "OTHER_SCHEMA"}))

    def test_missing_or_modified_columns_rejected(self):
        self.assert_mismatch("FROM user_tab_columns", lambda data: data.pop())
        self.assert_mismatch("FROM user_tab_columns", lambda data: data[0].update(nullable="Y"))
        self.assert_mismatch("FROM user_tab_columns", lambda data: data[0].update(char_length=200))

    def test_disabled_wrong_table_or_wrong_foreign_key_rejected(self):
        for field, value in (("status", "DISABLED"), ("validated", "NOT VALIDATED"),
                             ("table_name", "REQUESTS"), ("columns_list", "WRONG_COLUMN")):
            with self.subTest(field=field):
                self.assert_mismatch("JOIN user_cons_columns", lambda data: data[0].update({field: value}))
        for field, value in (("r_owner", "OTHER_SCHEMA"), ("delete_rule", "CASCADE"),
                             ("r_constraint_name", "WRONG_PARENT")):
            with self.subTest(field=field):
                self.assert_mismatch("JOIN user_cons_columns",
                    lambda data: data[0].update({field: value}) if data[0]["constraint_type"] == "R" else None)

    def test_missing_or_weakened_check_rejected(self):
        self.assert_mismatch("search_condition_vc", lambda data: data.clear())
        self.assert_mismatch("search_condition_vc", lambda data: data[0].update(search_condition_vc="1=1"))

    def test_disabled_modified_or_invalid_trigger_rejected(self):
        self.assert_mismatch("FROM user_triggers", lambda data: data[0].update(status="DISABLED"))
        self.assert_mismatch("FROM user_source", lambda data: data[0].update(text="TRIGGER MP2_REVIEW_FREEZE BEGIN NULL; END;"))
        self.assert_mismatch("FROM user_errors", lambda data: data.append({"name": "MP2_REVIEW_FREEZE"}))

    def test_migration_is_additive_and_refuses_running_jobs(self):
        sql = (Path(__file__).resolve().parents[3] / "sql/oracle/mvp_phase2.sql").read_text().upper()
        for table in schema.TABLES:
            self.assertIn(f"CREATE TABLE {table}", sql)
        self.assertEqual(sql.count("CREATE TABLE "), 3)
        self.assertEqual(sql.count("CREATE TRIGGER "), 3)
        self.assertIn("AGENTS_ENABLED='N' AND NOTIFICATIONS_ENABLED='N'", sql)
        self.assertIn("STATUS IN ('QUEUED','RUNNING')", sql)
        self.assertIn("IF N=0 THEN", sql)
        for destructive in ("DROP TABLE", "TRUNCATE TABLE", "DELETE FROM", "INSERT INTO", "CREATE OR REPLACE", "UPDATE STAFFING_RUNTIME"):
            self.assertNotIn(destructive, sql)


if __name__ == "__main__":
    unittest.main()
