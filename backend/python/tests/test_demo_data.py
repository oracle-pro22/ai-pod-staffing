"""Offline data-loader safeguards; these doubles do NOT test Oracle triggers or locks."""

import ast
import copy
import inspect
import json
import unittest
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import demo_backup, demo_data
from app.demo_dataset import build_demo_dataset
from app.errors import ServiceError


class ExternalDistributionTests(unittest.TestCase):
    def setUp(self):
        self.monday = date(2026, 9, 14)
        self.days = {
            self.monday + timedelta(days=i): {"available": Decimal(8) if i < 5 else Decimal(0)}
            for i in range(7)
        }

    def test_exact_total_and_no_weekend_work(self):
        result = demo_data.distribute_external(self.days, Decimal("12.01"))
        self.assertEqual(sum(result.values()), Decimal("12.01"))
        self.assertTrue(all(day.weekday() < 5 and hours <= 8 for day, hours in result.items()))
        self.assertLessEqual(max(result.values()) - min(result.values()), Decimal("0.01"))

    def test_full_day_absence_is_never_allocated(self):
        friday = self.monday + timedelta(days=4)
        self.days[friday]["available"] = Decimal(0)
        result = demo_data.distribute_external(self.days, 8)
        self.assertNotIn(friday, result)
        self.assertEqual(set(result.values()), {Decimal(2)})

    def test_partial_day_capacity_is_respected(self):
        self.days[self.monday]["available"] = Decimal("0.50")
        result = demo_data.distribute_external(self.days, 16)
        self.assertEqual(result[self.monday], Decimal("0.50"))
        self.assertEqual(sum(result.values()), 16)
        self.assertTrue(all(value <= self.days[day]["available"] for day, value in result.items()))

    def test_excessive_work_rejected(self):
        with self.assertRaises(ServiceError):
            demo_data.distribute_external(self.days, 41)

    def test_fully_absent_week_and_zero_work(self):
        self.assertEqual(demo_data.distribute_external(self.days, 0), {})
        absent = {day: {"available": Decimal(0)} for day in self.days}
        self.assertEqual(demo_data.distribute_external(absent, 8), {})

    def test_invalid_hours_rejected(self):
        for hours in (Decimal("-1"), Decimal("NaN"), Decimal("Infinity"), Decimal("0.001")):
            with self.subTest(hours=hours), self.assertRaises((ServiceError, ValueError)):
                demo_data.distribute_external(self.days, hours)

    def test_inputs_not_mutated(self):
        before = copy.deepcopy(self.days)
        demo_data.distribute_external(self.days, 12)
        self.assertEqual(self.days, before)


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.dataset = build_demo_dataset(date(2026, 9, 14))
        self.roster = [
            {"person_id": p.person_id, "full_name": p.full_name, "external_identity_subject": None}
            for p in self.dataset.people
            if p.person_id != demo_data.ADMIN_ID
        ]
        self.scalar_override = None
        self.patches = [
            patch("app.demo_data.read_catalog", return_value=({}, {})),
            patch("app.demo_data.rows", side_effect=lambda *_args, **_kwargs: self.roster),
            patch("app.demo_data.scalar", side_effect=self.scalar),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def scalar(self, _connection, sql, **_binds):
        if self.scalar_override:
            result = self.scalar_override(sql)
            if result is not None:
                return result
        return 1 if "FROM app_roles" in sql or "FROM user_sequences" in sql else 0

    def test_expected_existing_roster_allowed(self):
        self.assertEqual(demo_data.preflight(None, self.dataset), ({}, {}))

    def test_roster_name_or_identifier_drift_rejected(self):
        self.roster[0]["full_name"] = "Someone else"
        with self.assertRaises(ServiceError):
            demo_data.preflight(None, self.dataset)

    def test_missing_person_rejected(self):
        self.roster.pop()
        with self.assertRaises(ServiceError):
            demo_data.preflight(None, self.dataset)

    def test_real_identity_not_overwritten(self):
        self.roster[0]["external_identity_subject"] = "company-identity-123"
        with self.assertRaises(ServiceError):
            demo_data.preflight(None, self.dataset)

    def test_existing_assignments_require_review(self):
        self.scalar_override = lambda sql: 1 if "FROM pod_assignments" in sql else None
        with self.assertRaises(ServiceError):
            demo_data.preflight(None, self.dataset)

    def test_reserved_policy_collision_rejected(self):
        self.scalar_override = lambda sql: 1 if "FROM staffing_policies" in sql else None
        with self.assertRaises(ServiceError):
            demo_data.preflight(None, self.dataset)

    def test_real_active_role_mapping_rejected(self):
        self.scalar_override = lambda sql: 1 if "FROM app_user_roles" in sql else None
        with self.assertRaises(ServiceError):
            demo_data.preflight(None, self.dataset)

    def test_missing_active_role_rejected(self):
        self.scalar_override = lambda sql: 0 if "FROM app_roles" in sql else None
        with self.assertRaises(ServiceError):
            demo_data.preflight(None, self.dataset)

    def test_reserved_request_collision_rejected(self):
        self.scalar_override = lambda sql: 1 if "FROM requests" in sql else None
        with self.assertRaises(ServiceError):
            demo_data.preflight(None, self.dataset)


class BackupTests(unittest.TestCase):
    def test_only_mutable_inputs_are_backed_up(self):
        self.assertEqual(len(demo_backup.MUTABLE_TABLES), 9)
        self.assertEqual(set(demo_backup.BACKUP_TABLES), set(demo_backup.MUTABLE_TABLES))
        self.assertTrue(set(demo_backup.HISTORY_TABLES) <= set(demo_backup.TRACKED_TABLES))
        self.assertFalse(set(demo_backup.HISTORY_TABLES) & set(demo_backup.MUTABLE_TABLES))
        self.assertTrue(all(len(name) <= 30 for name in demo_backup.BACKUP_TABLES.values()))

    def test_arbitrary_table_sql_rejected_before_any_query(self):
        connection = MagicMock()
        with self.assertRaises(ServiceError), patch("app.demo_backup.rows") as read:
            demo_backup.fingerprint(connection, "PEOPLE; DROP TABLE PEOPLE")
        read.assert_not_called()
        connection.cursor.assert_not_called()

    def test_canonical_serialization_reads_lob_and_preserves_types(self):
        lob = SimpleNamespace(read=lambda: "A long text value")
        moment = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
        value = demo_backup._canonical(
            (lob, Decimal("2.000"), 2.0, date(2026, 9, 14), moment, b"\x00\x01", True)
        )
        self.assertEqual(value[0], "A long text value")
        self.assertEqual(value[1], value[2])
        self.assertEqual(value[3], {"date": "2026-09-14"})
        self.assertEqual(value[4], {"date": "2026-09-14T12:00:00+00:00"})
        self.assertEqual(value[5], {"bytes": "AAE="})
        self.assertIs(value[6], True)

    def test_unknown_value_type_does_not_get_silently_stringified(self):
        with self.assertRaises(TypeError):
            demo_backup._canonical(object())

    def fingerprint(self, records):
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value.__iter__.return_value = iter(records)
        columns = [{"column_name": "PERSON_ID", "data_type": "VARCHAR2", "data_length": 30, "nullable": "N"}]
        with (
            patch("app.demo_backup._object_type", return_value="TABLE"),
            patch("app.demo_backup._columns", return_value=columns),
        ):
            return demo_backup.fingerprint(connection, "PEOPLE")

    def test_hash_is_order_independent_but_duplicate_sensitive(self):
        first = self.fingerprint([("P-001",), ("P-002",)])
        reordered = self.fingerprint([("P-002",), ("P-001",)])
        duplicate = self.fingerprint([("P-001",), ("P-002",), ("P-002",)])
        self.assertEqual(first, reordered)
        self.assertNotEqual(first["data_hash"], duplicate["data_hash"])
        self.assertEqual(duplicate["row_count"], 3)

    def test_unknown_backup_ownership_stops_before_ddl(self):
        connection = MagicMock()

        @contextmanager
        def write():
            yield connection

        database = SimpleNamespace(write=write)

        def read(_connection, sql, **_binds):
            return (
                [{"agents_enabled": "N", "notifications_enabled": "N"}]
                if "staffing_runtime" in sql
                else [{"n": 0}]
            )

        def object_type(_connection, name):
            return None if name == demo_backup.STATE_TABLE else "TABLE"

        with (
            patch("app.demo_backup.rows", side_effect=read),
            patch("app.demo_backup._object_type", side_effect=object_type),
        ):
            with self.assertRaises(ServiceError):
                demo_backup.prepare(database, date(2026, 9, 14), "test-operator")
        connection.cursor.assert_not_called()

    def test_enabled_runtime_stops_before_schema_work(self):
        connection = MagicMock()

        @contextmanager
        def write():
            yield connection

        with patch(
            "app.demo_backup.rows", return_value=[{"agents_enabled": "Y", "notifications_enabled": "N"}]
        ):
            with self.assertRaises(ServiceError):
                demo_backup.prepare(SimpleNamespace(write=write), date(2026, 9, 14), "test-operator")
        connection.cursor.assert_not_called()

    def test_applied_manifest_returns_without_recreating_copies(self):
        connection = MagicMock()

        @contextmanager
        def write():
            yield connection

        metadata = {"status": "APPLIED", "anchor": "2026-09-14", "operator": "test-operator"}

        def read(_connection, sql, **_binds):
            return (
                [{"agents_enabled": "N", "notifications_enabled": "N"}]
                if "staffing_runtime" in sql
                else [{"n": 0}]
            )

        with (
            patch("app.demo_backup.rows", side_effect=read),
            patch("app.demo_backup._object_type", return_value="TABLE"),
            patch("app.demo_backup._verify_state_table"),
            patch("app.demo_backup.read_state", return_value=metadata),
            patch("app.demo_backup.verify_backups", return_value={}) as verify,
        ):
            self.assertEqual(
                demo_backup.prepare(SimpleNamespace(write=write), date(2026, 9, 14), "test-operator"),
                metadata,
            )
        verify.assert_called_once_with(connection)
        connection.cursor.assert_not_called()

    def test_resumed_source_change_stops_without_overwriting_copy(self):
        connection = MagicMock()

        @contextmanager
        def write():
            yield connection

        metadata = {"status": "PREPARING", "anchor": "2026-09-14", "operator": "test-operator"}

        def read(_connection, sql, **_binds):
            return (
                [{"agents_enabled": "N", "notifications_enabled": "N"}]
                if "staffing_runtime" in sql
                else [{"n": 0}]
            )

        def state(_connection, key="migration"):
            return metadata if key == "migration" else {"status": "PLANNED", "before": {"data_hash": "old"}}

        with (
            patch("app.demo_backup.rows", side_effect=read),
            patch("app.demo_backup._object_type", return_value="TABLE"),
            patch("app.demo_backup._verify_state_table"),
            patch("app.demo_backup.read_state", side_effect=state),
            patch("app.demo_backup.fingerprint", return_value={"data_hash": "new"}),
        ):
            with self.assertRaises(ServiceError):
                demo_backup.prepare(SimpleNamespace(write=write), date(2026, 9, 14), "test-operator")
        connection.cursor.assert_not_called()

    def test_save_state_binds_input_and_does_not_commit(self):
        connection = MagicMock()
        key = "review'; DELETE FROM people; --"
        demo_backup.save_state(connection, key, {"status": "APPLIED"})
        sql = connection.cursor.return_value.__enter__.return_value.execute.call_args.args[0]
        binds = connection.cursor.return_value.__enter__.return_value.execute.call_args.kwargs
        self.assertNotIn(key, sql)
        self.assertEqual(binds["stateKey"], key)
        self.assertEqual(json.loads(binds["stateValue"]), {"status": "APPLIED"})
        connection.commit.assert_not_called()


class LoaderContractTests(unittest.TestCase):
    def test_existing_manifest_requires_verified_ownership(self):
        with (
            patch("app.demo_data.scalar", return_value=1),
            patch(
                "app.demo_data.owned_metadata",
                side_effect=ServiceError("DEMO_BACKUP_CONFLICT", "Unknown owner", 409),
            ) as verify,
        ):
            with self.assertRaises(ServiceError):
                demo_data.existing_metadata(None)
        verify.assert_called_once_with(None)

    def test_refresh_only_removes_owned_recurring_work_in_the_selected_window(self):
        from dataclasses import replace

        dataset = replace(build_demo_dataset(date(2026, 9, 14)), people=())
        calls = []
        person = build_demo_dataset(date(2026, 9, 14)).people[0]
        dataset = replace(dataset, people=(person,))

        def read(_connection, sql, **_binds):
            return [{"availability_version": 1}] if "SELECT availability_version" in sql else []

        with (
            patch("app.demo_data.rows", side_effect=read),
            patch("app.demo_data.build_days", return_value={}),
            patch("app.demo_data.execute", side_effect=lambda *args: calls.append(args)),
        ):
            demo_data.capacity_inputs(None, dataset)
        self.assertEqual(len(calls), 1)
        sql, binds = calls[0][1:3]
        for predicate in (
            "person_id=:personId",
            "created_by=:batch",
            "event_type='Commitment'",
            "capacity_kind='EXTERNAL_WORK'",
            "starts_on=ends_on",
            "BETWEEN :startDay AND :endDay",
        ):
            self.assertIn(predicate, sql)
        self.assertEqual(binds["batch"], demo_data.BATCH)
        self.assertEqual(binds["startDay"], dataset.anchor)
        self.assertEqual(binds["endDay"], dataset.capacity_end)

    def test_prepared_dataset_cannot_be_silently_changed(self):
        connection = MagicMock()

        @contextmanager
        def write():
            yield connection

        def read(_connection, sql, **_binds):
            return (
                [{"agents_enabled": "N", "notifications_enabled": "N"}]
                if "staffing_runtime" in sql
                else [{"n": 0}]
            )

        metadata = {
            "status": "PREPARED",
            "anchor": "2026-09-14",
            "operator": "test-operator",
            "dataset_signature": "original",
        }
        with (
            patch("app.demo_backup.rows", side_effect=read),
            patch("app.demo_backup._object_type", return_value="TABLE"),
            patch("app.demo_backup._verify_state_table"),
            patch("app.demo_backup.read_state", return_value=metadata),
        ):
            with self.assertRaises(ServiceError):
                demo_backup.prepare(
                    SimpleNamespace(write=write),
                    date(2026, 9, 14),
                    "test-operator",
                    dataset_signature="changed",
                )
        connection.cursor.assert_not_called()

    def test_baseline_policy_uses_runtime_reader_json_contract(self):
        calls = []
        with patch("app.demo_data.execute", side_effect=lambda *_args: calls.append(_args)):
            demo_data.baseline_policy(None, "test-operator")
        rules = [call[2] for call in calls if "INSERT INTO eligibility_rules" in call[1]]
        self.assertEqual(len(rules), 4)
        values = {rule["ruleCode"]: json.loads(rule["valueJson"])["value"] for rule in rules}
        self.assertEqual(
            values,
            {
                "MINIMUM_STRENGTH": 3,
                "LEAD_ROLE": "POD_LEAD",
                "MEMBER_ROLES": ["POD_MEMBER", "POD_LEAD"],
                "MAX_AGENT_STEPS": 12,
            },
        )
        self.assertIn("'DRAFT'", calls[0][1])
        self.assertIn("status='APPROVED'", calls[-1][1])
        self.assertEqual(calls[-1][2]["operatorName"], "demo-import:test-operator")

    def test_sql_constants_do_not_disable_triggers_or_remove_frozen_history(self):
        # A narrow source-level guard, not a substitute for Oracle integration tests.
        module = ast.parse(inspect.getsource(demo_data))
        frozen = (
            "APPROVAL_DECISIONS",
            "AUDIT_EVENTS",
            "AGENT_EXECUTION_EVENTS",
            "POD_PROPOSAL_MEMBERS",
            "POD_PROPOSALS",
        )
        for node in ast.walk(module):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "execute"
                and len(node.args) > 1
            ):
                sql = (
                    node.args[1].value.upper()
                    if isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str)
                    else ""
                )
                self.assertNotIn("DISABLE ALL TRIGGERS", sql)
                self.assertNotIn("TRUNCATE TABLE", sql)
                self.assertNotIn("DROP TABLE", sql)
                for table in frozen:
                    self.assertNotIn("DELETE FROM " + table, sql)


if __name__ == "__main__":
    unittest.main()
