"""Local-only, short-lived persona sessions backed by fresh Oracle role mappings.

No employee roles are granted here. The management credential can choose an
already seeded local identity, but never serves as a normal employee session.
"""
import base64
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import time
from dataclasses import dataclass
from typing import Literal

from app.auth import Actor, OFFICIAL_ROLES
from app.contracts import Contract, EntityId
from app.errors import ServiceError
from app.storage import rows

SESSION_SECONDS = 8 * 60 * 60
TOKEN_PREFIX = "dps1"
TOKEN_PURPOSE = "staffing-demo-persona"
SIGNING_CONTEXT = b"ai-pod-staffing/local-persona-session/v1"
CLAIM_KEYS = {"purpose", "sub", "person_id", "role_code", "iat", "exp", "nonce"}


class PersonaSelection(Contract):
    person_id: EntityId
    role_code: Literal["POD_CAPTAIN", "POD_LEAD", "POD_MEMBER", "SYSTEM_ADMINISTRATOR"]


@dataclass(frozen=True)
class PersonaIdentity:
    sub: str
    person_id: str
    role_code: str
    iat: int
    exp: int


def require_enabled(settings):
    if (not settings.staffing_demo_personas_enabled or settings.backend_env != "local"
        or settings.backend_auth_mode != "local"):
        raise ServiceError("PERSONAS_DISABLED", "Local persona entry is not enabled.", 404)


def bearer_token(authorization):
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token or len(token) > 16000:
        raise ServiceError("UNAUTHENTICATED", "A valid access token is required.", 401)
    return token


def require_management(settings, authorization, client_host):
    require_enabled(settings)
    try:
        address = ipaddress.ip_address(client_host)
        if getattr(address, "ipv4_mapped", None):
            address = address.ipv4_mapped
        loopback = address.is_loopback
    except (ValueError, TypeError):
        loopback = False
    if not loopback:
        raise ServiceError("LOCAL_ONLY", "Persona entry is available only through the local application server.", 403)
    token = bearer_token(authorization)
    if not settings.backend_local_token or not secrets.compare_digest(
        token.encode(), settings.backend_local_token.get_secret_value().encode()
    ):
        raise ServiceError("UNAUTHENTICATED", "The local management credential is required.", 401)


def _base64(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("Invalid token encoding")
    decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if _base64(decoded) != value:
        raise ValueError("Noncanonical token encoding")
    return decoded


def _key(settings):
    require_enabled(settings)
    if not settings.backend_local_token:
        raise ServiceError("AUTH_NOT_CONFIGURED", "Local persona authentication is not configured.", 503)
    return hmac.new(settings.backend_local_token.get_secret_value().encode(), SIGNING_CONTEXT, hashlib.sha256).digest()


def _encode_claims(claims, settings):
    payload = _base64(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    signed = f"{TOKEN_PREFIX}.{payload}"
    signature = _base64(hmac.new(_key(settings), signed.encode("ascii"), hashlib.sha256).digest())
    return f"{signed}.{signature}"


def mint_session(selection, settings, *, now=None):
    require_enabled(settings)
    issued = int(time.time()) if now is None else now
    claims = {"purpose": TOKEN_PURPOSE, "sub": f"demo:d1:{selection.person_id}",
              "person_id": selection.person_id, "role_code": selection.role_code,
              "iat": issued, "exp": issued + SESSION_SECONDS, "nonce": secrets.token_urlsafe(18)}
    return {"access_token": _encode_claims(claims, settings), "expires_in": SESSION_SECONDS,
            "person_id": selection.person_id, "role_code": selection.role_code}


def _unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate token claim")
        result[key] = value
    return result


def verify_persona_token(authorization, settings, *, now=None):
    require_enabled(settings)
    token = bearer_token(authorization)
    try:
        prefix, payload, signature = token.split(".")
        if prefix != TOKEN_PREFIX:
            raise ValueError("Wrong token type")
        supplied = _decode(signature)
        expected = hmac.new(_key(settings), f"{prefix}.{payload}".encode("ascii"), hashlib.sha256).digest()
        if not secrets.compare_digest(supplied, expected):
            raise ValueError("Invalid signature")
        claims = json.loads(_decode(payload), object_pairs_hook=_unique_json)
        if not isinstance(claims, dict) or set(claims) != CLAIM_KEYS or claims["purpose"] != TOKEN_PURPOSE:
            raise ValueError("Invalid token claims")
        person_id, role = claims["person_id"], claims["role_code"]
        if (not isinstance(person_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,30}", person_id)
            or not isinstance(role, str) or role not in OFFICIAL_ROLES
            or claims["sub"] != f"demo:d1:{person_id}"):
            raise ValueError("Invalid persona mapping")
        current = int(time.time()) if now is None else now
        if (type(claims["iat"]) is not int or type(claims["exp"]) is not int
            or claims["iat"] < 0 or claims["iat"] > current
            or claims["exp"] - claims["iat"] != SESSION_SECONDS or claims["exp"] <= current
            or not isinstance(claims["nonce"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", claims["nonce"])):
            raise ValueError("Persona session is expired or invalid")
        return PersonaIdentity(claims["sub"], person_id, role, claims["iat"], claims["exp"])
    except (ValueError, TypeError, UnicodeError, KeyError):
        raise ServiceError("UNAUTHENTICATED", "Persona session is invalid or expired. Choose a profile again.", 401) from None


def constrain_actor(actor, identity):
    if (actor.subject != identity.sub or actor.person_id != identity.person_id
        or identity.role_code not in actor.roles):
        raise ServiceError("PERSONA_NOT_AVAILABLE", "This person's selected profile is no longer available.", 403)
    return Actor(actor.subject, actor.person_id, frozenset({identity.role_code}),
                 tuple(permission for permission in actor.permissions if permission.role == identity.role_code), actor.full_name)


class PersonaRepository:
    def __init__(self, database):
        self.database = database

    def list(self):
        with self.database.read() as connection:
            return rows(connection, """SELECT DISTINCT p.person_id,p.full_name,ar.role_code,ar.role_name
                FROM people p JOIN app_user_roles ur ON ur.person_id=p.person_id
                JOIN app_roles ar ON ar.role_code=ur.role_code
                WHERE p.active_flag='Y' AND ur.active_flag='Y' AND ar.active_flag='Y'
                  AND ur.identity_subject='demo:d1:' || p.person_id
                  AND ur.role_code IN ('POD_CAPTAIN','POD_LEAD','POD_MEMBER','SYSTEM_ADMINISTRATOR')
                  AND ur.effective_from<=TRUNC(SYSDATE)
                  AND (ur.effective_to IS NULL OR ur.effective_to>=TRUNC(SYSDATE))
                ORDER BY ar.role_code,p.full_name,p.person_id""")

    def require_selection(self, selection):
        available = self.list()
        if not any(row["person_id"] == selection.person_id and row["role_code"] == selection.role_code for row in available):
            raise ServiceError("PERSONA_NOT_AVAILABLE", "This person's selected profile is no longer available.", 403)
