"""Explicit account administration and first-login setup; no agent/model tools."""
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from pydantic import Field, StrictBool, model_validator

from app.accounts import execute
from app.capacity import spread_hours
from app.capacity_admin import refresh, SameConnection
from app.contracts import Contract, DeliverableEvidence, SkillEvidence
from app.errors import ServiceError
from app.planning import json_text
from app.storage import calendar_day, document, rows


def demand(ok, message, code='ROSTER_CONFLICT', status=409):
    if not ok:
        raise ServiceError(code, message, status)


class AccessChange(Contract):
    enabled: StrictBool
    revision: int = Field(ge=1, strict=True)
    reason: str = Field(min_length=3, max_length=2000)


class WorkEntry(Contract):
    kind: Literal['LEAVE', 'EXTERNAL', 'POD']
    title: str = Field(min_length=1, max_length=500)
    starts_on: date
    ends_on: date
    total_hours: Decimal = Field(gt=0, le=10000, decimal_places=2, allow_inf_nan=False)
    role_code: Literal['POD_LEAD', 'POD_MEMBER'] | None = None

    @model_validator(mode='after')
    def valid(self):
        if self.ends_on < self.starts_on or (self.ends_on-self.starts_on).days > 83:
            raise ValueError('Use an ordered work period of at most 12 weeks')
        if (self.kind == 'POD') != (self.role_code is not None):
            raise ValueError('Only existing POD work needs a role')
        if any(d.hours > (8 if self.kind == 'LEAVE' else 24) for d in spread_hours(self.total_hours, self.starts_on, self.ends_on)):
            raise ValueError('Leave cannot exceed 8 hours/day; recorded work cannot exceed 24 hours/day')
        return self


class OnboardingInput(Contract):
    revision: int = Field(ge=1, strict=True)
    starts_on: date
    ends_on: date
    confirmed: StrictBool
    skills: tuple[SkillEvidence, ...] = Field(default=(), max_length=100)
    deliverables: tuple[DeliverableEvidence, ...] = Field(default=(), max_length=100)
    work: tuple[WorkEntry, ...] = Field(default=(), max_length=40)

    @model_validator(mode='after')
    def valid(self):
        if not self.confirmed:
            raise ValueError('Explicitly confirm the accuracy of the dated inputs')
        first = self.starts_on-timedelta(days=self.starts_on.weekday())
        last = self.ends_on+timedelta(days=6-self.ends_on.weekday())
        if self.ends_on < self.starts_on or (last-first).days > 90:
            raise ValueError('Confirm at most 13 complete weeks')
        if any(w.starts_on < self.starts_on or w.ends_on > self.ends_on for w in self.work):
            raise ValueError('Work entries must fit the confirmed period')
        if len({s.skill_id for s in self.skills}) != len(self.skills) or len({d.deliverable_id for d in self.deliverables}) != len(self.deliverables):
            raise ValueError('Duplicate assessments')
        if len({(w.kind, w.title, w.starts_on, w.ends_on) for w in self.work}) != len(self.work):
            raise ValueError('Duplicate work entries')
        totals = {}
        for w in self.work:
            for day in spread_hours(w.total_hours, w.starts_on, w.ends_on):
                key = (w.kind, day.day)
                totals[key] = totals.get(key, Decimal(0))+day.hours
        if any(hours > (8 if kind == 'LEAVE' else 24) for (kind, _), hours in totals.items()):
            raise ValueError('Overlapping leave exceeds contracted hours or recorded work exceeds 24 hours/day')
        return self


def status(c, person_id):
    found = rows(c, 'SELECT status,revision FROM roster_onboarding WHERE person_id=:pid', pid=person_id)
    if not found:
        return {'status': 'LEGACY', 'revision': 0}
    # Profiles submitted by the retired approval-gated flow must not remain
    # locked out. Expose those legacy REVIEW rows as completed setup.
    return {**found[0], 'status': 'COMPLETE' if found[0]['status'] == 'REVIEW' else found[0]['status']}


def require_ready(c, person_id):
    demand(status(c, person_id)['status'] in ('COMPLETE', 'LEGACY'),
           'Complete first-login setup before using the workspace.', 'ONBOARDING_REQUIRED', 403)


