"""Multi-role access and shared-Captain regression tests; no Oracle/OCI calls."""

import json
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from test_phase3 import bundle, job

from app.auth import Actor, Permission, require_captain_decision
from app.decisions import DecisionStore
from app.engine_version import PROMPT_VERSION, new_checkpoint
from app.errors import ServiceError
from app.execution_store import ExecutionStore, assert_captain
from app.planning import json_text


def actor(*roles):
    return Actor(
        "actual-captain",
        "P-OTHER",
        frozenset(roles),
        tuple(
            Permission(role, resource, "FULL", frozenset({"view", "create", "approve"}))
            for role in roles
            for resource in ("AI_FITMENT", "AGENT_EXECUTION")
        ),
    )


class MultiRolePermissions(unittest.TestCase):
    def test_highest_role_breaks_equal_scope_tie_without_inheriting_actions(self):
        user = actor("POD_MEMBER", "POD_LEAD", "POD_CAPTAIN", "SYSTEM_ADMINISTRATOR")
        self.assertEqual(user.require("AI_FITMENT", "view").role, "SYSTEM_ADMINISTRATOR")
        self.assertEqual(user.require("AI_FITMENT", "approve", "POD_CAPTAIN").role, "POD_CAPTAIN")
        require_captain_decision(user, "P-OWNER")
        with self.assertRaises(ServiceError):
            require_captain_decision(actor("SYSTEM_ADMINISTRATOR"), "P-OWNER")

    def test_locked_admin_does_not_mask_granted_captain_read(self):
        user = actor("POD_CAPTAIN")
        user = Actor(
            user.subject,
            user.person_id,
            user.roles | {"SYSTEM_ADMINISTRATOR"},
            (*user.permissions, Permission("SYSTEM_ADMINISTRATOR", "AGENT_EXECUTION", "LOCKED", frozenset())),
        )
        ExecutionStore.authorize_read(user, "P-OWNER")

    def test_narrow_action_permission_does_not_borrow_broader_read_scope(self):
        user = Actor(
            "id",
            "P-OTHER",
            frozenset({"SYSTEM_ADMINISTRATOR", "POD_CAPTAIN"}),
            (
                Permission("SYSTEM_ADMINISTRATOR", "AI_FITMENT", "FULL", frozenset({"view"})),
                Permission("POD_CAPTAIN", "AI_FITMENT", "OWN", frozenset({"view", "approve"})),
            ),
        )
        self.assertEqual(user.require("AI_FITMENT", "approve").scope, "OWN")
        with self.assertRaises(ServiceError):
            require_captain_decision(user, "P-OWNER")


