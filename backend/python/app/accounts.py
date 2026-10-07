"""MVP password accounts. Opaque, revocable sessions; database roles remain authoritative."""
import hashlib
import hmac
import re
import secrets
from uuid import uuid4

from pydantic import Field, SecretStr, field_validator

from app.contracts import Contract
from app.errors import ServiceError
from app.storage import rows

ITERATIONS = 600_000
TOKEN_PATTERN = re.compile(r"aps1\.[A-Za-z0-9_-]{43}")
SESSION_ABSOLUTE_SECONDS = 3600
SESSION_IDLE_SECONDS = 300
SESSION_VALID_SQL = """s.revoked_at IS NULL AND s.expires_at>SYSTIMESTAMP
    AND s.created_at>SYSTIMESTAMP-NUMTODSINTERVAL(:absoluteSeconds,'SECOND')
    AND s.last_activity_at>SYSTIMESTAMP-NUMTODSINTERVAL(:idleSeconds,'SECOND')"""


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@oracle\.com", email) or len(email) > 320:
        raise ValueError("Use an Oracle email address")
    return email


class PasswordLogin(Contract):
    email: str = Field(min_length=3, max_length=320)
    password: SecretStr = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def email_address(cls, value):
        return normalize_email(value)


class PasswordChange(Contract):
    current_password: SecretStr = Field(min_length=1, max_length=1024)
    new_password: SecretStr = Field(min_length=1, max_length=128)


def require_strong_password(password: str):
    if len(password) < 10:
        raise ServiceError("WEAK_PASSWORD", "Use at least 10 characters.", 400)
    if not any(value.islower() for value in password) or not any(value.isupper() for value in password):
        raise ServiceError("WEAK_PASSWORD", "Include an uppercase and a lowercase letter.", 400)
    if not any(value.isdigit() for value in password) or not any(not value.isalnum() for value in password):
        raise ServiceError("WEAK_PASSWORD", "Include a number and a special character.", 400)


def hash_password(password: str) -> str:
    if not 8 <= len(password) <= 1024:
        raise ValueError("The initial password must contain 8–1024 characters")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS).hex()
    return f"pbkdf2_sha256${ITERATIONS}${salt}${digest}"


def check_password(password: str, encoded: str) -> bool:
    try:
        algorithm, count, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256" or int(count) != ITERATIONS or not re.fullmatch(r"[0-9a-f]{32}", salt):
            return False
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, AttributeError):
        return False


def session_hash(authorization: str | None) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not TOKEN_PATTERN.fullmatch(token):
        raise ServiceError("UNAUTHENTICATED", "Sign in to continue.", 401)
    return hashlib.sha256(token.encode()).hexdigest()


def execute(c, sql, **binds):
    with c.cursor() as cursor:
        cursor.execute(sql, binds)


