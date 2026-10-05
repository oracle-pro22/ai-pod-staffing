"""Atomic administrator provisioning. No directory-only users or plaintext passwords."""
from typing import Literal
from uuid import uuid4

from pydantic import Field, StrictBool, field_validator

from app.accounts import hash_password, normalize_email
from app.contracts import Contract
from app.errors import ServiceError
from app.execution_store import execute
from app.roster_lifecycle import audit, authorize
from app.storage import rows

Role = Literal['POD_CAPTAIN', 'POD_LEAD', 'POD_MEMBER', 'SYSTEM_ADMINISTRATOR']


class EmployeeInput(Contract):
    fullName: str = Field(min_length=1, max_length=250)
    jobTitle: str = Field(min_length=1, max_length=250)
    location: str = Field(min_length=1, max_length=150)
    email: str = Field(min_length=3, max_length=320)
    roles: tuple[Role, ...] = Field(min_length=1, max_length=4)
    enabled: StrictBool
    staffingEligible: StrictBool

    @field_validator('fullName', 'jobTitle', 'location')
    @classmethod
    def nonblank(cls, value, info):
        value = ' '.join(value.split())
        limit = 150 if info.field_name == 'location' else 250
        if not value or len(value.encode('utf-8')) > limit:
            raise ValueError('Enter nonblank text within the database byte limit')
        return value

    @field_validator('email')
    @classmethod
    def email_address(cls, value):
        return normalize_email(value)

    @field_validator('roles')
    @classmethod
    def unique_roles(cls, value):
        if len(set(value)) != len(value):
            raise ValueError('Select each role only once')
        return value


def provision_employee(database, settings, actor, body):
    actor.require('ACCESS_MANAGEMENT', 'administer', 'SYSTEM_ADMINISTRATOR')
    actor.require('TEAM_SKILLS', 'create', 'SYSTEM_ADMINISTRATOR')
    secret = settings.staffing_mvp_default_password
    if settings.backend_auth_mode != 'password' or not secret or not 8 <= len(secret.get_secret_value()) <= 1024:
        raise ServiceError('EMPLOYEE_PASSWORD_CONFIGURATION',
            'Configure password sign-in and the existing shared initial password on the backend before adding employees.', 503)
    encoded = hash_password(secret.get_secret_value())
    try:
        with database.write() as c:
            control = rows(c, 'SELECT revision FROM roster_access_control WHERE control_id=1 FOR UPDATE WAIT 5')
            authorize(c, actor, 'ACCESS_MANAGEMENT', 'administer', 'SYSTEM_ADMINISTRATOR')
            authorize(c, actor, 'TEAM_SKILLS', 'create', 'SYSTEM_ADMINISTRATOR')
            if len(control) != 1:
                raise ServiceError('EMPLOYEE_SETUP_REQUIRED', 'Account administration schema is incomplete.', 503)
            duplicates = rows(c, """SELECT person_id FROM people WHERE LOWER(TRIM(email_address))=:email
                UNION ALL SELECT person_id FROM app_accounts WHERE LOWER(TRIM(login_email))=:email""", email=body.email)
            if duplicates:
                raise ServiceError('EMPLOYEE_EXISTS', 'This email already belongs to an employee or account, including disabled accounts.', 409)
            installed = {r['role_code'] for r in rows(c, "SELECT role_code FROM app_roles WHERE active_flag='Y'")}
            if not set(body.roles) <= installed:
                raise ServiceError('ROLE_UNAVAILABLE', 'A selected role is not active. Refresh before adding the employee.', 409)
            seq = rows(c, 'SELECT person_id_seq.NEXTVAL AS person_number FROM dual')
            pid = f"P-{int(seq[0]['person_number']):03}"
            account = 'ACC-' + uuid4().hex
            subject = 'acct:' + account
            parts = body.fullName.split()
            initials = (parts[0][0] + (parts[-1][0] if len(parts) > 1 else '')).upper()
            execute(c, """INSERT INTO people(person_id,full_name,initials,job_title,location,weekly_work_hours,
                email_address,external_identity_subject,allocation_pct,active_pods,active_flag,staffing_eligible_flag,
                skills_version,deliverable_experience_json)
                VALUES(:pid,:name,:initials,:job,:location,40,:email,:subject,0,0,'Y',:eligible,0,:experience)""",
                dict(pid=pid, name=body.fullName, initials=initials, job=body.jobTitle, location=body.location,
                     email=body.email, subject=subject, eligible='Y' if body.staffingEligible else 'N', experience='[]'), ('experience',))
            execute(c, """INSERT INTO app_accounts(account_id,person_id,identity_subject,login_email,password_hash,active_flag,created_by)
                VALUES(:account,:pid,:subject,:email,:encoded,:active,:actor)""",
                dict(account=account, pid=pid, subject=subject, email=body.email, encoded=encoded,
                     active='Y' if body.enabled else 'N', actor=actor.subject))
            for role in body.roles:
                execute(c, """INSERT INTO app_user_roles(identity_subject,role_code,person_id,active_flag,effective_from,assigned_by)
                    VALUES(:subject,:role,:pid,'Y',TRUNC(SYSDATE),:actor)""",
                    dict(subject=subject, role=role, pid=pid, actor=actor.subject))
            execute(c, "INSERT INTO roster_onboarding(person_id,status) VALUES(:pid,'DRAFT')", dict(pid=pid))
            execute(c, 'UPDATE roster_access_control SET revision=revision+1 WHERE control_id=1')
            audit(c, actor, pid, 'EMPLOYEE_CREATED',
                  f"Account created; access={'enabled' if body.enabled else 'pending'}; roles={','.join(body.roles)}; first-login setup required.")
            return dict(personId=pid, fullName=body.fullName, enabled=body.enabled, onboarding='DRAFT')
    except Exception as error:
        code = getattr(error.args[0], 'code', None) if error.args else None
        if code == 1:
            raise ServiceError('EMPLOYEE_EXISTS', 'Email or generated identity already exists. Refresh before retrying.', 409) from error
        if code == 2289:
            raise ServiceError('EMPLOYEE_SETUP_REQUIRED', 'The person ID sequence is missing. Run the existing admin_people.sql setup.', 503) from error
        raise