def current_account(c, actor, lock=False):
    found = rows(c, """SELECT a.account_id,a.active_flag FROM app_accounts a
        JOIN people p ON p.person_id=a.person_id AND p.active_flag='Y'
        WHERE a.identity_subject=:subject AND a.person_id=:pid""" + (' FOR UPDATE OF a.active_flag WAIT 5' if lock else ''),
        subject=actor.subject, pid=actor.person_id)
    demand(len(found) == 1 and found[0]['active_flag'] == 'Y', 'Account is disabled or changed. Sign in again.', 'FORBIDDEN', 403)
    return found[0]


def authorize(c, actor, resource, action, role):
    permission = actor.require(resource, action, role)
    demand(permission.scope == 'FULL', 'Full scoped access is required.', 'FORBIDDEN', 403)
    current_account(c, actor)
    demand(rows(c, f"""SELECT ur.person_id FROM app_user_roles ur JOIN app_roles ar
        ON ar.role_code=ur.role_code AND ar.active_flag='Y'
        JOIN role_permissions rp ON rp.role_code=ar.role_code AND rp.resource_code=:resource
        WHERE ur.identity_subject=:subject AND ur.person_id=:pid AND ur.role_code=:role
        AND ur.active_flag='Y' AND ur.effective_from<=TRUNC(SYSDATE)
        AND (ur.effective_to IS NULL OR ur.effective_to>=TRUNC(SYSDATE))
        AND rp.can_view='Y' AND rp.can_{action}='Y' AND rp.access_scope='FULL'""",
        resource=resource, subject=actor.subject, pid=actor.person_id, role=role), 'Your permission changed.', 'FORBIDDEN', 403)


def audit(c, actor, entity, action, reason):
    execute(c, """INSERT INTO audit_events(audit_event_id,entity_type,entity_id,action_type,
        actor_subject,correlation_id,reason) VALUES(:id,'ROSTER',:entity,:action,:actor,:id,:reason)""",
        id=uuid4().hex, entity=entity, action=action, actor=actor.subject, reason=reason)


