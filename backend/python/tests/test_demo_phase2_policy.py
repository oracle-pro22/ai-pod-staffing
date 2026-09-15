"""Offline compatibility/decision checks; SQL checks do not claim live Oracle execution."""
import json
import unittest
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from app.capacity import CapacityLedger, DailyHours
from app.contracts import DeliverableEvidence
from app.decisions import published_member
from app.errors import ServiceError
from app.planning import json_text
from app.policy import DEFAULT_POLICY, SchedulingRules, StaffingPolicy
from app.storage import load_policy
import test_phase4


def policy_records(version="staffing-demo-v2", scheduling=True):
    policy = {"policy_version": version, "status": "DRAFT", "approved_by": None, "approved_at": None,
              "default_weekly_hours": 40, "maximum_allocation_pct": 100, "scheduling_timezone": "Asia/Kolkata",
              "skill_weight": 50, "deliverable_weight": 30, "capacity_weight": 15, "interest_weight": 5}
    documents = {"MINIMUM_STRENGTH": {"value": 3}, "LEAD_ROLE": {"value": "POD_LEAD"},
                 "MEMBER_ROLES": {"value": ["POD_MEMBER", "POD_LEAD"]}, "MAX_AGENT_STEPS": {"value": 12}}
    if scheduling:
        documents["MAX_AGENT_STEPS"]["scheduling"] = SchedulingRules().model_dump(mode="json")
    return policy, documents


class SchedulingPolicyTests(unittest.TestCase):
    def load(self, version="staffing-demo-v2", scheduling=True, mutate=None, native=True):
        policy, documents = policy_records(version, scheduling)
        if mutate:
            mutate(documents)
        rules = [{"rule_code": code, "rule_value_json": value if native else json.dumps(value)}
                 for code, value in documents.items()]
        with patch("app.storage.rows", side_effect=[[policy], rules]):
            return load_policy(None, version)

    def test_v2_json_native_and_text_decodes_explicit_rules(self):
        for native in (True, False):
            with self.subTest(native=native):
                result = self.load(native=native)
                self.assertEqual(result.scheduling, SchedulingRules())
                self.assertEqual(result.maximum_agent_steps, 12)
                self.assertEqual(result.status, "DRAFT")

    def test_old_policy_keeps_legacy_schedule_and_snapshot_defaults(self):
        old = self.load(version="staffing-baseline-v1", scheduling=False)
        self.assertIsNone(old.scheduling)
        previous_snapshot = DEFAULT_POLICY.model_dump(mode="json", exclude={"scheduling"})
        self.assertEqual(StaffingPolicy.model_validate(previous_snapshot), DEFAULT_POLICY)

    def test_known_v2_policy_cannot_silently_fall_back_to_legacy(self):
        with self.assertRaises(ServiceError) as caught:
            self.load(scheduling=False)
        self.assertEqual(caught.exception.code, "INVALID_POLICY")

    def test_malformed_scheduling_configuration_fails_closed(self):
        for value in (None, [], {}, {"algorithm": "available-days-v2"},
                      {"algorithm": "equal-spread", "minimum_member_hours": 1, "minimum_equal_share_pct": 50},
                      {"algorithm": "available-days-v2", "minimum_member_hours": 0, "minimum_equal_share_pct": 50},
                      {"algorithm": "available-days-v2", "minimum_member_hours": "NaN", "minimum_equal_share_pct": 50},
                      {"algorithm": "available-days-v2", "minimum_member_hours": 1, "minimum_equal_share_pct": 101},
                      {"algorithm": "available-days-v2", "minimum_member_hours": 1, "minimum_equal_share_pct": 50, "ignore_leave": True}):
            with self.subTest(value=value), self.assertRaises(ServiceError) as caught:
                self.load(mutate=lambda docs: docs["MAX_AGENT_STEPS"].update(scheduling=value))
            self.assertEqual(caught.exception.code, "INVALID_POLICY")

    def test_unexpected_rule_fields_are_not_ignored(self):
        with self.assertRaises(ServiceError):
            self.load(mutate=lambda docs: docs["MINIMUM_STRENGTH"].update(scheduling={}))


