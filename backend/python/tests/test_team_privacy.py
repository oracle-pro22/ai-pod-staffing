"""Execute the real profile predicate against a relational fixture; no external I/O."""
import json
import sqlite3
import unittest
from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from closure_sql_fixture import register_closure_day, sqlite_closure_sql

from app.assignments import ADMINISTRATOR_ONLY_SQL, AssignmentStore, team_people_scope
from app.auth import Actor, Permission
from app.capacity import CapacityLedger
from app.errors import ServiceError
from app.policy import DEFAULT_POLICY


def actor(role, scope, pid="lead"):
    return Actor("test-subject", pid, frozenset({role}),
                 (Permission(role, "TEAM_SKILLS", scope, frozenset({"view"})),))


class TeamPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        register_closure_day(self.db)
        self.db.create_function(
            "JSON_VALUE", 2,
            lambda payload, path: json.loads(payload or "{}").get(path.removeprefix("$.")),
        )
        self.addCleanup(self.db.close)
        self.db.executescript('''
            CREATE TABLE people(person_id TEXT PRIMARY KEY,active_flag TEXT);
            CREATE TABLE requests(request_id TEXT PRIMARY KEY,status TEXT);
            CREATE TABLE pod_assignments(request_id TEXT,person_id TEXT,role_in_pod TEXT,status TEXT);
            CREATE TABLE app_roles(role_code TEXT,active_flag TEXT);
            CREATE TABLE app_user_roles(person_id TEXT,role_code TEXT,active_flag TEXT,effective_from TEXT,effective_to TEXT);
        ''')
        self.db.executemany("INSERT INTO people VALUES (?,?)", [
            (pid, "N" if pid == "inactive" else "Y") for pid in (
                "lead", "member", "closed_member", "unrelated", "future_member", "admin", "inactive",
                "cancelled_member", "proposal_member", "other_lead", "member_slot_peer", "unassigned")])
        self.db.executemany("INSERT INTO requests VALUES (?,?)", [
            ("active", "STAFFED"), ("future", "STAFFED"), ("overdue", "STAFFED"),
            ("closed", "CLOSED"), ("proposed", "IN_REVIEW"), ("member_slot", "STAFFED")])
        self.db.executemany("INSERT INTO pod_assignments VALUES (?,?,?,?)", [
            ("active", "lead", "POD_LEAD", "CONFIRMED"),
            ("active", "member", "POD_MEMBER", "CONFIRMED"),
            ("active", "inactive", "POD_MEMBER", "CONFIRMED"),
            ("active", "cancelled_member", "POD_MEMBER", "CANCELLED"),
            ("future", "lead", "POD_LEAD", "CONFIRMED"),
            ("future", "future_member", "POD_MEMBER", "CONFIRMED"),
            ("closed", "lead", "POD_LEAD", "CLOSED"),
            ("closed", "closed_member", "POD_MEMBER", "CONFIRMED"),
            ("proposed", "lead", "POD_LEAD", "CONFIRMED"),
            ("proposed", "proposal_member", "POD_MEMBER", "CONFIRMED"),
            ("member_slot", "other_lead", "POD_LEAD", "CONFIRMED"),
            ("member_slot", "lead", "POD_MEMBER", "CONFIRMED"),
            ("member_slot", "member_slot_peer", "POD_MEMBER", "CONFIRMED")])
        self.db.execute("INSERT INTO app_roles VALUES ('SYSTEM_ADMINISTRATOR','Y')")
        self.db.execute("INSERT INTO app_user_roles VALUES ('admin','SYSTEM_ADMINISTRATOR','Y','2026-01-01',NULL)")
        # Extra columns for executing the complete production workspace queries,
        # not just mocking a pre-filtered list of people.
        for table, columns in {
            "people": ["full_name TEXT"],
            "requests": ["title TEXT", "project_type TEXT", "priority TEXT", "request_revision INTEGER", "responsible_captain_id TEXT", "created_at TEXT", "estimated_start_date TEXT", "estimated_completion_date TEXT"],
            "pod_assignments": ["assignment_id TEXT", "proposal_id TEXT", "starts_on TEXT", "ends_on TEXT",
                                "assigned_hours INTEGER", "closed_at TEXT", "close_reason TEXT", "policy_version TEXT"],
        }.items():
            for column in columns:
                self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column}")
        self.db.executescript('''
            UPDATE people SET full_name=person_id || ' name';
            UPDATE requests SET title=request_id,request_revision=1,responsible_captain_id='captain',created_at='2026-09-01';
            UPDATE pod_assignments SET assignment_id='A-' || rowid,proposal_id=request_id,
                starts_on='2026-09-14',ends_on='2026-09-18',assigned_hours=8,close_reason='private closure note';
            CREATE TABLE pod_proposals(proposal_id TEXT,request_id TEXT,status TEXT,request_revision INTEGER,policy_version TEXT,validation_json TEXT);
            INSERT INTO pod_proposals SELECT DISTINCT proposal_id,request_id,'APPROVED',1,'v1','{}' FROM pod_assignments;
            CREATE TABLE pod_proposal_members(proposal_id TEXT,person_id TEXT,responsibilities TEXT);
            INSERT INTO pod_proposal_members SELECT proposal_id,person_id,'Project contribution; 8 planned hours. Deliverable experience: mentor. PRIVATE-SKILL-EVIDENCE' FROM pod_assignments;
            CREATE TABLE assignment_days(assignment_id TEXT,person_id TEXT,work_date TEXT,assigned_hours INTEGER);
            INSERT INTO assignment_days SELECT assignment_id,person_id,'2026-09-14',2 FROM pod_assignments;
            CREATE TABLE load_guardrails(policy_version TEXT PRIMARY KEY,scheduling_timezone TEXT);
            INSERT INTO load_guardrails VALUES ('v1','Asia/Kolkata');
            UPDATE pod_assignments SET policy_version='v1';
            UPDATE pod_assignments SET closed_at='2026-09-16T12:00:00+00:00' WHERE status='CLOSED';
        ''')

    def visible(self, user):
        predicate, binds = team_people_scope(user, user.require("TEAM_SKILLS", "view"))
        sql = f"SELECT p.person_id FROM people p WHERE p.active_flag='Y' AND NOT ({ADMINISTRATOR_ONLY_SQL}) AND ({predicate}) ORDER BY p.person_id"
        sql = sql.replace("TRUNC(SYSDATE)", "'2026-09-14'")
        return [row[0] for row in self.db.execute(sql, binds)]

    def test_member_is_own_even_with_legacy_scoped_or_misconfigured_full(self):
        for scope in ("OWN", "SCOPED", "FULL"):
            self.assertEqual(self.visible(actor("POD_MEMBER", scope, "member")), ["member"])

    def test_lead_sees_only_self_and_confirmed_members_of_staffed_led_pods(self):
        for scope in ("SCOPED", "FULL"):
            self.assertEqual(self.visible(actor("POD_LEAD", scope)), ["future_member", "lead", "member"])
        self.assertEqual(self.visible(actor("POD_LEAD", "OWN")), ["lead"])

    def test_closure_revokes_teammate_access_but_other_active_pod_keeps_access(self):
        self.db.execute("UPDATE requests SET status='CLOSED' WHERE request_id='active'")
        self.assertNotIn("member", self.visible(actor("POD_LEAD", "SCOPED")))
        self.db.execute("INSERT INTO pod_assignments(request_id,person_id,role_in_pod,status) VALUES ('future','member','POD_MEMBER','CONFIRMED')")
        self.assertIn("member", self.visible(actor("POD_LEAD", "SCOPED")))

    def test_revoked_lead_assignment_does_not_grant_access(self):
        self.db.execute("UPDATE pod_assignments SET status='CANCELLED' WHERE person_id='lead' AND role_in_pod='POD_LEAD'")
        self.assertEqual(self.visible(actor("POD_LEAD", "SCOPED")), ["lead"])

    def test_captain_and_admin_have_active_directory_without_admin_only_account(self):
        expected = [row[0] for row in self.db.execute("SELECT person_id FROM people WHERE active_flag='Y' AND person_id<>'admin' ORDER BY person_id")]
        for role in ("POD_CAPTAIN", "SYSTEM_ADMINISTRATOR"):
            self.assertEqual(self.visible(actor(role, "FULL", "admin")), expected)
            self.assertEqual(self.visible(actor(role, "OWN", "member")), ["member"])

    def test_locked_and_unknown_roles_are_denied(self):
        with self.assertRaises(ServiceError):
            self.visible(actor("POD_MEMBER", "LOCKED"))
        with self.assertRaises(ServiceError):
            self.visible(actor("UNKNOWN", "FULL"))

    def test_team_endpoint_queries_capacity_only_for_its_allowlist(self):
        user = actor("POD_MEMBER", "SCOPED", "member")
        @contextmanager
        def read():
            yield self.db

        def query(conn, sql, **binds):
            if "COUNT(DISTINCT request_id)" in sql:
                return [{"person_id": "member", "total": 1}]
            return [dict(row) for row in conn.execute(sqlite_closure_sql(sql).replace("TRUNC(SYSDATE)", "'2026-09-14'"), binds)]

        with patch("app.assignments.rows", side_effect=query), \
             patch('app.policy_admin.active_policy_version', return_value='v1'), \
             patch("app.assignments.load_policy", return_value=DEFAULT_POLICY), \
             patch("app.assignments.load_capacity_ledgers", side_effect=lambda _connection, person_ids, *_: {
                 person_id: (CapacityLedger(), 1) for person_id in person_ids
             }) as capacity:
            result = AssignmentStore(SimpleNamespace(read=read), SimpleNamespace(staffing_policy_version="v1")).workspace(
                user, date(2026, 9, 14), "TEAM_SKILLS")
        self.assertEqual([p["person_id"] for p in result["people"]], ["member"])
        self.assertEqual(capacity.call_count, 1)
        self.assertEqual(set(capacity.call_args.args[1]), {"member"})
        for key in ("assignments", "days", "requests"):
            self.assertEqual(result[key], [])

    def test_query_failure_does_not_fall_back_to_directory(self):
        db = SimpleNamespace(read=lambda: self.db)
        with patch("app.assignments.load_policy", side_effect=RuntimeError("database failed")), self.assertRaises(RuntimeError):
            AssignmentStore(db, SimpleNamespace(staffing_policy_version="v1")).workspace(actor("POD_MEMBER", "OWN"), resource="TEAM_SKILLS")

    def workspace(self, role, scope, pid, resource="REQUESTS", team=True):
        permissions = [Permission(role, resource, "FULL", frozenset({"view", "export"}))]
        if team:
            permissions.append(Permission(role, "TEAM_SKILLS", scope, frozenset({"view"})))
        user = Actor("subject", pid, frozenset({role}), tuple(permissions))
        @contextmanager
        def read():
            yield self.db
        def query(conn, sql, **binds):
            binds = {key: value.isoformat() if isinstance(value, date) else value for key, value in binds.items()}
            return [dict(row) for row in conn.execute(sqlite_closure_sql(sql).replace("TRUNC(SYSDATE)", "'2026-09-14'"), binds)]
        with patch("app.assignments.rows", side_effect=query), \
             patch('app.policy_admin.active_policy_version', return_value='v1'), \
             patch("app.assignments.load_policy", return_value=DEFAULT_POLICY), \
             patch("app.assignments.load_capacity_ledgers", side_effect=lambda _connection, person_ids, *_: {
                 person_id: (CapacityLedger(), 1) for person_id in person_ids
             }) as capacity:
            result = AssignmentStore(SimpleNamespace(read=read), SimpleNamespace(staffing_policy_version="v1")).workspace(
                user, date(2026, 9, 14), resource)
        loaded = set(capacity.call_args.args[1]) if capacity.called else set()
        return result, loaded

    def test_member_all_resource_responses_are_own_with_basic_project_roster(self):
        for resource in ("REQUESTS", "ALLOCATION_CALENDAR", "REPORTS", "MY_AVAILABILITY"):
            for scope in ("OWN", "SCOPED", "FULL"):
                with self.subTest(resource=resource, scope=scope):
                    result, loaded = self.workspace("POD_MEMBER", scope, "member", resource)
                    self.assertEqual(loaded, {"member"})
                    self.assertEqual([p["person_id"] for p in result["people"]], ["member"])
                    self.assertEqual({d["person_id"] for d in result["days"]}, {"member"})
                    lead = next(a for a in result["assignments"] if a["person_id"] == "lead")
                    self.assertEqual(set(lead), {"assignment_id", "request_id", "person_id", "full_name", "role_in_pod", "status", "responsibilities", "staffing_method"})
                    self.assertEqual(lead["full_name"], "lead name")
                    self.assertEqual(lead["responsibilities"], "Coordinate the POD and guide delivery of the request's deliverables.")
                    self.assertNotIn("PRIVATE-SKILL-EVIDENCE", lead["responsibilities"])
                    self.assertNotIn("mentor", lead["responsibilities"])
                    self.assertNotIn("planned hours", lead["responsibilities"])
                    own = next(a for a in result["assignments"] if a["person_id"] == "member")
                    self.assertEqual(own["assigned_hours"], 8)

    def test_lead_other_response_paths_use_active_led_pods_not_historical_roster(self):
        for resource in ("REQUESTS", "ALLOCATION_CALENDAR", "REPORTS"):
            with self.subTest(resource=resource):
                result, loaded = self.workspace("POD_LEAD", "SCOPED", "lead", resource)
                self.assertEqual(loaded, {"lead", "member", "future_member"})
                self.assertEqual({p["person_id"] for p in result["people"]}, loaded)
                historical = next(a for a in result["assignments"] if a["person_id"] == "closed_member")
                self.assertNotIn("assigned_hours", historical)
                self.assertNotIn("close_reason", historical)
                self.assertTrue(all(d["person_id"] in loaded for d in result["days"]))

    def test_closure_revokes_profiles_on_requests_response_too(self):
        self.db.execute("UPDATE requests SET status='CLOSED' WHERE request_id='active'")
        result, loaded = self.workspace("POD_LEAD", "SCOPED", "lead")
        self.assertEqual(loaded, {"lead", "future_member"})
        member = next(a for a in result["assignments"] if a["person_id"] == "member")
        self.assertNotIn("assigned_hours", member)

    def test_member_keeps_own_closed_history_without_gaining_teammate_history(self):
        self.db.execute("UPDATE requests SET status='CLOSED' WHERE request_id='active'")
        self.db.execute("UPDATE pod_assignments SET status='CLOSED',closed_at='2026-09-14T12:00:00+00:00' WHERE request_id='active' AND status='CONFIRMED'")
        self.db.execute("INSERT INTO assignment_days SELECT assignment_id,person_id,'2026-09-15',2 FROM pod_assignments WHERE request_id='active'")
        result, loaded = self.workspace("POD_MEMBER", "OWN", "member")
        self.assertEqual(loaded, {'member'})
        self.assertEqual([(d['person_id'], d['work_date']) for d in result['days']], [('member', '2026-09-14')])
        own = next(a for a in result['assignments'] if a['person_id'] == 'member')
        self.assertEqual(own['status'], 'CLOSED')
        lead = next(a for a in result['assignments'] if a['person_id'] == 'lead')
        self.assertNotIn('assigned_hours', lead)
        self.assertNotIn('closed_at', lead)

    def test_overdue_indicator_is_only_for_staffed_requests_and_uses_business_today(self):
        self.db.execute("UPDATE requests SET estimated_completion_date='2000-01-01'")
        result, _ = self.workspace('POD_LEAD', 'SCOPED', 'lead')
        for request in result['requests']:
            self.assertEqual(request['past_planned_end'], request['status'] == 'STAFFED')
        self.db.execute("UPDATE requests SET estimated_completion_date='2999-01-01'")
        result, _ = self.workspace('POD_LEAD', 'SCOPED', 'lead')
        self.assertFalse(any(r['past_planned_end'] for r in result['requests']))

    def test_missing_team_permission_never_borrows_request_roster(self):
        result, loaded = self.workspace("POD_LEAD", "SCOPED", "lead", team=False)
        self.assertEqual(loaded, {"lead"})
        self.assertEqual(len(result["people"]), 1)

    def test_full_directory_in_other_workspaces_excludes_admin_and_inactive(self):
        expected = set(self.visible(actor("POD_CAPTAIN", "FULL", "admin")))
        for role in ("POD_CAPTAIN", "SYSTEM_ADMINISTRATOR"):
            result, loaded = self.workspace(role, "FULL", "admin")
            self.assertEqual(loaded, expected)
            self.assertEqual({p["person_id"] for p in result["people"]}, expected)

    def test_full_administrator_report_includes_capacity_without_team_screen_access(self):
        result, loaded = self.workspace("SYSTEM_ADMINISTRATOR", "FULL", "admin", "REPORTS", team=False)
        expected = set(self.visible(actor("POD_CAPTAIN", "FULL", "admin")))
        self.assertEqual(loaded, expected)
        self.assertEqual({person["person_id"] for person in result["people"]}, expected)


if __name__ == "__main__":
    unittest.main()
