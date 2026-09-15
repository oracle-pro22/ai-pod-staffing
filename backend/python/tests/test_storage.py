import json
import unittest
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import patch

from app.errors import ServiceError
from app.storage import document, load_capacity_ledger, load_policy, load_request_snapshot

MON = date(2026, 9, 14)


def request_row():
    return {"request_id": "REQ-1", "request_revision": 1, "responsible_captain_id": "P-1",
            "title": "Delivery", "estimated_start_date": MON, "estimated_completion_date": MON + timedelta(days=4),
            "estimated_hours": 24, "requested_lead_count": 1, "requested_contributor_count": 2,
            "deliverables_json": '[{"id":"DEL-1","name":"Delivery","custom":false}]'}


def requirement(**changes):
    return {"interest_id": "SK-2", "mandatory_flag": "Y", "required_strength": 3,
            "capability_source": "MAPPED", "assessment_type": "SELF_RATED", "derived_role_code": None, **changes}


def capacity_rows():
    return [{"work_date": MON + timedelta(days=i), "available_hours": 8 if i < 5 else 0,
             "external_committed_hours": 0, "availability_version": 2} for i in range(7)]


class StorageTests(unittest.TestCase):
    def test_document_supports_oracle_native_json_and_lobs(self):
        for value in ({"value": 3}, '{"value":3}', b'{"value":3}',
                      StringIO('{"value":3}'), BytesIO(b'{"value":3}')):
            with self.subTest(representation=type(value).__name__):
                self.assertEqual(document(value), {"value": 3})
        self.assertEqual(document([{"id": "DEL-1"}]), [{"id": "DEL-1"}])
        for value in (None, object(), "invalid-json"):
            with self.subTest(representation=type(value).__name__), self.assertRaises(ValueError):
                document(value)

    @patch("app.storage.rows")
    def test_request_supports_native_deliverables_json(self, query):
        row = request_row()
        row["deliverables_json"] = json.loads(row["deliverables_json"])
        query.side_effect = [[row], [requirement()]]
        self.assertEqual(load_request_snapshot(object(), "REQ-1").deliverable_ids, ("DEL-1",))

    @patch("app.storage.rows")
    def test_request_uses_canonical_ids_and_merges_duplicate_requirements(self, query):
        query.side_effect = [[request_row()], [requirement(), requirement(required_strength=4)]]
        result = load_request_snapshot(object(), "REQ-1")
        self.assertEqual(result.deliverable_ids, ("DEL-1",))
        self.assertEqual(len(result.requirements), 1)
        self.assertEqual(result.requirements[0].minimum_strength, 4)
        self.assertEqual(query.call_args.kwargs, {"requestId": "REQ-1"})

    @patch("app.storage.rows")
    def test_missing_captain_is_not_inferred_from_request_source(self, query):
        query.side_effect = [[{**request_row(), "responsible_captain_id": None}], [requirement()]]
        with self.assertRaises(ServiceError) as error:
            load_request_snapshot(object(), "REQ-1")
        self.assertEqual(error.exception.code, "NEEDS_INFORMATION")

    @patch("app.storage.rows")
    def test_custom_mandatory_skill_is_not_silently_discarded(self, query):
        query.side_effect = [[request_row()], [requirement(), requirement(interest_id=None, capability_source="CUSTOM")]]
        with self.assertRaises(ServiceError) as error:
            load_request_snapshot(object(), "REQ-1")
        self.assertEqual(error.exception.code, "NEEDS_INFORMATION")

    @patch("app.storage.rows")
    def test_legacy_role_derived_rating_not_used(self, query):
        query.side_effect = [[request_row()], [requirement(assessment_type="ROLE_DERIVED", required_strength=5)]]
        result = load_request_snapshot(object(), "REQ-1")
        self.assertIsNone(result.requirements[0].minimum_strength)
        self.assertIsNone(result.requirements[0].derived_role_code)

    @patch("app.storage.rows")
    def test_complete_capacity_ledger_returns_workload_version(self, query):
        query.side_effect = [[{"weekly_work_hours": 40, "workload_version": 7, "availability_version": 2}],
                             capacity_rows(), [{"work_date": MON, "hours": 4}]]
        ledger, version = load_capacity_ledger(object(), "P-1", MON, MON)
        self.assertEqual(version, 7)
        self.assertEqual(ledger.confirmed_work[0].hours, Decimal(4))
        self.assertIn("a.status='CONFIRMED'", query.call_args.args[1])
        self.assertEqual(query.call_args.kwargs["endDay"], MON + timedelta(days=6))

    @patch("app.storage.rows")
    def test_missing_working_hours_are_unknown(self, query):
        query.return_value = [{"weekly_work_hours": None}]
        with self.assertRaises(ServiceError) as error:
            load_capacity_ledger(object(), "P-1", MON, MON)
        self.assertEqual(error.exception.code, "CAPACITY_UNKNOWN")

    @patch("app.storage.rows")
    def test_incomplete_or_outdated_days_are_rejected(self, query):
        people = [{"weekly_work_hours": 40, "workload_version": 7, "availability_version": 2}]
        for days in (capacity_rows()[:-1], [{**row, "availability_version": 1} for row in capacity_rows()]):
            query.side_effect = [people, days, []]
            with self.subTest(days=len(days)), self.assertRaises(ServiceError) as error:
                load_capacity_ledger(object(), "P-1", MON, MON)
            self.assertEqual(error.exception.code, "CAPACITY_STALE")

    @patch("app.storage.rows")
    def test_policy_roundtrips_phase1_defaults(self, query):
        policy = {"policy_version": "staffing-v1-draft", "status": "DRAFT", "approved_by": None, "approved_at": None,
                  "default_weekly_hours": 40, "maximum_allocation_pct": 100, "scheduling_timezone": "Asia/Kolkata",
                  "skill_weight": 50, "deliverable_weight": 30, "capacity_weight": 15, "interest_weight": 5}
        rules = [{"rule_code": code, "rule_value_json": json.dumps({"value": value})} for code, value in
                 (("MINIMUM_STRENGTH", 3), ("LEAD_ROLE", "POD_LEAD"),
                  ("MEMBER_ROLES", ["POD_MEMBER", "POD_LEAD"]), ("MAX_AGENT_STEPS", 12))]
        for native in (False, True):
            with self.subTest(native_json=native):
                query.side_effect = [[policy], [
                    {**r, "rule_value_json": json.loads(r["rule_value_json"]) if native else r["rule_value_json"]}
                    for r in rules
                ]]
                result = load_policy(object(), "staffing-v1-draft")
                self.assertEqual(result.weights.skill, 50)
                self.assertEqual(result.status, "DRAFT")
                with self.assertRaises(ServiceError):
                    result.require_published()

    @patch("app.storage.rows")
    def test_incomplete_policy_fails_closed(self, query):
        query.return_value = []
        with self.assertRaises(ServiceError):
            load_policy(object(), "missing")


