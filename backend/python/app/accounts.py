"""MVP password accounts. Opaque, revocable sessions; database roles remain authoritative."""
import hashlib
import hmac
import re
import secrets

from pydantic import Field, SecretStr, field_validator

from app.contracts import Contract
from app.errors import ServiceError
from app.storage import rows

ITERATIONS = 600_000
TOKEN_PATTERN = re.compile(r"aps1\.[A-Za-z0-9_-]{43}")


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
                        execute(c, """INSERT INTO app_sessions(token_hash,account_id,expires_at)
                            VALUES(:token,:account,SYSTIMESTAMP+NUMTODSINTERVAL(:seconds,'SECOND'))""",
                            token=session_hash("Bearer " + token), account=account["account_id"], seconds=self.settings.staffing_session_hours * 3600)
                        execute(c, "UPDATE app_accounts SET failed_attempts=0,locked_until=NULL WHERE account_id=:id", id=account["account_id"])
                if not token:
                    execute(c, """UPDATE app_accounts SET failed_attempts=MOD(failed_attempts+1,5),
                        locked_until=CASE WHEN failed_attempts>=4 THEN SYSTIMESTAMP+INTERVAL '1' MINUTE ELSE NULL END
                        WHERE account_id=:id""", id=account["account_id"])
        if token is None:
            raise ServiceError("INVALID_CREDENTIALS", "Unable to sign in. Check your email and password, or try again shortly.", 401)
        return {"access_token": token, "expires_in": self.settings.staffing_session_hours * 3600}

    def subject(self, authorization: str | None) -> str:
        self.require_enabled()
        digest = session_hash(authorization)
        with self.database.read() as c:
            result = rows(c, """SELECT a.identity_subject FROM app_sessions s
                JOIN app_accounts a ON a.account_id=s.account_id AND a.active_flag='Y'
                JOIN people p ON p.person_id=a.person_id AND p.active_flag='Y'
                WHERE s.token_hash=:token AND s.revoked_at IS NULL AND s.expires_at>SYSTIMESTAMP""", token=digest)
        if len(result) != 1:
            raise ServiceError("UNAUTHENTICATED", "Your session ended. Sign in again.", 401)
        return result[0]["identity_subject"]

    def logout(self, authorization: str | None):
        self.require_enabled()
        digest = session_hash(authorization)
        with self.database.write() as c:
            execute(c, "UPDATE app_sessions SET revoked_at=SYSTIMESTAMP WHERE token_hash=:token AND revoked_at IS NULL", token=digest)
        return {"ok": True}
