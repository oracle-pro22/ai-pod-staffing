"""Local persona sessions never grant roles or write business/session records."""
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth import Actor, AuthorizationRepository, Permission, TokenVerifier
from app.config import Settings
from app.errors import ServiceError
from app.main import create_app
from app.personas import (SESSION_SECONDS, TOKEN_PURPOSE, PersonaRepository, PersonaSelection,
                          _encode_claims, constrain_actor, mint_session, require_management, verify_persona_token)

MANAGEMENT_TOKEN = "local-management-test-token-" + "x" * 40
ROLE_NAMES = {"POD_CAPTAIN": "POD Captain", "POD_LEAD": "POD Lead", "POD_MEMBER": "POD Member",
              "SYSTEM_ADMINISTRATOR": "Administrator"}


def settings(**changes):
    return Settings(backend_env="local", backend_auth_mode="local", backend_local_token=MANAGEMENT_TOKEN,
                    staffing_demo_personas_enabled=True, **changes)


def selection(person_id="P-009", role="POD_CAPTAIN"):
    return PersonaSelection(person_id=person_id, role_code=role)


def actor(person_id="P-009", roles=("POD_CAPTAIN",)):
    return Actor(f"demo:d1:{person_id}", person_id, frozenset(roles), tuple(
        Permission(role, "REQUESTS", "FULL", frozenset({"view", "create"})) for role in roles))


class PersonaSettingsTests(unittest.TestCase):
    def test_disabled_is_default_and_existing_fixed_identity_remains(self):
        value = Settings(backend_auth_mode="local", backend_local_token=MANAGEMENT_TOKEN,
                         backend_local_subject="existing-subject")
        self.assertFalse(value.staffing_demo_personas_enabled)
        self.assertEqual(TokenVerifier(value).subject("Bearer " + MANAGEMENT_TOKEN), "existing-subject")

    def test_flag_cannot_be_used_in_test_production_or_oidc_modes(self):
        for environment, mode in (("test", "local"), ("production", "local"), ("local", "oidc")):
            with self.subTest(environment=environment, mode=mode), self.assertRaises(ValidationError):
                Settings(backend_env=environment, backend_auth_mode=mode,
                         backend_local_token=MANAGEMENT_TOKEN, staffing_demo_personas_enabled=True)

    def test_persona_mode_requires_secret_but_not_fixed_captain_subject(self):
        self.assertEqual(settings().backend_local_subject, "")
        with self.assertRaises(ValidationError):
            Settings(backend_auth_mode="local", staffing_demo_personas_enabled=True)