class MigrationStaticTests(unittest.TestCase):
    """Static regression checks, NOT Oracle syntax or live constraint execution."""
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[3]
        cls.sql = (cls.root / "sql/oracle/phase2.sql").read_text(encoding="utf-8")
        cls.manifest = json.loads(Path(__file__).with_name("phase2_manifest.json").read_text(encoding="utf-8"))

    def test_every_declared_migration_step_is_journaled(self):
        self.assertEqual(len(self.manifest["tables"]), 15)
        for step in self.manifest["steps"]:
            self.assertIn(f"apply_step('{step['key']}','{step['kind']}','{step['name']}'", self.sql)

    def test_migration_has_no_destructive_schema_operation(self):
        import re
        executable = re.sub(r"--[^\n]*", "", self.sql).upper()
        for statement in (r"\bDROP\s+TABLE\b", r"\bTRUNCATE\s+TABLE\b", r"\bDROP\s+USER\b", r"\bGRANT\s+.*\bPUBLIC\b"):
            self.assertNotRegex(executable, statement)

    def test_all_scripts_enforce_schema_and_error_stop(self):
        for name in ("phase2.sql", "phase2_verify.sql", "phase2_seed.sql", "phase2_smoke.sql",
                     "phase2_recover.sql", "phase2_seed_cleanup.sql"):
            text = (self.root / "sql/oracle" / name).read_text(encoding="utf-8")
            with self.subTest(name=name):
                self.assertIn("SESSION_USER", text)
                self.assertIn("CURRENT_SCHEMA", text)
                self.assertIn("WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK", text)

    def test_retry_does_not_ignore_existing_objects(self):
        self.assertIn("rec.script_hash=sql_hash", self.sql)
        self.assertIn("current_hash=rec.after_hash", self.sql)
        self.assertIn("state='APPLIED'", self.sql)
        self.assertIn("DISABLE PARALLEL DML", self.sql)
        self.assertNotIn("SQLCODE = -955", self.sql)

    def test_fingerprint_cannot_overwrite_journal_count(self):
        fingerprint = self.sql.split(" FUNCTION fingerprint(", 1)[1].split(" PROCEDURE apply_step(", 1)[0]
        self.assertIn("object_count NUMBER;", fingerprint)
        self.assertIn("INTO object_count FROM user_objects", fingerprint)
        self.assertIn("IF object_count=0 THEN RETURN NULL", fingerprint)
        self.assertNotRegex(fingerprint, r"\bINTO\s+n\b")
        self.assertNotIn("journal_count", fingerprint)

    def test_step_uses_its_own_journal_and_compilation_counts(self):
        step = self.sql.split(" PROCEDURE apply_step(", 1)[1].split("\nBEGIN\n DBMS_METADATA", 1)[0]
        self.assertIn("journal_count NUMBER;", step)
        self.assertIn("compilation_error_count NUMBER;", step)
        self.assertIn("INTO journal_count FROM AIPS_P2_MIGRATION WHERE step_key=k;", step)
        self.assertIn("current_hash:=fingerprint(kind,obj);\n   IF journal_count=0 THEN", step)
        self.assertIn("INTO compilation_error_count FROM user_errors", step)
        self.assertNotRegex(step, r"\bINTO\s+n\b")

    def test_assignments_require_approved_selected_proposal_member(self):
        self.assertIn("approval_action = 'APPROVED' AND selected_flag = 'Y'", self.sql)
        self.assertIn("REFERENCES APPROVAL_DECISIONS(decision_id, proposal_id, request_id, action_type)", self.sql)
        self.assertIn("REFERENCES POD_PROPOSAL_MEMBERS(proposal_id, person_id, role_in_pod, selected_flag)", self.sql)
        self.assertIn("REGEXP_LIKE(reason, '[^[:space:]]')", self.sql)

    def test_seed_uses_frontend_json_and_single_row_identity_inserts(self):
        text = (self.root / "sql/oracle/phase2_seed.sql").read_text(encoding="utf-8")
        self.assertIn("'id' VALUE d_id,'name' VALUE d_name", text)
        self.assertNotIn("INSERT ALL", text)
        self.assertNotIn("UPDATE PEOPLE", text.upper())
        self.assertIn("AIPS_BACKEND_P2_SEED_V1", text)

    def test_recovery_is_not_a_fake_ddl_rollback(self):
        text = (self.root / "sql/oracle/phase2_recover.sql").read_text(encoding="utf-8")
        self.assertIn("agents_enabled='N'", text)
        self.assertNotIn("DELETE FROM", text.upper())
        self.assertNotIn("DROP TABLE", text.upper())


if __name__ == "__main__":
    unittest.main()
