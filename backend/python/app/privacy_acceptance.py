"""Local HTTP/Oracle acceptance checks. No business mutations or model calls.

Creates only short-lived local persona cookies in isolated HTTP clients. Browser
sessions are untouched. Uses independently computed expected IDs from Oracle.
Run explicitly with both local application servers running; not part of pytest.
"""
import argparse
import hashlib
import json

import httpx
import oracledb

from app.assignments import ADMINISTRATOR_ONLY_SQL
from app.config import Settings
from app.database import OracleDatabase
from app.errors import ServiceError
from app.storage import rows

ROSTER_FIELDS = {"assignment_id", "request_id", "person_id", "full_name", "role_in_pod", "status", "responsibilities"}
TABLES = ("people", "person_interests", "availability", "app_user_roles", "role_permissions", "requests",
          "requirements", "recommendations", "pod_proposals", "pod_proposal_members", "pod_assignments",
          "assignment_days", "person_capacity_days", "approval_decisions", "audit_events",
          "agent_executions", "agent_execution_events", "notification_outbox", "staffing_runtime")


def demand(condition, message):
    if not condition:
        raise AssertionError(message)


def fingerprint(db):
    """Hash full rows while LOBs are readable; print neither rows nor secrets."""
    result = {}
    def normalize(value):
        return value.read() if hasattr(value, "read") else str(value)
    previous = oracledb.defaults.fetch_lobs
    try:
        # This CLI is single-threaded. Fetch LOB contents in the row batch,
        # avoiding thousands of per-LOB Oracle network round trips.
        oracledb.defaults.fetch_lobs = False
        with db.read() as connection:
            for table in TABLES:  # Fixed application-owned identifiers, never user SQL.
                records = sorted(json.dumps(row, sort_keys=True, default=normalize) for row in rows(connection, f"SELECT * FROM {table}"))
                result[table] = hashlib.sha256("\n".join(records).encode()).hexdigest()
    finally:
        oracledb.defaults.fetch_lobs = previous
    return result


def oracle_expectations(db):
    with db.read() as connection:
        employees = {r["person_id"] for r in rows(connection,
            f"SELECT p.person_id FROM people p WHERE p.active_flag='Y' AND NOT ({ADMINISTRATOR_ONLY_SQL})")}
        staffed = {r["request_id"] for r in rows(connection, "SELECT request_id FROM requests WHERE status='STAFFED'")}
        assignments = rows(connection, "SELECT request_id,person_id,role_in_pod FROM pod_assignments WHERE status='CONFIRMED'")
    def expected(person):
        pid, role = person["person_id"], person["role_code"]
        if role in ("POD_CAPTAIN", "SYSTEM_ADMINISTRATOR"):
            return employees
        ids = {pid}
        if role == "POD_LEAD":
            led = {a["request_id"] for a in assignments if a["request_id"] in staffed
                   and a["person_id"] == pid and a["role_in_pod"] == "POD_LEAD"}
            ids.update(a["person_id"] for a in assignments if a["request_id"] in led)
        return ids & employees
    return expected


def payload(response, expected=200):
    # Do not print response bodies/cookies/tokens even on failure.
    demand(response.status_code == expected, f"{response.request.method} {response.request.url.path}: expected {expected}, got {response.status_code}")
    if expected == 200:
        demand("no-store" in response.headers.get("cache-control", ""), f"{response.request.url.path}: missing no-store")
        return response.json()
    return None


def workspace_check(snapshot, ids):
    demand({p["person_id"] for p in snapshot["people"]} <= ids, "Workspace leaked another profile's capacity")
    demand(all(d["person_id"] in ids for d in snapshot["days"]), "Workspace leaked another profile's dated hours")
    for assignment in snapshot["assignments"]:
        if assignment["person_id"] not in ids:
            demand(set(assignment) <= ROSTER_FIELDS, "Teammate roster included private fields")
            expected = ("Coordinate the POD and guide delivery of the request's deliverables."
                        if assignment["role_in_pod"] == "POD_LEAD" else
                        "Contribute to the request's deliverables with the POD lead.")
            demand(assignment["responsibilities"] == expected, "Teammate roster leaked model-authored evidence")