class PersonaTokenTests(unittest.TestCase):
    def setUp(self):
        self.settings = settings()
        self.now = 2_000_000_000

    def test_each_official_role_gets_purpose_bound_expiring_session(self):
        for role in ROLE_NAMES:
            with self.subTest(role=role):
                session = mint_session(selection(role=role), self.settings, now=self.now)
                identity = verify_persona_token("Bearer " + session["access_token"], self.settings, now=self.now)
                self.assertEqual(identity.role_code, role)
                self.assertEqual(identity.sub, "demo:d1:P-009")
                self.assertEqual(identity.exp - identity.iat, SESSION_SECONDS)
                self.assertEqual(session["expires_in"], SESSION_SECONDS)
                self.assertNotIn(MANAGEMENT_TOKEN, session["access_token"])

    def test_tokens_use_random_nonces_and_do_not_act_as_management_credentials(self):
        first = mint_session(selection(), self.settings)
        second = mint_session(selection(), self.settings)
        self.assertNotEqual(first["access_token"], second["access_token"])
        with self.assertRaises(ServiceError):
            require_management(self.settings, "Bearer " + first["access_token"], "127.0.0.1")
        with self.assertRaises(ServiceError):
            TokenVerifier(self.settings).subject("Bearer " + MANAGEMENT_TOKEN)

    def test_expired_and_future_tokens_are_rejected(self):
        session = mint_session(selection(), self.settings, now=self.now)
        for current in (self.now - 1, self.now + SESSION_SECONDS, self.now + SESSION_SECONDS + 1):
            with self.subTest(current=current), self.assertRaises(ServiceError) as error:
                verify_persona_token("Bearer " + session["access_token"], self.settings, now=current)
            self.assertEqual(error.exception.code, "UNAUTHENTICATED")

    def test_tampered_key_payload_and_prefix_are_rejected(self):
        token = mint_session(selection(), self.settings, now=self.now)["access_token"]
        prefix, payload, signature = token.split(".")
        for value in (f"{prefix}.{payload}x.{signature}", f"wrong.{payload}.{signature}", token + "x", "unsigned"):
            with self.subTest(value=value[:8]), self.assertRaises(ServiceError):
                verify_persona_token("Bearer " + value, self.settings, now=self.now)
        different = self.settings.model_copy(update={"backend_local_token": settings().backend_local_token.__class__("z" * 50)})
        with self.assertRaises(ServiceError):
            verify_persona_token("Bearer " + token, different, now=self.now)

    def test_claim_purpose_seed_prefix_person_role_and_duration_are_validated(self):
        claims = {"purpose": TOKEN_PURPOSE, "sub": "demo:d1:P-009", "person_id": "P-009",
                  "role_code": "POD_CAPTAIN", "iat": self.now, "exp": self.now + SESSION_SECONDS, "nonce": "n" * 24}
        for change in ({"purpose": "other-purpose"}, {"sub": "seed:backend-p2:P-009"},
                       {"sub": "demo:d1:P-010"}, {"person_id": "P-010"}, {"role_code": "UNKNOWN"},
                       {"iat": True}, {"exp": self.now + SESSION_SECONDS + 1}, {"nonce": "short"},
                       {"extra": "not-permitted"}):
            with self.subTest(change=change), self.assertRaises(ServiceError):
                verify_persona_token("Bearer " + _encode_claims({**claims, **change}, self.settings), self.settings, now=self.now)

    def test_selected_role_cannot_inherit_other_roles_permissions(self):
        session = mint_session(selection(role="POD_MEMBER"), self.settings, now=self.now)
        identity = verify_persona_token("Bearer " + session["access_token"], self.settings, now=self.now)
        result = constrain_actor(actor(roles=("POD_MEMBER", "SYSTEM_ADMINISTRATOR")), identity)
        self.assertEqual(result.roles, frozenset({"POD_MEMBER"}))
        self.assertEqual({permission.role for permission in result.permissions}, {"POD_MEMBER"})

    def test_cross_person_and_revoked_role_are_rejected_after_signature_verification(self):
        session = mint_session(selection(), self.settings, now=self.now)
        identity = verify_persona_token("Bearer " + session["access_token"], self.settings, now=self.now)
        for current in (actor(person_id="P-010"), actor(roles=("POD_MEMBER",))):
            with self.subTest(current=current.person_id), self.assertRaises(ServiceError):
                constrain_actor(current, identity)