class CurrentCaptainChecks(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.addCleanup(self.connection.close)
        self.connection.executescript("""
          CREATE TABLE people(person_id TEXT,active_flag TEXT);
          CREATE TABLE app_user_roles(identity_subject TEXT,person_id TEXT,role_code TEXT,active_flag TEXT,effective_from TEXT,effective_to TEXT);
          CREATE TABLE app_roles(role_code TEXT,active_flag TEXT);
          CREATE TABLE role_permissions(role_code TEXT,resource_code TEXT,can_view TEXT,can_approve TEXT,can_create TEXT,access_scope TEXT);
          CREATE TABLE app_accounts(identity_subject TEXT,person_id TEXT,active_flag TEXT);
          INSERT INTO people VALUES ('P-OTHER','Y');
          INSERT INTO app_roles VALUES ('POD_CAPTAIN','Y');
          INSERT INTO app_user_roles VALUES ('actual-captain','P-OTHER','POD_CAPTAIN','Y','2026-01-01',NULL);
          INSERT INTO role_permissions VALUES ('POD_CAPTAIN','AI_FITMENT','Y','Y','Y','FULL');
          INSERT INTO role_permissions VALUES ('POD_CAPTAIN','AGENT_EXECUTION','Y','Y','Y','FULL');
          INSERT INTO app_accounts VALUES ('actual-captain','P-OTHER','Y');
        """)

        def query(conn, sql, **binds):
            return [dict(row) for row in conn.execute(sql.replace("TRUNC(SYSDATE)", "'2026-09-23'"), binds)]

        for module in ("app.decisions", "app.execution_store"):
            mock = patch(module + ".rows", side_effect=query)
            mock.start()
            self.addCleanup(mock.stop)

    def check(self, owner="P-OWNER"):
        DecisionStore.authorize(self.connection, actor("POD_CAPTAIN"), owner)
        assert_captain(self.connection, "actual-captain", "P-OTHER", owner)

    def test_current_captain_can_act_cross_owner_and_on_self(self):
        self.check()
        self.check("P-OTHER")

    def test_disabled_account_cannot_run_or_approve_even_with_active_role(self):
        self.connection.execute("UPDATE app_accounts SET active_flag='N'")
        with self.assertRaises(ServiceError):
            self.check()
        with self.assertRaises(ServiceError):
            assert_captain(self.connection, "actual-captain", "P-OTHER", "P-OWNER")

    def test_old_subject_cannot_bypass_disabled_canonical_account(self):
        self.connection.execute(
            "UPDATE app_accounts SET active_flag='N',identity_subject='new-canonical-subject'"
        )
        with self.assertRaises(ServiceError):
            self.check()

    def test_revoked_expired_or_narrow_grants_cannot_act_cross_owner(self):
        for update in (
            "UPDATE app_user_roles SET active_flag='N'",
            "UPDATE app_user_roles SET effective_to='2026-09-01'",
            "UPDATE role_permissions SET access_scope='OWN'",
            "UPDATE role_permissions SET can_view='N'",
        ):
            with self.subTest(update=update):
                self.connection.execute("SAVEPOINT scenario")
                self.connection.execute(update)
                with self.assertRaises(ServiceError):
                    self.check()
                self.connection.execute("ROLLBACK TO scenario")

    def test_identity_cannot_be_relinked_to_another_person_in_request(self):
        with self.assertRaises(ServiceError):
            DecisionStore.authorize(
                self.connection, Actor("actual-captain", "P-OWNER", frozenset({"POD_CAPTAIN"}), ()), "P-OWNER"
            )


class ExecutionProvenance(unittest.TestCase):
    def test_cross_captain_enqueue_preserves_owner_and_actual_actor_separately(self):
        data = bundle()
        store = ExecutionStore(MagicMock(), SimpleNamespace(backend_env="local", oci_genai_model_id="model"))
        request = {
            "request_revision": 1,
            "responsible_captain_id": "P-OWNER",
            "status": "NEEDS_RECOMMENDATION",
            "agent_enabled": "Y",
        }
        with (
            patch.object(store, "require_enabled"),
            patch.object(store, "event"),
            patch("app.policy_admin.rows", return_value=[{"policy_version": data.policy.version}]),
            patch("app.manual_store.pending_manual", return_value=None),
            patch("app.execution_store.rows", side_effect=[[request], [], []]),
            patch("app.execution_store.load_policy", return_value=data.policy),
            patch("app.execution_store.assert_captain") as authorize,
            patch("app.execution_store.execute") as write,
        ):
            store.enqueue("REQ-1046", "actual-captain", "P-OTHER", "unique-key")
        values = write.call_args.args[2]
        saved = json.loads(values["requestJson"])
        self.assertEqual(saved["responsible_captain_id"], "P-OWNER")
        self.assertEqual(saved["requester_person_id"], "P-OTHER")
        self.assertEqual(values["actorSubject"], "actual-captain")
        self.assertEqual(authorize.call_args.args[1:], ("actual-captain", "P-OTHER", "P-OWNER"))

    def test_claim_restores_requester_for_checkpoint_resume(self):
        data = bundle()
        database = MagicMock()
        database.write.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value.fetchone.return_value = (
            "RUN-1",
        )
        store = ExecutionStore(
            database, SimpleNamespace(oci_genai_model_id="model", staffing_lease_seconds=180)
        )
        record = {
            "attempt_count": 0,
            "max_attempts": 3,
            "checkpoint_json": json_text(new_checkpoint()),
            "prompt_version": PROMPT_VERSION,
            "model_id": "model",
            "evidence_snapshot_json": json_text(data),
            "request_snapshot_json": json_text(
                {"responsible_captain_id": "P-OWNER", "requester_person_id": "P-OTHER"}
            ),
            "request_id": data.request.request_id,
            "request_revision": 1,
            "policy_version": data.policy.version,
            "created_by": "actual-captain",
        }
        with (
            patch("app.execution_store.rows", return_value=[record]),
            patch("app.execution_store.execute"),
            patch.object(store, "event"),
            patch.object(store, "require_enabled"),
        ):
            resumed = store.claim("worker")
        self.assertEqual(resumed.requester_person_id, "P-OTHER")
        self.assertEqual(resumed.created_by, "actual-captain")

    def test_evidence_load_revalidates_requester_not_request_owner(self):
        data = bundle()
        item = job()
        item.created_by = "actual-captain"
        store = ExecutionStore(MagicMock(), SimpleNamespace(staffing_max_candidates=60, backend_env="local"))
        owner = data.request.responsible_captain_id
        request = {"request_revision": 1, "responsible_captain_id": owner, "status": "NEEDS_RECOMMENDATION"}
        snapshot = {
            "responsible_captain_id": owner,
            "requester_person_id": "P-OTHER",
            "policy": data.policy.model_dump(mode="json"),
        }
        with (
            patch.object(store, "require_enabled"),
            patch("app.execution_store.require_current_policy"),
            patch(
                "app.execution_store.rows",
                side_effect=[[request], [{"request_snapshot_json": json_text(snapshot)}]],
            ),
            patch("app.execution_store.collect_evidence", return_value=data),
            patch("app.execution_store.assert_captain") as authorize,
        ):
            self.assertEqual(store.load_evidence(item), data)
        self.assertEqual(authorize.call_args.args[1:], ("actual-captain", "P-OTHER", owner))


if __name__ == "__main__":
    unittest.main()
