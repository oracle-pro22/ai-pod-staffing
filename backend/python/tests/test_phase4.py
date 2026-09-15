"""Decision transaction tests with offline Oracle command doubles, not live locking claims."""
import copy
import unittest
from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pydantic import ValidationError

from app.capacity import CapacityLedger, spread_hours
from app.contracts import CaptainDecision
from app.decisions import DecisionStore
from app.errors import ServiceError
from app.planning import find_options, json_text
from test_phase3 import bundle


class DecisionTests(unittest.TestCase):
    def setUp(self):
        initial = bundle()
        policy = initial.policy.model_copy(update={"status": "APPROVED", "approved_by": "business-approver", "approved_at": "2026-09-11T00:00:00Z"})
        self.data = initial.model_copy(update={"policy": policy})
        self.fresh = self.data
        self.option = find_options(self.data).options[0]
        self.actor = SimpleNamespace(subject="captain-subject", person_id="P-010", require=MagicMock())
        self.settings = SimpleNamespace(staffing_decisions_enabled=True, staffing_max_candidates=60)
        self.commands, self.committed, self.order = [], [], []
        self.fail_on = None
        self.prior = []
        self.proposal_status = "READY_FOR_REVIEW"
        self.revision = 1
        self.existing = []
        @contextmanager
        def write():
            try:
                yield None
                self.committed.extend(copy.deepcopy(self.commands))
            finally:
                self.commands.clear()
        self.store = DecisionStore(SimpleNamespace(write=write), self.settings)
        self.patches = [patch("app.decisions.rows", side_effect=self.read), patch("app.decisions.execute", side_effect=self.execute),
                        patch('app.policy_admin.rows', side_effect=lambda *_a, **_kw: [{'policy_version': self.data.policy.version}]),
                        patch("app.decisions.collect_evidence", side_effect=self.collect),
                        patch("app.notifications.rows", return_value=[{"email_address": "person@example.test"}]),
                        patch("app.notifications.execute", side_effect=self.execute)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def collect(self, *_args):
        self.order.append("fresh-capacity")
        return self.fresh

    def read(self, _connection, sql, **_binds):
        self.order.append(sql)
        if sql.startswith("SELECT request_id,policy_version"):
            return [{"request_id": "REQ-1046", "policy_version": self.data.policy.version}]
        if sql.startswith("SELECT request_revision"):
            return [{"request_revision": self.revision, "responsible_captain_id": "P-010", "status": "NEEDS_RECOMMENDATION"}]
        if sql.startswith("SELECT ur.person_id"):
            return [{"person_id": "P-010"}]
        if sql.startswith("SELECT * FROM pod_proposal_members"):
            return [{"person_id": m.person_id, "role_in_pod": m.role.value, "planned_hours": m.hours,
                "responsibilities": m.responsibilities, "deliverable_ids_json": json_text(list(m.deliverable_ids)),
                "person_skills_version": 0} for m in self.option.proposal.members]
        if sql.startswith("SELECT * FROM pod_proposals"):
            return [{"proposal_id": "PP-1", "status": self.proposal_status, "proposal_version": 1, "request_revision": 1,
                "responsible_captain_id": "P-010", "execution_id": "RUN-1", "rationale": "Evidence fit",
                "evidence_refs_json": json_text(list(self.option.proposal.evidence_refs))}]
        if sql.startswith("SELECT d.*"):
            return self.prior
        if sql.startswith("SELECT evidence_snapshot_json"):
            return [{"evidence_snapshot_json": json_text(self.data)}]
        if sql.startswith("SELECT assignment_id"):
            return self.existing
        return []

    def execute(self, _connection, sql, binds=None, *_args):
        self.order.append(sql)
        self.commands.append((sql, binds or {}))
        if self.fail_on and self.fail_on in sql:
            raise RuntimeError("Injected database failure")

    def decide(self, action="APPROVED", **overrides):
        return self.store.decide(self.actor, CaptainDecision(proposal_id="PP-1", proposal_version=1,
            action=action, idempotency_key="decision_test_000001", **overrides))

    def test_approval_commits_final_assignments_and_exact_days_without_email(self):
        result = self.decide()
        self.assertEqual(result["status"], "APPROVED")
        assignments = [(sql, binds) for sql, binds in self.committed if "INSERT INTO pod_assignments" in sql]
        days = [binds for sql, binds in self.committed if "INSERT INTO assignment_days" in sql]
        self.assertEqual(len(assignments), 2)
        self.assertEqual(sum(d["assignedHours"] for d in days), self.data.request.total_hours)
        for _sql, assignment in assignments:
            self.assertEqual(sum(d["assignedHours"] for d in days if d["assignmentId"] == assignment["assignmentId"]), assignment["assignedHours"])
        notices = [(sql, binds) for sql, binds in self.committed if "notification_outbox" in sql.lower()]
        self.assertEqual(len(notices), len(assignments))
        self.assertTrue(all("'DISABLED'" in sql for sql, _ in notices))
        self.assertTrue(any("UPDATE requests" in sql and binds["newStatus"] == "STAFFED" for sql, binds in self.committed))
        person_locks = [i for i, sql in enumerate(self.order) if sql.startswith("SELECT person_id FROM people")]
        self.assertEqual(len(person_locks), 2)
        self.assertLess(max(person_locks), self.order.index("fresh-capacity"))

    def test_rejection_requires_reason_and_creates_no_assignments(self):
        with self.assertRaises(ValidationError):
            self.decide("REJECTED", reason="   ")
        self.decide("REJECTED", reason="Need stronger launch experience")
        self.assertTrue(any("INSERT INTO approval_decisions" in sql and binds["reasonText"] == "Need stronger launch experience" for sql, binds in self.committed))
        self.assertFalse(any("INSERT INTO pod_assignments" in sql for sql, _ in self.committed))
        self.assertNotIn("fresh-capacity", self.order)

    def test_disabled_decisions_do_not_write(self):
        self.settings.staffing_decisions_enabled = False
        with self.assertRaises(ServiceError) as error:
            self.decide()
        self.assertEqual(error.exception.code, "DECISIONS_DISABLED")
        self.assertFalse(self.committed)

    def test_other_captain_cannot_decide(self):
        self.actor.person_id = "P-OTHER"
        with self.assertRaises(ServiceError) as error:
            self.decide()
        self.assertEqual(error.exception.code, "FORBIDDEN")
        self.assertFalse(self.committed)

    def test_stale_revision_prevents_decision(self):
        self.revision = 2
        with self.assertRaises(ServiceError) as error:
            self.decide()
        self.assertEqual(error.exception.code, "STALE_PROPOSAL")
        self.assertFalse(self.committed)

    def test_double_approval_is_rejected_without_new_records(self):
        self.proposal_status = "APPROVED"
        with self.assertRaises(ServiceError) as error:
            self.decide()
        self.assertEqual(error.exception.code, "ALREADY_DECIDED")
        self.assertFalse(self.committed)

    def test_same_idempotency_key_replays_after_request_revision_changes(self):
        self.prior = [{"proposal_id": "PP-1", "proposal_version": 1, "action_type": "APPROVED", "reason": None, "decision_id": "DC-1"}]
        self.revision = 2
        self.proposal_status = "APPROVED"
        result = self.decide()
        self.assertTrue(result["replayed"])
        self.assertFalse(self.committed)

    def test_idempotency_key_cannot_change_decision(self):
        self.prior = [{"proposal_id": "PP-1", "proposal_version": 1, "action_type": "APPROVED", "reason": None, "decision_id": "DC-1"}]
        with self.assertRaises(ServiceError) as error:
            self.decide("REJECTED", reason="Different team")
        self.assertEqual(error.exception.code, "IDEMPOTENCY_CONFLICT")

    def test_draft_policy_cannot_create_assignments(self):
        self.fresh = self.data.model_copy(update={"policy": self.data.policy.model_copy(update={"status": "DRAFT"})})
        with self.assertRaises(ServiceError) as error:
            self.decide()
        self.assertEqual(error.exception.code, "POLICY_NOT_APPROVED")
        self.assertFalse(self.committed)

    def test_current_workload_from_other_approval_prevents_overbooking(self):
        ledger = CapacityLedger(confirmed_work=spread_hours(Decimal(40), self.data.request.starts_on, self.data.request.ends_on))
        self.fresh = self.data.model_copy(update={"ledgers": {"P-006": ledger, "P-007": ledger}})
        with self.assertRaises(ServiceError) as error:
            self.decide()
        self.assertEqual(error.exception.code, "CAPACITY_OR_ELIGIBILITY_CHANGED")
        self.assertFalse(self.committed)

    def test_changed_skill_or_role_evidence_prevents_approval(self):
        self.fresh = self.data.model_copy(update={"candidates": ()})
        with self.assertRaises(ServiceError) as error:
            self.decide()
        self.assertEqual(error.exception.code, "STALE_PROPOSAL")
        self.assertFalse(self.committed)

    def test_assignment_day_failure_rolls_back_decision_and_assignments(self):
        self.fail_on = "INSERT INTO assignment_days"
        with self.assertRaises(RuntimeError):
            self.decide()
        self.assertFalse(self.committed)
        self.assertFalse(self.commands)

    def test_audit_failure_rolls_back_entire_approval(self):
        self.fail_on = "INSERT INTO audit_events"
        with self.assertRaises(RuntimeError):
            self.decide()
        self.assertFalse(self.committed)

    def test_existing_confirmed_request_cannot_be_assigned_again(self):
        self.existing = [{"assignment_id": "AS-other"}]
        with self.assertRaises(ServiceError) as error:
            self.decide()
        self.assertEqual(error.exception.code, "ALREADY_ASSIGNED")
        self.assertFalse(self.committed)

    def test_outbox_failure_rolls_back_approval_and_assignments(self):
        self.fail_on = 'INSERT INTO notification_outbox'
        with self.assertRaises(RuntimeError):
            self.decide()
        self.assertFalse(self.committed)


if __name__ == "__main__":
    unittest.main()