class PersonaApiTests(unittest.TestCase):
    def setUp(self):
        self.database, self.authorization = MagicMock(), MagicMock()
        self.authorization.resolve.return_value = actor()
        self.settings = settings()
        self.app = create_app(self.settings, self.database, authorization=self.authorization)
        self.client = TestClient(self.app, client=("127.0.0.1", 12345))
        self.headers = {"Authorization": "Bearer " + MANAGEMENT_TOKEN}

    def test_directory_is_name_only_and_read_only(self):
        roster = [{"person_id": "P-009", "full_name": "Indranie Balkaran", "role_code": "POD_CAPTAIN", "role_name": "POD Captain"}]
        with patch("app.personas.rows", return_value=roster) as query:
            response = self.client.get("/v1/local-personas", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"personas": roster})
        sql = query.call_args.args[1]
        for text in ("p.active_flag='Y'", "ur.active_flag='Y'", "ar.active_flag='Y'",
                     "ur.identity_subject='demo:d1:' || p.person_id", "effective_from", "effective_to"):
            self.assertIn(text, sql)
        for field in ("location", "job_title", "skills"):
            self.assertNotIn(field, sql)
        self.database.write.assert_not_called()

    def test_all_four_roles_can_enter_using_only_current_roster(self):
        for index, (role, name) in enumerate(ROLE_NAMES.items(), start=1):
            person_id = f"P-{index:03}"
            with self.subTest(role=role), patch("app.personas.rows", return_value=[{
                "person_id": person_id, "full_name": "Selected person", "role_code": role, "role_name": name}]):
                response = self.client.post("/v1/local-personas/session", headers=self.headers,
                                            json={"person_id": person_id, "role_code": role})
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(set(data), {"access_token", "expires_in", "person_id", "role_code"})
            self.authorization.resolve.return_value = actor(person_id, (role,))
            me = self.client.get("/v1/me", headers={"Authorization": "Bearer " + data["access_token"]})
            self.assertEqual(me.status_code, 200)
            self.assertEqual(me.json()["roles"], [role])
            self.assertEqual(me.json()["person_id"], person_id)
        self.database.write.assert_not_called()

    def test_management_token_never_falls_back_to_fixed_captain(self):
        response = self.client.get("/v1/me", headers=self.headers)
        self.assertEqual(response.status_code, 401)
        self.authorization.resolve.assert_not_called()

    def test_member_token_cannot_gain_captain_actions_from_header(self):
        token = mint_session(selection(role="POD_MEMBER"), self.settings)["access_token"]
        self.authorization.resolve.return_value = actor(roles=("POD_MEMBER", "POD_CAPTAIN"))
        response = self.client.post("/v1/requests/REQ-1047/executions",
            headers={"Authorization": "Bearer " + token, "x-staffing-role": "POD Captain"},
            json={"idempotency_key": "test-persona-1234"})
        self.assertEqual(response.status_code, 403)
        self.database.write.assert_not_called()

    def test_signed_persona_cannot_list_or_mint_more_personas(self):
        token = mint_session(selection(), self.settings)["access_token"]
        headers = {"Authorization": "Bearer " + token}
        for method, path, body in (("GET", "/v1/local-personas", None),
                                   ("POST", "/v1/local-personas/session", {"person_id": "P-009", "role_code": "POD_CAPTAIN"})):
            response = self.client.request(method, path, headers=headers, json=body)
            self.assertEqual(response.status_code, 401)
        self.database.read.assert_not_called()

    def test_non_loopback_cannot_use_management_even_with_forwarded_header(self):
        client = TestClient(self.app, client=("192.0.2.10", 12345))
        response = client.get("/v1/local-personas", headers={**self.headers, "X-Forwarded-For": "127.0.0.1"})
        self.assertEqual(response.status_code, 403)
        self.database.read.assert_not_called()

    def test_session_selection_contract_rejects_extra_identity_claims(self):
        for change in ({"role_code": "UNKNOWN"}, {"sub": "demo:d1:P-010"}, {"expires_in": 999999}, {"person_id": True}):
            with self.subTest(change=change):
                response = self.client.post("/v1/local-personas/session", headers=self.headers,
                    json={"person_id": "P-009", "role_code": "POD_CAPTAIN", **change})
            self.assertEqual(response.status_code, 422)
        self.database.read.assert_not_called()

    def test_no_longer_active_or_unmapped_selection_is_rejected(self):
        with patch("app.personas.rows", return_value=[]):
            response = self.client.post("/v1/local-personas/session", headers=self.headers,
                                        json={"person_id": "P-009", "role_code": "POD_CAPTAIN"})
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("access_token", response.json())

    def test_normal_requests_resolve_current_permissions_every_time_and_reject_revocation(self):
        token = mint_session(selection(), self.settings)["access_token"]
        headers = {"Authorization": "Bearer " + token}
        self.assertEqual(self.client.get("/v1/me", headers=headers).status_code, 200)
        self.authorization.resolve.side_effect = ServiceError("IDENTITY_NOT_LINKED", "No active mapping", 403)
        self.assertEqual(self.client.get("/v1/me", headers=headers).status_code, 403)
        self.assertEqual(self.authorization.resolve.call_count, 2)

    def test_disabled_endpoints_cannot_be_used(self):
        value = Settings(backend_auth_mode="local", backend_local_token=MANAGEMENT_TOKEN,
                         backend_local_subject="existing-subject")
        client = TestClient(create_app(value, self.database), client=("127.0.0.1", 12345))
        response = client.get("/v1/local-personas", headers=self.headers)
        self.assertEqual(response.status_code, 404)
        self.database.read.assert_not_called()


class RepositoryRevocationTests(unittest.TestCase):
    def test_full_name_is_loaded_without_changing_permission_columns(self):
        database = MagicMock()
        cursor = database.read.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [("P-009", "POD_CAPTAIN", "REQUESTS", "OWN", "Y", "Y", "N", "N", "N", "N", "Indranie Balkaran")]
        current = AuthorizationRepository(database).resolve("demo:d1:P-009")
        self.assertEqual(current.full_name, "Indranie Balkaran")
        self.assertEqual(current.permissions[0].actions, frozenset({"view", "create"}))
        identity = verify_persona_token("Bearer " + mint_session(selection(), settings())["access_token"], settings())
        self.assertEqual(constrain_actor(current, identity).full_name, "Indranie Balkaran")
        database.write.assert_not_called()

    def test_inactive_person_or_roles_yield_no_identity_and_never_write(self):
        database = MagicMock()
        cursor = database.read.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = []
        with self.assertRaises(ServiceError) as error:
            AuthorizationRepository(database).resolve("demo:d1:P-009")
        self.assertEqual(error.exception.code, "IDENTITY_NOT_LINKED")
        sql = cursor.execute.call_args.args[0]
        self.assertIn("p.active_flag = 'Y'", sql)
        self.assertIn("aur.active_flag = 'Y'", sql)
        database.write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