class PublishedScheduleTests(unittest.TestCase):
    def setUp(self):
        # Reuse the existing transaction double without inheriting/re-running
        # its unrelated tests. All database writes remain mocked.
        self.h = test_phase4.DecisionTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        policy = self.h.data.policy.model_copy(update={"version": "staffing-demo-v2", "scheduling": SchedulingRules()})
        evidence = DeliverableEvidence(deliverable_id="DEL-001", experience_level="INDEPENDENT",
                                       contribution_scope="END_TO_END", experience="Delivered a complete launch package.")
        people = tuple(p.model_copy(update={"deliverables": (evidence,), "skills": tuple(
            s.model_copy(update={"evidence": "Created launch messaging for a completed service release."})
            for s in p.skills)}) for p in self.h.data.candidates)
        self.friday = self.h.data.request.ends_on
        ledgers = {p.person_id: CapacityLedger(absences=(DailyHours(day=self.friday, hours=8),)) for p in people}
        self.h.data = self.h.data.model_copy(update={"policy": policy, "candidates": people, "ledgers": ledgers})
        self.h.fresh = self.h.data
        members = tuple(m.model_copy(update={"daily_schedule": tuple(
            DailyHours(day=self.h.data.request.starts_on + timedelta(days=i), hours=Decimal("2.5")) for i in range(4))})
            for m in self.h.option.proposal.members)
        self.h.option = self.h.option.model_copy(update={"proposal": self.h.option.proposal.model_copy(
            update={"policy_version": policy.version, "members": members})})
        self.factor_override = None
        original = self.h.read

        def read(connection, sql, **binds):
            records = original(connection, sql, **binds)
            if sql.startswith("SELECT * FROM pod_proposal_members"):
                for record in records:
                    member = next(m for m in members if m.person_id == record["person_id"])
                    factors = {"scheduling_algorithm": policy.scheduling.algorithm,
                               "daily_schedule": [d.model_dump(mode="json") for d in member.daily_schedule]}
                    if self.factor_override:
                        self.factor_override(factors)
                    record["factors_json"] = json_text(factors)
            return records
        self.h.patches[0].target.rows.side_effect = read

    def test_approval_preserves_exact_published_days_without_friday_work(self):
        self.h.decide()
        days = [binds for sql, binds in self.h.committed if "INSERT INTO assignment_days" in sql]
        self.assertEqual(len(days), 8)
        self.assertTrue(all(d["workDay"] < self.friday for d in days))
        self.assertTrue(all(d["assignedHours"] == Decimal("2.5") for d in days))
        self.assertEqual(sum(d["assignedHours"] for d in days), Decimal(20))

    def test_new_absence_rejects_original_schedule_even_if_other_days_have_room(self):
        monday = self.h.data.request.starts_on
        self.h.fresh = self.h.data.model_copy(update={"ledgers": {p.person_id: CapacityLedger(
            absences=(DailyHours(day=monday, hours=8), DailyHours(day=self.friday, hours=8)))
            for p in self.h.data.candidates}})
        with self.assertRaises(ServiceError) as caught:
            self.h.decide()
        self.assertEqual(caught.exception.code, "CAPACITY_OR_ELIGIBILITY_CHANGED")
        self.assertFalse(self.h.committed)

    def test_missing_or_mismatched_schedule_never_respreads(self):
        for mutation in (lambda f: f.pop("daily_schedule"),
                         lambda f: f.update(scheduling_algorithm="equal-weekdays-v1"),
                         lambda f: f.update(daily_schedule=[]),
                         lambda f: f["daily_schedule"][0].update(hours="0.04")):
            self.factor_override = mutation
            with self.subTest(mutation=mutation), self.assertRaises(ServiceError) as caught:
                self.h.decide()
            self.assertEqual(caught.exception.code, "INVALID_PUBLISHED_SCHEDULE")
            self.assertFalse(self.h.committed)

    def test_saved_legacy_member_retains_no_explicit_schedule_requirement(self):
        m = self.h.option.proposal.members[0]
        record = {"person_id": m.person_id, "role_in_pod": m.role, "planned_hours": m.hours,
                  "responsibilities": m.responsibilities, "deliverable_ids_json": json_text(list(m.deliverable_ids))}
        self.assertEqual(published_member(record, DEFAULT_POLICY).daily_schedule, ())


class PolicySqlStaticTests(unittest.TestCase):
    def setUp(self):
        self.sql = (Path(__file__).resolve().parents[3] / "sql/oracle/demo_phase2_policy.sql").read_text(encoding="utf-8")
        self.body = "\n".join(line for line in self.sql.splitlines() if not line.lstrip().startswith("--")).upper()

    def test_additive_transaction_requires_explicit_approval(self):
        self.assertIn("APPROVE_POLICY CONSTANT BOOLEAN := FALSE", self.body)
        self.assertIn("REPLACE_WITH_YOUR_NAME", self.body)
        self.assertIn("IF APPROVE_POLICY AND CURRENT_STATUS='DRAFT' THEN", self.body)
        self.assertIn("COMMIT;", self.body)
        self.assertIn("EXCEPTION WHEN OTHERS THEN\n  ROLLBACK;", self.body)
        self.assertNotIn("CREATE TABLE", self.body)
        self.assertNotIn("ALTER TABLE", self.body)
        self.assertNotIn("DELETE FROM", self.body)

    def test_four_rules_and_strict_idempotency_without_runtime_mutations(self):
        self.assertEqual(self.body.count("INSERT INTO ELIGIBILITY_RULES"), 4)
        self.assertIn("DBMS_LOB.COMPARE", self.body)
        self.assertIn("IF N=0 THEN", self.body)
        self.assertIn("LOCK TABLE STAFFING_POLICIES IN EXCLUSIVE MODE NOWAIT", self.body)
        self.assertNotIn("UPDATE STAFFING_RUNTIME", self.body)
        self.assertNotIn("UPDATE POD_ASSIGNMENTS", self.body)
        self.assertNotIn("UPDATE REQUESTS", self.body)
        self.assertIn('"MINIMUM_MEMBER_HOURS":1', self.body)
        self.assertIn('"MINIMUM_EQUAL_SHARE_PCT":50', self.body)


if __name__ == "__main__":
    unittest.main()
