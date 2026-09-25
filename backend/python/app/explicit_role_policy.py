"""Offline preparation of a new exact-role policy revision. Never opens Oracle.

Export an approved StaffingPolicy JSON from the read-only audit, review this
preview, then provision the SQL during the controlled maintenance window. The
script does NOT switch staffing_policy_control or any runtime flag. Switching
the pointer is a separate operator-approved cutover after schema verification.
"""
import argparse
import json
import re
from pathlib import Path

from app.policy import StaffingPolicy


def revised_policy(previous: StaffingPolicy, version: str, operator: str, approved_at: str) -> StaffingPolicy:
    previous.require_published()
    if (not re.fullmatch(r'[A-Za-z0-9_-]{1,60}', version) or version == previous.version
        or not operator.strip() or len(operator) > 255):
        raise ValueError('A distinct safe policy version and a named operator are required')
    # Require an unambiguous timestamp in previews; SQL approval uses the DB clock.
    from datetime import datetime
    if datetime.fromisoformat(approved_at.replace('Z', '+00:00')).tzinfo is None:
        raise ValueError('Approval timestamp requires a timezone')
    return StaffingPolicy.model_validate({**previous.model_dump(), 'version': version,
        'approved_by': operator.strip(), 'approved_at': approved_at,
        'lead_role_code': 'POD_LEAD', 'member_role_codes': ('POD_MEMBER',)})


def migration_sql(previous: StaffingPolicy, revision: StaffingPolicy) -> str:
    """Clone immutable policy records while preserving every non-role rule."""
    expected = revised_policy(previous, revision.version, revision.approved_by or '', revision.approved_at or '')
    if revision != expected:
        raise ValueError('This migration can change only explicit staffing-role rules')
    def quote(text):
        return "'" + text.replace("'", "''") + "'"
    old, new, actor = map(quote, (previous.version, revision.version, revision.approved_by))
    return f"""-- Generated offline. Review before applying; no live command was executed.
-- Requires Phase 2 schema verification and a controlled maintenance window.
-- Creates a NEW approved revision. Does not edit history or switch active policy.
-- Inspect an existing revision instead of blindly retrying an uncertain commit.
SET DEFINE OFF
WHENEVER SQLERROR EXIT FAILURE ROLLBACK
DECLARE
    source_count NUMBER;
    target_count NUMBER;
    maintenance_count NUMBER;
    active_version VARCHAR2(60);
BEGIN
    IF USER<>'AI_POD_STAFFING' THEN
        RAISE_APPLICATION_ERROR(-20005,'Connect as AI_POD_STAFFING; no changes applied.');
    END IF;
    SELECT COUNT(*) INTO maintenance_count FROM staffing_runtime
      WHERE runtime_id=1 AND agents_enabled='N' AND notifications_enabled='N';
    IF maintenance_count<>1 THEN
        RAISE_APPLICATION_ERROR(-20006,'Stop application services and disable agent/notification switches before provisioning.');
    END IF;
    SELECT COUNT(*) INTO maintenance_count FROM agent_executions WHERE status IN ('QUEUED','RUNNING');
    IF maintenance_count<>0 THEN
        RAISE_APPLICATION_ERROR(-20007,'Queued/running executions exist; resolve them before provisioning.');
    END IF;
    SELECT policy_version INTO active_version FROM staffing_policy_control WHERE control_id=1 FOR UPDATE NOWAIT;
    IF active_version<>{old} THEN
        RAISE_APPLICATION_ERROR(-20008,'Active policy changed since the preview; export and review it again.');
    END IF;
    SELECT COUNT(*) INTO source_count FROM staffing_policies
      WHERE policy_version={old} AND status='APPROVED';
    SELECT COUNT(*) INTO target_count FROM staffing_policies WHERE policy_version={new};
    IF source_count<>1 OR target_count<>0 THEN
        RAISE_APPLICATION_ERROR(-20001,'Source must be approved and target must not exist. Inspect policy state before retrying.');
    END IF;
    INSERT INTO staffing_policies(policy_version,status,description,created_by)
      VALUES({new},'DRAFT','Explicit Lead and Member grants; no inherited slot eligibility',{actor});
    INSERT INTO eligibility_rules(policy_version,rule_code,rule_value_json)
      SELECT {new},rule_code,rule_value_json FROM eligibility_rules WHERE policy_version={old};
    IF SQL%ROWCOUNT<>4 THEN RAISE_APPLICATION_ERROR(-20002,'Source eligibility rules incomplete'); END IF;
    UPDATE eligibility_rules SET rule_value_json='{{"value":"POD_LEAD"}}'
      WHERE policy_version={new} AND rule_code='LEAD_ROLE';
    UPDATE eligibility_rules SET rule_value_json='{{"value":["POD_MEMBER"]}}'
      WHERE policy_version={new} AND rule_code='MEMBER_ROLES';
    INSERT INTO scoring_weights(policy_version,skill_weight,deliverable_weight,capacity_weight,interest_weight)
      SELECT {new},skill_weight,deliverable_weight,capacity_weight,interest_weight
      FROM scoring_weights WHERE policy_version={old};
    IF SQL%ROWCOUNT<>1 THEN RAISE_APPLICATION_ERROR(-20003,'Source scoring weights incomplete'); END IF;
    INSERT INTO load_guardrails(policy_version,default_weekly_hours,maximum_allocation_pct,scheduling_timezone)
      SELECT {new},default_weekly_hours,maximum_allocation_pct,scheduling_timezone
      FROM load_guardrails WHERE policy_version={old};
    IF SQL%ROWCOUNT<>1 THEN RAISE_APPLICATION_ERROR(-20004,'Source load guardrails incomplete'); END IF;
    UPDATE staffing_policies SET status='APPROVED',approved_by={actor},approved_at=SYSTIMESTAMP
      WHERE policy_version={new};
    INSERT INTO audit_events(audit_event_id,entity_type,entity_id,action_type,actor_subject,correlation_id,reason)
      VALUES(RAWTOHEX(SYS_GUID()),'STAFFING_POLICY',{new},'EXPLICIT_ROLE_POLICY_PREPARED',{actor},
        RAWTOHEX(SYS_GUID()),'Cloned approved policy; changed only slot-role eligibility; active pointer retained');
END;
/
COMMIT;
"""


def policy_from_document(value: dict) -> StaffingPolicy:
    """Accept the Phase 1 read-only audit report or a bare policy export."""
    return StaffingPolicy.model_validate(value['active_policy'] if 'active_policy' in value else value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy-json', required=True, help='Read-only roster audit report or approved StaffingPolicy JSON')
    parser.add_argument('--version', required=True)
    parser.add_argument('--operator', required=True)
    parser.add_argument('--approved-at', required=True, help='Timezone-qualified intended approval time')
    parser.add_argument('--sql', action='store_true', help='Print provisioning SQL instead of the preview')
    args = parser.parse_args()
    previous = policy_from_document(json.loads(Path(args.policy_json).read_text(encoding='utf-8-sig')))
    revision = revised_policy(previous, args.version, args.operator, args.approved_at)
    if args.sql:
        print(migration_sql(previous, revision))
    else:
        print(json.dumps({'writes': 0, 'model_calls': 0, 'active_policy_unchanged': True,
            'source_policy_version': previous.version, 'proposed_policy': revision.model_dump(mode='json')}, indent=2))


if __name__ == '__main__':
    main()
