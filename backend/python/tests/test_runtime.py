"""Offline runtime tests. Missing dependencies are an explicit skip, never a mocked installation."""
# ruff: noqa: E402 -- Skip explicitly before importing optional, uninstalled runtime dependencies.
import importlib.util
import os
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

MISSING = [name for name in ("fastapi", "httpx", "jwt", "oracledb", "pydantic_settings")
           if importlib.util.find_spec(name) is None]
if MISSING:
    raise unittest.SkipTest("Runtime dependencies not installed: " + ", ".join(MISSING))

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth import Actor, AuthorizationRepository, Permission, TokenVerifier, require_captain_decision, require_own_person
from app.config import Settings
from app.database import OracleDatabase
from app.errors import ServiceError
from app.main import create_app


def captain():
    return Actor("identity-1", "P-010", frozenset({"POD_CAPTAIN"}), (
        Permission("POD_CAPTAIN", "AI_FITMENT", "FULL", frozenset({"view", "approve"})),
        Permission("POD_CAPTAIN", "AGENT_EXECUTION", "FULL", frozenset({"view"})),
    ))


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_local_auth_is_forbidden_in_production(self):
        with self.assertRaises(ValidationError):
            Settings(backend_env="production", backend_auth_mode="local",
                     backend_local_token="x" * 32, backend_local_subject="identity-1")

    def test_pool_and_schema_bounds(self):
        for values in ({"db_pool_min": 3, "db_pool_max": 2}, {"db_user": "ADMIN"},
                       {"oidc_jwks_url": "http://identity.example/keys"}):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                Settings(**values)

    def test_local_token_missing_wrong_and_unicode(self):
        verifier = TokenVerifier(Settings(backend_auth_mode="local", backend_local_token="x" * 32,
                                          backend_local_subject="identity-1"))
        for header in (None, "Bearer wrong", "Bearer \u2603", "Basic abc"):
            with self.subTest(header=header), self.assertRaises(ServiceError) as error:
                verifier.subject(header)
            self.assertEqual(error.exception.status, 401)
        self.assertEqual(verifier.subject("Bearer " + "x" * 32), "identity-1")

    def test_valid_jwt_and_claim_validation(self):
        settings = Settings(oidc_issuer="https://id.example", oidc_audience="staffing",
                            oidc_jwks_url="https://id.example/keys")
        verifier = TokenVerifier(settings)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        verifier.jwks = MagicMock()
        verifier.jwks.get_signing_key_from_jwt.return_value = SimpleNamespace(key=key.public_key())
        claims = {"sub": "identity-1", "iss": settings.oidc_issuer, "aud": "staffing",
                  "iat": int(time.time()), "exp": int(time.time()) + 300}
        def encode(data):
            return jwt.encode(data, key, algorithm="RS256", headers={"kid": "key-1"})
        self.assertEqual(verifier.subject("Bearer " + encode(claims)), "identity-1")
        for change in ({"aud": "other"}, {"iss": "https://other.example"},
                       {"exp": int(time.time()) - 300}, {"sub": " "}):
            with self.subTest(change=change), self.assertRaises(ServiceError) as error:
                verifier.subject("Bearer " + encode({**claims, **change}))
            self.assertEqual(error.exception.status, 401)

    def test_full_captain_can_decide_shared_request_but_not_edit_another_profile(self):
        require_captain_decision(captain(), "P-010")
        require_captain_decision(captain(), "P-006")
        with self.assertRaises(ServiceError):
            require_own_person(captain(), "P-006")

    def test_admin_does_not_impersonate_captain(self):
        admin = Actor("admin", "P-011", frozenset({"SYSTEM_ADMINISTRATOR"}), (
            Permission("SYSTEM_ADMINISTRATOR", "AI_FITMENT", "FULL", frozenset({"view", "approve"})),
        ))
        with self.assertRaises(ServiceError):
            require_captain_decision(admin, "P-011")

    def test_permissions_cannot_merge_across_roles(self):
        actor = Actor("id", "P-001", frozenset({"POD_LEAD", "POD_MEMBER"}), (
            Permission("POD_LEAD", "REQUESTS", "FULL", frozenset({"view"})),
            Permission("POD_MEMBER", "REQUESTS", "OWN", frozenset({"view", "update"})),
        ))
        self.assertEqual(actor.require("REQUESTS", "update").scope, "OWN")

    def test_repository_requires_single_real_person_mapping(self):
        db = MagicMock()
        cursor = db.read.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        repository = AuthorizationRepository(db)
        for rows in ([], [("P-001", "POD_LEAD", None, None), ("P-002", "POD_LEAD", None, None)]):
            cursor.fetchall.return_value = rows
            with self.assertRaises(ServiceError):
                repository.resolve("identity-1")
        cursor.fetchall.return_value = [("P-001", "POD_LEAD", "REQUESTS", "OWN", "Y", "N", "Y", "N", "N", "N")]
        actor = repository.resolve("identity-1")
        self.assertEqual(actor.person_id, "P-001")
        self.assertEqual(cursor.execute.call_args.kwargs, {"identitySubject": "identity-1"})

    def test_database_is_read_only_and_rolls_back(self):
        db = OracleDatabase(Settings())
        db._pool = MagicMock()
        connection = db._pool.acquire.return_value.__enter__.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = ("AI_POD_STAFFING",) * 3
        with db.read():
            pass
        self.assertEqual(cursor.execute.call_args_list[0].args[0], "SET TRANSACTION READ ONLY")
        connection.rollback.assert_called_once()
        connection.commit.assert_not_called()

    def test_database_stops_wrong_schema(self):
        db = OracleDatabase(Settings())
        db._pool = MagicMock()
        connection = db._pool.acquire.return_value.__enter__.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = ("ADMIN",) * 3
        with self.assertRaises(ServiceError) as error:
            with db.read():
                self.fail("Unexpected schema must not reach repository")
        self.assertEqual(error.exception.code, "WRONG_SCHEMA")
        connection.rollback.assert_called_once()

    def test_api_identity_and_role_header_boundary(self):
        db = MagicMock()
        repository = MagicMock()
        repository.resolve.return_value = captain()
        settings = Settings(backend_auth_mode="local", backend_local_token="x" * 32,
                            backend_local_subject="identity-1")
        with TestClient(create_app(settings, db, authorization=repository)) as client:
            self.assertEqual(client.get("/health/live").status_code, 200)
            denied = client.get("/v1/me", headers={"x-staffing-role": "Administrator"})
            self.assertEqual(denied.status_code, 401)
            repository.resolve.assert_not_called()
            response = client.get("/v1/me", headers={"Authorization": "Bearer " + "x" * 32})
            self.assertEqual(response.json()["person_id"], "P-010")
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertIn("x-correlation-id", response.headers)
            from app.policy import DEFAULT_POLICY
            with patch("app.main.load_policy", return_value=DEFAULT_POLICY), \
                 patch('app.policy_admin.rows', return_value=[{'policy_version': DEFAULT_POLICY.version}]):
                policy = client.get("/v1/policy", headers={"Authorization": "Bearer " + "x" * 32})
            self.assertEqual(policy.json()["status"], "DRAFT")

    def test_unexpected_error_is_redacted(self):
        db = MagicMock()
        db.ping.side_effect = RuntimeError("secret-password-do-not-echo")
        with TestClient(create_app(Settings(), db), raise_server_exceptions=False) as client:
            response = client.get("/health/ready")
            self.assertEqual(response.status_code, 500)
            self.assertNotIn("secret-password", response.text)


if __name__ == "__main__":
    unittest.main()
