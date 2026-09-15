"""Offline tests of the live acceptance validator; no HTTP or database calls."""
import unittest

from app.privacy_acceptance import workspace_check


class AcceptanceValidatorTests(unittest.TestCase):
    def fixture(self):
        return {"people": [{"person_id": "own"}], "days": [{"person_id": "own", "assigned_hours": 8}],
                "assignments": [{"person_id": "peer", "role_in_pod": "POD_MEMBER",
                                 "responsibilities": "Contribute to the request's deliverables with the POD lead."}]}

    def test_basic_roster_and_own_metrics_pass(self):
        workspace_check(self.fixture(), {"own"})

    def test_private_roster_fields_fail(self):
        for key in ("assigned_hours", "allocation_pct", "active_pods", "evidence", "close_reason"):
            with self.subTest(field=key), self.assertRaises(AssertionError):
                value = self.fixture()
                value["assignments"][0][key] = "private"
                workspace_check(value, {"own"})

    def test_private_details_in_free_text_fail_even_with_only_public_keys(self):
        value = self.fixture()
        value["assignments"][0]["responsibilities"] = "Write content. Deliverable experience: mentor."
        with self.assertRaises(AssertionError):
            workspace_check(value, {"own"})

    def test_foreign_capacity_and_schedule_fail(self):
        for collection in ("people", "days"):
            with self.subTest(collection=collection), self.assertRaises(AssertionError):
                value = self.fixture()
                value[collection].append({"person_id": "peer"})
                workspace_check(value, {"own"})
