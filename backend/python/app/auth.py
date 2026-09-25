import secrets
from dataclasses import dataclass

import jwt
from jwt import PyJWKClient

from app.config import Settings
from app.database import OracleDatabase
from app.errors import ServiceError

OFFICIAL_ROLES = {"POD_CAPTAIN", "POD_LEAD", "POD_MEMBER", "SYSTEM_ADMINISTRATOR"}
ROLE_PRIORITY = {"SYSTEM_ADMINISTRATOR": 0, "POD_CAPTAIN": 1, "POD_LEAD": 2, "POD_MEMBER": 3}
ACTIONS = {"view", "create", "update", "approve", "export", "administer"}


@dataclass(frozen=True)
class Permission:
    role: str
    resource: str
    scope: str
    actions: frozenset[str]


@dataclass(frozen=True)
class Actor:
    subject: str
    person_id: str
    roles: frozenset[str]
    permissions: tuple[Permission, ...]
    full_name: str = ""

    def require(self, resource: str, action: str, role: str | None = None) -> Permission:
        if action not in ACTIONS:
            raise ServiceError("FORBIDDEN", "This action is not permitted.", 403)
        matches = [permission for permission in self.permissions if permission.resource == resource
                   and (role is None or permission.role == role) and permission.role in self.roles
                   and permission.scope != "LOCKED" and "view" in permission.actions
                   and action in permission.actions]
        if not matches:
            raise ServiceError("FORBIDDEN", "This action is not permitted.", 403)
        # Never merge scopes from different roles. Callers must enforce the returned record scope.
        return sorted(matches, key=lambda item: (
            {"FULL": 0, "SCOPED": 1, "OWN": 2}[item.scope], ROLE_PRIORITY.get(item.role, 99)))[0]


class TokenVerifier:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.jwks = PyJWKClient(settings.oidc_jwks_url, cache_jwk_set=True, lifespan=300, timeout=5) if settings.oidc_ready else None

    def subject(self, authorization: str | None) -> str:
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token or len(token) > 16000:
            raise ServiceError("UNAUTHENTICATED", "A valid access token is required.", 401)
        if self.settings.backend_auth_mode == "local":
            if self.settings.staffing_demo_personas_enabled:
                # The local management secret no longer authenticates a fixed
                # employee when explicit persona sessions are enabled.
                return self.persona(authorization).sub
            if not secrets.compare_digest(token.encode(), self.settings.backend_local_token.get_secret_value().encode()):
                raise ServiceError("UNAUTHENTICATED", "A valid access token is required.", 401)
            return self.settings.backend_local_subject.strip()
        if self.jwks is None:
            raise ServiceError("AUTH_NOT_CONFIGURED", "Enterprise authentication is not configured.", 503)
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str) or len(header["kid"]) > 200:
                raise jwt.InvalidTokenError()
            key = self.jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=["RS256"], audience=self.settings.oidc_audience,
                                issuer=self.settings.oidc_issuer, leeway=30,
                                options={"require": ["exp", "iat", "sub", "iss", "aud"]})
            subject = claims["sub"]
            if not isinstance(subject, str) or not subject.strip() or len(subject) > 255:
                raise jwt.InvalidTokenError()
            return subject
        except jwt.PyJWKClientConnectionError as error:
            raise ServiceError("IDENTITY_UNAVAILABLE", "Identity verification is temporarily unavailable.", 503) from error
        except jwt.PyJWTError as error:
            raise ServiceError("UNAUTHENTICATED", "Access token is invalid or expired.", 401) from error

    def persona(self, authorization: str | None):
        from app.personas import verify_persona_token
        return verify_persona_token(authorization, self.settings)


class AuthorizationRepository:
    def __init__(self, database: OracleDatabase):
        self.database = database

    def resolve(self, subject: str) -> Actor:
        # Roles in the JWT or x-staffing-role are deliberately not used for permission grants.
        with self.database.read() as connection, connection.cursor() as cursor:
            cursor.execute("""
                SELECT aur.person_id, ar.role_code, rp.resource_code, rp.access_scope,
                       rp.can_view, rp.can_create, rp.can_update, rp.can_approve, rp.can_export, rp.can_administer,
                       p.full_name
                  FROM app_user_roles aur JOIN people p ON p.person_id = aur.person_id AND p.active_flag = 'Y'
                  JOIN app_roles ar ON ar.role_code = aur.role_code AND ar.active_flag = 'Y'
                  LEFT JOIN role_permissions rp ON rp.role_code = ar.role_code
                 WHERE aur.identity_subject = :identitySubject AND aur.active_flag = 'Y'
                   AND aur.effective_from <= TRUNC(SYSDATE)
                   AND (aur.effective_to IS NULL OR aur.effective_to >= TRUNC(SYSDATE))
                 ORDER BY ar.role_code, rp.resource_code
            """, identitySubject=subject)
            rows = cursor.fetchall()
        people = {row[0] for row in rows}
        roles = {row[1] for row in rows}
        if len(people) != 1 or not roles or not roles <= OFFICIAL_ROLES:
            raise ServiceError("IDENTITY_NOT_LINKED", "No unambiguous active employee role mapping is available.", 403)
        permissions = []
        for row in rows:
            if row[2] is None:
                continue
            if row[3] not in {"FULL", "SCOPED", "OWN", "LOCKED"}:
                raise ServiceError("INVALID_PERMISSION", "The permission configuration needs review.", 403)
            permissions.append(Permission(row[1], row[2], row[3], frozenset(
                action for action, flag in zip(("view", "create", "update", "approve", "export", "administer"), row[4:10], strict=True) if flag == "Y")))
        full_name = (rows[0][10] or "") if len(rows[0]) > 10 else ""
        return Actor(subject, next(iter(people)), frozenset(roles), tuple(permissions), full_name)


def require_own_person(actor: Actor, person_id: str):
    if actor.person_id != person_id:
        raise ServiceError("FORBIDDEN", "Only your own employee record is permitted.", 403)


def require_captain_decision(actor: Actor, responsible_captain_id: str):
    permission = actor.require("AI_FITMENT", "approve", role="POD_CAPTAIN")
    # Official Captains have FULL access to the shared queue. Keep narrower
    # legacy grants narrow; neither a source name nor an Admin grant upgrades them.
    if permission.scope != "FULL" and actor.person_id != responsible_captain_id:
        raise ServiceError("FORBIDDEN", "This request belongs to another Captain.", 403)
