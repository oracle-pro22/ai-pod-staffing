"""Offline utilization boundaries, version fencing, permissions and transaction tests."""

from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth import Actor, Permission
from app.capacity import CapacityLedger, DailyHours, calculate_capacity, schedule_available_hours
from app.config import Settings
from app.errors import ServiceError
from app.main import create_app
from app.policy import DEFAULT_POLICY
from app.policy_admin import (
    PolicyAdminStore,
    UtilizationUpdate,
    active_policy_version,
    require_current_policy,
)


def actor(role="SYSTEM_ADMINISTRATOR", scope="FULL"):
    return Actor(
        "admin-subject",
        "P-012",
        frozenset({role}),
        (Permission(role, "BACKEND_CONFIGURATION", scope, frozenset({"view", "administer"})),),
    )


@pytest.mark.parametrize("value", ["0", "-1", "100.01", "NaN", "Infinity", "85.001"])
def test_invalid_limit(value):
    with pytest.raises(ValidationError):
        UtilizationUpdate(maximum_allocation_pct=value, expected_policy_version="old", reason="Change")


def test_reason_required():
    with pytest.raises(ValidationError):
        UtilizationUpdate(maximum_allocation_pct=85, expected_policy_version="old", reason="   ")


@pytest.mark.parametrize(
    "role,scope",
    [("POD_CAPTAIN", "FULL"), ("POD_LEAD", "FULL"), ("POD_MEMBER", "FULL"), ("SYSTEM_ADMINISTRATOR", "OWN")],
)
def test_only_full_administrator_may_read_or_save(role, scope):
    database = MagicMock()
    store = PolicyAdminStore(database)
    with pytest.raises(ServiceError) as error:
        store.get(actor(role, scope))
    assert error.value.code == "FORBIDDEN"
    with pytest.raises(ServiceError):
        store.update(
            actor(role, scope),
            UtilizationUpdate(maximum_allocation_pct=85, expected_policy_version="old", reason="Change"),
        )
    database.read.assert_not_called()
    database.write.assert_not_called()


def test_missing_pointer_fails_closed_and_old_version_is_blocked():
    with patch("app.policy_admin.rows", return_value=[]), pytest.raises(ServiceError):
        active_policy_version(None)
    with patch("app.policy_admin.rows", return_value=[{"policy_version": "new"}]) as query:
        with pytest.raises(ServiceError) as error:
            require_current_policy(None, "old", lock=True)
        assert error.value.code == "STALE_POLICY"
        assert "FOR UPDATE WAIT 5" in query.call_args.args[1]
        require_current_policy(None, "new")


def test_85_boundary_and_fractional_rounding():
    day = date(2026, 9, 16)
    ledger = CapacityLedger(weekly_hours=40)
    at = (DailyHours(day=day, hours=Decimal("6.80")),)
    over = (DailyHours(day=day, hours=Decimal("6.81")),)
    assert calculate_capacity(ledger, day, day, at, Decimal(85)).feasible
    assert not calculate_capacity(ledger, day, day, over, Decimal(85)).feasible


def test_partial_period_over_limit_is_not_hidden_by_week():
    start, end = date(2026, 9, 16), date(2026, 9, 18)
    ledger = CapacityLedger(
        external_work=tuple(DailyHours(day=date(2026, 9, d), hours=Decimal("5.6")) for d in (16, 17, 18))
    )
    # 70% before, four additional hours would be 86.67% in the three-day period.
    with pytest.raises(ValueError):
        schedule_available_hours(ledger, Decimal(4), start, end, Decimal(85))
    schedule = schedule_available_hours(ledger, Decimal("3.6"), start, end, Decimal(85))
    assert sum(row.hours for row in schedule) == Decimal("3.6")
    assert calculate_capacity(ledger, start, end, schedule, Decimal(85)).feasible


def test_leave_and_existing_over_limit_do_not_gain_headroom():
    day = date(2026, 9, 16)
    leave = CapacityLedger(absences=(DailyHours(day=day, hours=4),))
    assert calculate_capacity(
        leave, day, day, (DailyHours(day=day, hours=Decimal("3.4")),), Decimal(85)
    ).feasible
    assert not calculate_capacity(
        leave, day, day, (DailyHours(day=day, hours=Decimal("3.41")),), Decimal(85)
    ).feasible
    busy = CapacityLedger(external_work=(DailyHours(day=day, hours=7),))
    with pytest.raises(ValueError):
        schedule_available_hours(busy, Decimal(1), day, day, Decimal(85))