class RosterLifecycle:
    def __init__(self, database):
        self.database = database

    def accounts(self, actor):
        with self.database.read() as c:
            authorize(c, actor, 'ACCESS_MANAGEMENT', 'administer', 'SYSTEM_ADMINISTRATOR')
            revision = rows(c, 'SELECT revision FROM roster_access_control WHERE control_id=1')[0]['revision']
            people = rows(c, """SELECT a.account_id,a.person_id,a.login_email,a.active_flag,p.full_name,
                NVL(o.status,'LEGACY') onboarding_status FROM app_accounts a
                JOIN people p ON p.person_id=a.person_id LEFT JOIN roster_onboarding o ON o.person_id=p.person_id
                ORDER BY p.full_name""")
            return {'revision': revision, 'accounts': people}

    def access(self, actor, account_id, body):
        with self.database.write() as c:
            # Global account-change lock prevents two Administrators disabling each other/the last admin.
            control = rows(c, 'SELECT revision FROM roster_access_control WHERE control_id=1 FOR UPDATE WAIT 5')
            authorize(c, actor, 'ACCESS_MANAGEMENT', 'administer', 'SYSTEM_ADMINISTRATOR')
            demand(control and control[0]['revision'] == body.revision, 'Access changed; refresh before saving.')
            target = rows(c, 'SELECT person_id FROM app_accounts WHERE account_id=:id', id=account_id)
            demand(len(target) == 1, 'Account not found.', 'NOT_FOUND', 404)
            pid = target[0]['person_id']
            rows(c, 'SELECT person_id FROM people WHERE person_id=:pid FOR UPDATE WAIT 5', pid=pid)
            target = rows(c, 'SELECT person_id,active_flag FROM app_accounts WHERE account_id=:id FOR UPDATE WAIT 5', id=account_id)[0]
            flag = 'Y' if body.enabled else 'N'
            if target['active_flag'] == flag:
                return {'revision': body.revision, 'changed': False}
            if not body.enabled:
                demand(pid != actor.person_id, 'You cannot disable your own account.')
                admins = rows(c, """SELECT DISTINCT a.person_id FROM app_accounts a
                    JOIN people p ON p.person_id=a.person_id AND p.active_flag='Y'
                    JOIN app_user_roles ur ON ur.person_id=a.person_id AND ur.identity_subject=a.identity_subject
                    JOIN app_roles ar ON ar.role_code=ur.role_code AND ar.active_flag='Y'
                    JOIN role_permissions rp ON rp.role_code=ar.role_code AND rp.resource_code='ACCESS_MANAGEMENT'
                    WHERE a.active_flag='Y' AND ur.active_flag='Y' AND ur.role_code='SYSTEM_ADMINISTRATOR'
                    AND ur.effective_from<=TRUNC(SYSDATE) AND (ur.effective_to IS NULL OR ur.effective_to>=TRUNC(SYSDATE))
                    AND rp.can_view='Y' AND rp.can_administer='Y' AND rp.access_scope='FULL'""")
                demand(any(a['person_id'] != pid for a in admins), 'At least one active access Administrator must remain.')
                demand(not rows(c, """SELECT assignment_id FROM pod_assignments WHERE person_id=:pid
                    AND role_in_pod='POD_LEAD' AND status='CONFIRMED'""", pid=pid),
                    'This person leads an active POD. Resolve that project before disabling access.')
            else:
                demand(rows(c, "SELECT person_id FROM people WHERE person_id=:pid AND active_flag='Y'", pid=pid), 'The person record is inactive.')
                demand(rows(c, """SELECT ur.role_code FROM app_user_roles ur JOIN app_accounts a
                    ON a.person_id=ur.person_id AND a.identity_subject=ur.identity_subject JOIN app_roles ar
                    ON ar.role_code=ur.role_code AND ar.active_flag='Y' WHERE a.account_id=:id
                    AND ur.active_flag='Y' AND ur.effective_from<=TRUNC(SYSDATE)
                    AND (ur.effective_to IS NULL OR ur.effective_to>=TRUNC(SYSDATE))""", id=account_id), 'Effective role grants are missing.')
            execute(c, 'UPDATE app_accounts SET active_flag=:flag,failed_attempts=0,locked_until=NULL WHERE account_id=:id', flag=flag, id=account_id)
            execute(c, 'UPDATE app_sessions SET revoked_at=SYSTIMESTAMP WHERE account_id=:id AND revoked_at IS NULL', id=account_id)
            execute(c, 'UPDATE roster_access_control SET revision=revision+1 WHERE control_id=1')
            audit(c, actor, pid, 'ACCOUNT_ENABLED' if body.enabled else 'ACCOUNT_DISABLED', body.reason)
            return {'revision': body.revision+1, 'changed': True}

    def onboarding(self, actor):
        with self.database.read() as c:
            current_account(c, actor)
            state = status(c, actor.person_id)
            result = {**state, 'full_name': actor.full_name, 'daily_hours': 8, 'weekly_hours': 40}
            result['staffing_roles'] = sorted(actor.roles & {'POD_LEAD', 'POD_MEMBER'})
            if state['status'] == 'DRAFT':
                result['skills'] = rows(c, "SELECT interest_id,interest_name FROM interests WHERE assessment_type='SELF_RATED' ORDER BY interest_name")
                # Names can intentionally repeat across project types. Return the
                # catalogue context so first-login users can distinguish the
                # exact deliverable without changing or collapsing its mapping.
                catalogue = rows(c, """SELECT deliverable_id,deliverable_name,project_name
                    FROM deliverables WHERE active_flag='Y'
                    ORDER BY deliverable_name,project_name,deliverable_id""")
                result['deliverables'] = [{**item, 'display_name':
                    f"{item['deliverable_name']} — {item['project_name']}"} for item in catalogue]
            return result

    def submit(self, actor, body):
        with self.database.write() as c:
            rows(c, 'SELECT person_id FROM people WHERE person_id=:pid FOR UPDATE WAIT 5', pid=actor.person_id)
            current_account(c, actor)
            state = status(c, actor.person_id)
            demand(state['status'] == 'DRAFT' and state['revision'] == body.revision, 'Setup was already submitted or changed. Reload to check its status.')
            # New imported profiles only. Never overwrite legacy assessments or source work.
            for table in ('PERSON_INTERESTS', 'AVAILABILITY', 'POD_ASSIGNMENTS'):
                demand(not rows(c, f'SELECT person_id FROM {table} WHERE person_id=:pid', pid=actor.person_id),
                       'This profile already contains staffing data and cannot use first-login setup.')
            profile = rows(c, 'SELECT weekly_work_hours,deliverable_experience_json FROM people WHERE person_id=:pid', pid=actor.person_id)[0]
            demand(Decimal(str(profile['weekly_work_hours'])) == 40 and document(profile['deliverable_experience_json'] or '[]') == [], 'Initial profile must have 40 contracted hours and no imported assessments.')
            today = rows(c, 'SELECT TRUNC(SYSDATE) today FROM dual')[0]['today']
            demand(body.starts_on <= calendar_day(today) <= body.ends_on, 'The confirmed capacity period must include today.')
            skills = {r['interest_id'] for r in rows(c, "SELECT interest_id FROM interests WHERE assessment_type='SELF_RATED'")}
            deliverables = {r['deliverable_id'] for r in rows(c, "SELECT deliverable_id FROM deliverables WHERE active_flag='Y'")}
            demand(all(s.skill_id in skills for s in body.skills), 'Select only existing self-rated skills.')
            demand(all(d.deliverable_id in deliverables for d in body.deliverables), 'Select only active catalogue deliverables.')
            for skill in body.skills:
                demand(skill.strength is not None or skill.interested, 'An unrated skill must express learning interest.')
                execute(c, """INSERT INTO person_interests(person_id,interest_id,strength,interested_flag,evidence_note,source)
                    VALUES(:pid,:skill,:strength,:interested,:evidence,'Self-assessment')""",
                    pid=actor.person_id, skill=skill.skill_id, strength=skill.strength,
                    interested='Y' if skill.interested else 'N', evidence=skill.evidence or None)
            experiences = [{'deliverableId': d.deliverable_id, 'experienceLevel': d.experience_level.value,
                'contributionScope': d.contribution_scope, 'interested': d.interested, 'experience': d.experience} for d in body.deliverables]
            from app.execution_store import execute as clob_execute
            clob_execute(c, 'UPDATE people SET deliverable_experience_json=:payload,skills_version=skills_version+1,workload_version=workload_version+1 WHERE person_id=:pid',
                         {'payload': json_text(experiences), 'pid': actor.person_id}, ('payload',))
            for w in body.work:
                if w.kind == 'POD':
                    demand(w.role_code in actor.roles, 'Existing POD claims must use an explicitly granted role.')
                    execute(c, """INSERT INTO roster_pod_claims(claim_id,person_id,title,starts_on,ends_on,total_hours,role_code)
                        VALUES(:id,:pid,:title,:startDay,:endDay,:hours,:role)""", id='RC'+uuid4().hex[:26], pid=actor.person_id,
                        title=w.title, startDay=w.starts_on, endDay=w.ends_on, hours=w.total_hours, role=w.role_code)
                else:
                    execute(c, """INSERT INTO availability(person_id,event_type,starts_on,ends_on,title,allocated_hours,capacity_kind,created_by)
                        VALUES(:pid,:kind,:startDay,:endDay,:title,:hours,:capacityKind,:actor)""",
                        pid=actor.person_id, kind='Leave' if w.kind == 'LEAVE' else 'Commitment', startDay=w.starts_on,
                        endDay=w.ends_on, title=w.title, hours=w.total_hours,
                        capacityKind='NON_AVAILABILITY' if w.kind == 'LEAVE' else 'EXTERNAL_WORK', actor=actor.subject)
            refresh(SameConnection(c), actor.person_id, body.starts_on, body.ends_on, actor.subject, commit=True)
            next_status = 'COMPLETE'
            clob_execute(c, """UPDATE roster_onboarding SET status=:state,revision=revision+1,submitted_json=:payload,
                completed_at=CASE WHEN :state='COMPLETE' THEN SYSTIMESTAMP ELSE NULL END WHERE person_id=:pid""",
                {'state': next_status, 'payload': json_text(body.model_dump(mode='json')), 'pid': actor.person_id}, ('payload',))
            audit(c, actor, actor.person_id, 'ONBOARDING_SUBMITTED', 'Self-reported dated inputs saved; immediate access. Reported POD hours count without creating assignments.')
            return {'status': next_status, 'revision': body.revision+1}