class AccountStore:
    def __init__(self, database, settings):
        self.database, self.settings = database, settings
        # Same password work for an unknown email; the error never enumerates accounts.
        self._dummy_hash = None

    def require_enabled(self):
        if self.settings.backend_auth_mode != "password":
            raise ServiceError("PASSWORD_LOGIN_DISABLED", "Password sign-in is not enabled.", 404)

    def login(self, body: PasswordLogin):
        self.require_enabled()
        if self._dummy_hash is None:
            self._dummy_hash = hash_password(secrets.token_urlsafe(32))
        token = None
        # Invalid attempts must commit their counter before returning a generic error.
        with self.database.write() as c:
            accounts = rows(c, """SELECT account_id,identity_subject,password_hash,active_flag,
                failed_attempts, CASE WHEN locked_until>SYSTIMESTAMP THEN 1 ELSE 0 END locked
                FROM app_accounts WHERE login_email=:email FOR UPDATE WAIT 5""", email=body.email)
            account = accounts[0] if accounts else None
            valid = check_password(body.password.get_secret_value(), account["password_hash"] if account else self._dummy_hash)
            if account and not account["locked"]:
                if valid and account["active_flag"] == "Y":
                    # Verify the live role/person mapping before issuing any session.
                    mapped = rows(c, """SELECT DISTINCT ur.person_id,ur.role_code FROM app_user_roles ur
                        JOIN app_accounts a ON a.identity_subject=ur.identity_subject AND a.person_id=ur.person_id
                        JOIN people p ON p.person_id=ur.person_id AND p.active_flag='Y'
                        JOIN app_roles r ON r.role_code=ur.role_code AND r.active_flag='Y'
                        WHERE a.account_id=:id AND ur.active_flag='Y' AND ur.effective_from<=TRUNC(SYSDATE)
                        AND (ur.effective_to IS NULL OR ur.effective_to>=TRUNC(SYSDATE))""", id=account["account_id"])
                    from app.auth import OFFICIAL_ROLES
                    if len({r["person_id"] for r in mapped}) == 1 and mapped and all(r["role_code"] in OFFICIAL_ROLES for r in mapped):
                        token = "aps1." + secrets.token_urlsafe(32)
                        execute(c, """INSERT INTO app_sessions(token_hash,account_id,expires_at,last_activity_at)
                            VALUES(:token,:account,SYSTIMESTAMP+NUMTODSINTERVAL(:seconds,'SECOND'),SYSTIMESTAMP)""",
                            token=session_hash("Bearer " + token), account=account["account_id"], seconds=SESSION_ABSOLUTE_SECONDS)
                        execute(c, "UPDATE app_accounts SET failed_attempts=0,locked_until=NULL WHERE account_id=:id", id=account["account_id"])
                if not token:
                    execute(c, """UPDATE app_accounts SET failed_attempts=MOD(failed_attempts+1,5),
                        locked_until=CASE WHEN failed_attempts>=4 THEN SYSTIMESTAMP+INTERVAL '1' MINUTE ELSE NULL END
                        WHERE account_id=:id""", id=account["account_id"])
        if token is None:
            raise ServiceError("INVALID_CREDENTIALS", "Email or password is incorrect.", 401)
        return {"access_token": token, "expires_in": SESSION_ABSOLUTE_SECONDS}

    def subject(self, authorization: str | None) -> str:
        self.require_enabled()
        digest = session_hash(authorization)
        with self.database.read() as c:
            result = rows(c, f"""SELECT a.identity_subject FROM app_sessions s
                JOIN app_accounts a ON a.account_id=s.account_id AND a.active_flag='Y'
                JOIN people p ON p.person_id=a.person_id AND p.active_flag='Y'
                WHERE s.token_hash=:token AND {SESSION_VALID_SQL}""", token=digest,
                absoluteSeconds=SESSION_ABSOLUTE_SECONDS, idleSeconds=SESSION_IDLE_SECONDS)
        if len(result) != 1:
            raise ServiceError("UNAUTHENTICATED", "Your session ended. Sign in again.", 401)
        return result[0]["identity_subject"]

    def session_status(self, authorization: str | None):
        self.require_enabled()
        digest = session_hash(authorization)
        with self.database.read() as c:
            found = rows(c, f"""SELECT
                TO_CHAR(SYS_EXTRACT_UTC(CASE WHEN s.expires_at<s.created_at+NUMTODSINTERVAL(:absoluteSeconds,'SECOND')
                    THEN s.expires_at ELSE s.created_at+NUMTODSINTERVAL(:absoluteSeconds,'SECOND') END),
                    'YYYY-MM-DD"T"HH24:MI:SS.FF3"Z"') absolute_expires_at,
                TO_CHAR(SYS_EXTRACT_UTC(s.last_activity_at+NUMTODSINTERVAL(:idleSeconds,'SECOND')),
                    'YYYY-MM-DD"T"HH24:MI:SS.FF3"Z"') idle_expires_at
                FROM app_sessions s JOIN app_accounts a ON a.account_id=s.account_id AND a.active_flag='Y'
                JOIN people p ON p.person_id=a.person_id AND p.active_flag='Y'
                WHERE s.token_hash=:token AND {SESSION_VALID_SQL}""",
                token=digest, absoluteSeconds=SESSION_ABSOLUTE_SECONDS, idleSeconds=SESSION_IDLE_SECONDS)
        if len(found) != 1:
            raise ServiceError("UNAUTHENTICATED", "Your session ended. Sign in again.", 401)
        return {"absolute_expires_at": found[0]["absolute_expires_at"],
                "idle_expires_at": found[0]["idle_expires_at"]}

    def record_activity(self, authorization: str | None):
        self.require_enabled()
        digest = session_hash(authorization)
        with self.database.write() as c:
            with c.cursor() as cursor:
                cursor.execute(f"""UPDATE app_sessions s SET last_activity_at=SYSTIMESTAMP
                    WHERE s.token_hash=:token AND {SESSION_VALID_SQL}
                    AND EXISTS (SELECT 1 FROM app_accounts a JOIN people p ON p.person_id=a.person_id
                        WHERE a.account_id=s.account_id AND a.active_flag='Y' AND p.active_flag='Y')""",
                    {"token": digest, "absoluteSeconds": SESSION_ABSOLUTE_SECONDS, "idleSeconds": SESSION_IDLE_SECONDS})
                if cursor.rowcount != 1:
                    raise ServiceError("UNAUTHENTICATED", "Your session ended. Sign in again.", 401)
        return self.session_status(authorization)

    def logout(self, authorization: str | None):
        self.require_enabled()
        digest = session_hash(authorization)
        with self.database.write() as c:
            execute(c, "UPDATE app_sessions SET revoked_at=SYSTIMESTAMP WHERE token_hash=:token AND revoked_at IS NULL", token=digest)
        return {"ok": True}

    def change_password(self, authorization: str | None, body: PasswordChange):
        self.require_enabled()
        digest = session_hash(authorization)
        current = body.current_password.get_secret_value()
        replacement = body.new_password.get_secret_value()
        with self.database.write() as c:
            found = rows(c, f"""SELECT a.account_id,a.identity_subject,a.password_hash FROM app_sessions s
                JOIN app_accounts a ON a.account_id=s.account_id AND a.active_flag='Y'
                JOIN people p ON p.person_id=a.person_id AND p.active_flag='Y'
                WHERE s.token_hash=:token AND {SESSION_VALID_SQL}
                FOR UPDATE OF a.password_hash WAIT 5""", token=digest,
                absoluteSeconds=SESSION_ABSOLUTE_SECONDS, idleSeconds=SESSION_IDLE_SECONDS)
            if len(found) != 1:
                raise ServiceError("UNAUTHENTICATED", "Your session ended. Sign in again.", 401)
            account = found[0]
            if not check_password(current, account["password_hash"]):
                raise ServiceError("CURRENT_PASSWORD_INCORRECT", "The current password is incorrect.", 400)
            require_strong_password(replacement)
            if check_password(replacement, account["password_hash"]):
                raise ServiceError("PASSWORD_REUSED", "Choose a password different from your current password.", 400)
            execute(c, """UPDATE app_accounts SET password_hash=:passwordHash,failed_attempts=0,locked_until=NULL
                WHERE account_id=:accountId""", passwordHash=hash_password(replacement), accountId=account["account_id"])
            execute(c, """UPDATE app_sessions SET revoked_at=SYSTIMESTAMP
                WHERE account_id=:accountId AND revoked_at IS NULL""", accountId=account["account_id"])
            audit_id = uuid4().hex
            execute(c, """INSERT INTO audit_events(audit_event_id,entity_type,entity_id,action_type,
                actor_subject,correlation_id,reason)
                VALUES(:auditId,'ACCOUNT',:accountId,'PASSWORD_CHANGED',:actor,:auditId,
                'Password changed by account owner; all sessions revoked.')""",
                auditId=audit_id, accountId=account["account_id"], actor=account["identity_subject"])
        return {"ok": True, "sessions_revoked": True}