class Harness:
    def __init__(self, fail=False):
        self.pending, self.committed = [], []
        self.version = "old"
        self.previous = DEFAULT_POLICY.model_copy(
            update={
                "version": "old",
                "status": "APPROVED",
                "approved_by": "operator",
                "approved_at": "2026-09-15T00:00:00Z",
            }
        )

        @contextmanager
        def write():
            try:
                yield None
                self.committed.extend(self.pending)
            finally:
                self.pending.clear()

        self.store = PolicyAdminStore(SimpleNamespace(write=write))
        self.fail = fail

    def execute(self, _connection, sql, binds, *args):
        self.pending.append((sql, binds))
        if self.fail and "INSERT INTO audit_events" in sql:
            raise RuntimeError("audit unavailable")

    def load(self, _connection, version):
        return (
            self.previous
            if version == "old"
            else self.previous.model_copy(update={"version": version, "maximum_allocation_pct": Decimal(85)})
        )

    def save(self, expected="old"):
        with (
            patch("app.policy_admin.rows", return_value=[{"policy_version": self.version}]),
            patch("app.policy_admin.load_policy", side_effect=self.load),
            patch("app.execution_store.execute", side_effect=self.execute),
        ):
            return self.store.update(
                actor(),
                UtilizationUpdate(
                    maximum_allocation_pct=85, expected_policy_version=expected, reason="Restore agreed limit"
                ),
            )


def test_save_clones_policy_without_modifying_history():
    h = Harness()
    result = h.save()
    assert result.maximum_allocation_pct == 85
    assert result.version != "old"
    assert any("INSERT INTO audit_events" in sql for sql, _ in h.committed)
    assert any("UPDATE staffing_policy_control" in sql for sql, _ in h.committed)
    assert not any("UPDATE load_guardrails" in sql or "pod_assignments" in sql for sql, _ in h.committed)


def test_audit_failure_rolls_back_entire_change():
    h = Harness(fail=True)
    with pytest.raises(RuntimeError):
        h.save()
    assert h.committed == []


def test_concurrent_admin_edit_requires_refresh():
    h = Harness()
    h.version = "newer"
    with pytest.raises(ServiceError) as error:
        h.save()
    assert error.value.code == "STALE_POLICY"
    assert h.committed == []


@pytest.mark.parametrize("role", ["POD_CAPTAIN", "POD_LEAD", "POD_MEMBER", "SYSTEM_ADMINISTRATOR"])
def test_actual_api_permission_boundary(role):
    db = MagicMock()
    settings = Settings(_env_file=None)
    verifier = SimpleNamespace(subject=lambda _: "verified-subject")
    authorization = SimpleNamespace(resolve=lambda _: actor(role))
    app = create_app(settings=settings, database=db, verifier=verifier, authorization=authorization)
    with (
        patch("app.policy_admin.active_policy_version", return_value="old"),
        patch("app.policy_admin.load_policy", return_value=DEFAULT_POLICY),
        TestClient(app) as client,
    ):
        response = client.get("/v1/admin/utilization", headers={"x-staffing-role": "SYSTEM_ADMINISTRATOR"})
        assert response.status_code == (200 if role == "SYSTEM_ADMINISTRATOR" else 403)
        # Unchanged value exercises authenticated POST without mutating the fixture.
        response = client.post(
            "/v1/admin/utilization",
            json={
                "maximum_allocation_pct": 100,
                "expected_policy_version": "old",
                "reason": "Check permission",
            },
        )
        assert response.status_code == (200 if role == "SYSTEM_ADMINISTRATOR" else 403)


def test_approval_rejects_proposal_after_policy_switch():
    from test_phase4 import DecisionTests

    h = DecisionTests()
    h.setUp()
    try:
        with patch("app.policy_admin.rows", return_value=[{"policy_version": "new-85-policy"}]):
            with pytest.raises(ServiceError) as error:
                h.decide()
        assert error.value.code == "STALE_POLICY"
        assert h.committed == []
    finally:
        h.doCleanups()