def check_person(origin, person, expected):
    pid, role, label = person["person_id"], person["role_code"], person["role_name"]
    with httpx.Client(base_url=origin, timeout=90, trust_env=False, headers={"Origin": origin}) as client:
        payload(client.post("/api/personas/session", json={"person_id": pid, "role_code": role}))
        token = client.cookies.get("staffing_persona_session")
        demand(bool(token), "No persona cookie was issued")
        binding = hashlib.sha256(token.encode()).hexdigest()[:32]
        client.headers["x-staffing-persona-session"] = binding
        identity = payload(client.get("/api/agentic/me"))["data"]
        demand(identity["person_id"] == pid and identity["roles"] == [role], "Persona identity mismatch")
        profile = payload(client.get("/api/agentic/workspace", params={"resource": "TEAM_SKILLS"}))["data"]
        ids = expected(person)
        demand({p["person_id"] for p in profile["people"]} == ids, "Team profile allowlist differs from Oracle assignments")
        demand(not profile["requests"] and not profile["assignments"] and not profile["days"], "Team endpoint borrowed project data")
        model = payload(client.get("/api/staffing"))["data"]
        demand({p["id"] for p in model["people"]} == ids, "Next.js serialized an incorrect full-profile list")
        demand(not model["authorization"]["userRoles"], "Next.js leaked identity-role mappings")
        request_snapshot = payload(client.get("/api/agentic/workspace", params={"resource": "REQUESTS"}))["data"]
        workspace_check(request_snapshot, ids)
        for resource in ("ALLOCATION_CALENDAR", "REPORTS", "MY_AVAILABILITY"):
            permitted = any(p["resource"] == resource and p["scope"] != "LOCKED" and "view" in p["actions"] for p in identity["permissions"])
            response = client.get("/api/agentic/workspace", params={"resource": resource})
            if permitted:
                workspace_check(payload(response)["data"], ids)
            else:
                payload(response, 403)
        if role in ("POD_MEMBER", "POD_LEAD"):
            own = payload(client.get("/api/me/skills", params={"personId": "not-the-viewer"}))["data"]
            demand(own["personId"] == pid, "Self skills accepted a foreign person ID")
        if role == "POD_MEMBER":
            demand(ids == {pid}, "Member profile scope is not OWN")
            payload(client.get("/api/people"), 403)
            payload(client.get("/api/agentic/requests"), 403)
            payload(client.get("/api/staffing", headers={"x-staffing-role": "Administrator"}), 403)
            # Read-only built-in chat uses the same profile projection.
            answer = payload(client.post("/api/chat", json={"message": "Who has available capacity?"},
                                         headers={"x-staffing-role": label}))["answer"]
            demand(person["full_name"] in answer or "No people" in answer, "Chat own-capacity response is invalid")
            for teammate in request_snapshot["assignments"]:
                if teammate["person_id"] != pid:
                    demand(teammate["full_name"] not in answer, "Chat exposed a teammate's capacity")
        payload(client.get("/api/staffing", headers={"x-staffing-persona-session": "stale-page"}), 409)
        # Sign-out affects only this script's cookie jar.
        payload(client.delete("/api/personas/session"))
        payload(client.get("/api/staffing"), 401)
        return {"role": role, "person_id": pid, "profiles": len(ids), "checks": "PASS"}


def run(env_file, port):
    settings = Settings(_env_file=env_file)
    demand(settings.backend_env == "local" and settings.staffing_demo_personas_enabled,
           "Acceptance checks require the existing local persona configuration")
    origin = f"http://127.0.0.1:{port}"
    db = OracleDatabase(settings)
    print(json.dumps({"stage": "Capturing business-data fingerprints (read-only)"}), flush=True)
    try:
        before = fingerprint(db)
    except BaseException:
        db.close()
        raise
    try:
        expected = oracle_expectations(db)
        with httpx.Client(base_url=origin, timeout=90, trust_env=False) as client:
            people = payload(client.get("/api/personas"))["personas"]
            demand(bool(people), "No local personas available")
            for person in people:
                demand(set(person) == {"person_id", "full_name", "role_code", "role_name"}, "Persona directory leaked profile details")
        for person in people:
            print(json.dumps({"checking": person["role_code"], "person_id": person["person_id"]}), flush=True)
            print(json.dumps(check_person(origin, person, expected)), flush=True)
    finally:
        try:
            print(json.dumps({"stage": "Verifying unchanged business data"}), flush=True)
            changed = [table for table, value in fingerprint(db).items() if before[table] != value]
            demand(not changed, "Business data changed during acceptance checks: " + ", ".join(changed))
            print(json.dumps({"business_fingerprints": "UNCHANGED", "tables": len(TABLES)}), flush=True)
        finally:
            db.close()
    print(json.dumps({"acceptance": "PASS", "personas": len(people), "business_writes": 0, "model_calls": 0}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--port", type=int, default=3001, choices=range(1024, 65536), metavar="PORT")
    args = parser.parse_args()
    try:
        run(args.env_file, args.port)
    except (AssertionError, ServiceError, httpx.HTTPError) as error:
        print(json.dumps({"acceptance": "FAIL", "reason": str(error) if isinstance(error, AssertionError) else type(error).__name__}), flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
