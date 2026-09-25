import inspect
import json
import zipfile
from unittest.mock import MagicMock
from xml.sax.saxutils import escape

import pytest

from app import roster_audit as audit
from app.errors import ServiceError


def workbook(tmp_path, *, email="amy.test@oracle.com", tester="Yes", access="Yes", duplicate=False, formula=False):
    path = tmp_path / "roster.xlsx"
    headings = ["Manager", "Name", "Email", "POD Captain", "Pod Lead", "Pod Member", "Admin", "Tester", "Grant Tool Access"]
    values = [headings, ["External Manager", "Amy Test", email, "Yes", "Yes", "No", "", tester, access]]
    if duplicate:
        values.append(["Other Manager", "Another Person", email.upper(), "", "Yes", "Yes", "", "No", "Timing TBD"])
    data = []
    for number, row in enumerate(values, 1):
        cells = []
        for index, value in enumerate(row):
            computation = "<f>1+1</f>" if formula and number == 2 and index == 2 else ""
            cells.append(f'<c r="{chr(65 + index)}{number}" t="inlineStr">{computation}<is><t>{escape(value)}</t></is></c>')
        data.append(f'<row r="{number}">{"".join(cells)}</row>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{audit.NS["m"]}" xmlns:r="{audit.DOC_REL_NS}"><sheets><sheet name="Team-Role" sheetId="1" r:id="r1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", f'<Relationships xmlns="{audit.REL_NS}"><Relationship Id="r1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{audit.NS["m"]}"><sheetData>{"".join(data)}</sheetData></worksheet>')
    return path


def test_roster_exact_grants_disabled_account_and_default_hours(tmp_path):
    source = audit.read_workbook(workbook(tmp_path, access="Timing TBD"))
    person = source["people"][0]
    assert person["roles"] == ["POD_CAPTAIN", "POD_LEAD"]
    assert person["account_enabled"] is False
    assert person["initial_daily_hours"] == 8 and person["initial_weekly_hours"] == 40
    assert person["onboarding_required"]
    assert "tester" not in person
    assert audit.source_summary(source)["disabled"] == 1


def test_tester_does_not_control_access_or_roles(tmp_path):
    a = audit.read_workbook(workbook(tmp_path, tester="Yes"))
    b = audit.read_workbook(workbook(tmp_path, tester="No"))
    assert a["people"] == b["people"]
    assert audit.source_summary(a) == audit.source_summary(b)


@pytest.mark.parametrize("options", [
    {"duplicate": True}, {"email": "not-an-oracle-address@example.com"},
    {"access": "Maybe"}, {"formula": True},
])
def test_ambiguous_source_is_rejected(tmp_path, options):
    with pytest.raises((ServiceError, ValueError)):
        audit.read_workbook(workbook(tmp_path, **options))


def test_header_order_is_not_used_for_hierarchy(tmp_path):
    source = audit.read_workbook(workbook(tmp_path))
    source["people"][0]["roles"] = ["POD_MEMBER", "POD_LEAD", "POD_CAPTAIN", "SYSTEM_ADMINISTRATOR"]
    summary = audit.source_summary(source)
    assert summary["enabled_display_roles"] == {"SYSTEM_ADMINISTRATOR": 1}
    assert summary["external_manager_names"] == ["External Manager"]


def test_identity_matching_never_copies_assessments_or_reuses_subjects(tmp_path):
    source = audit.read_workbook(workbook(tmp_path))
    people = [{"person_id": "P-1", "full_name": "Amy Test", "email_address": "old@oracle.com"}]
    report = audit.reconcile(source, people, [], [{"person_id": "P-1", "role_code": "POD_MEMBER", "active_flag": "Y"}])
    row = report["rows"][0]
    assert row["match_status"] == "name_only_review_required"
    assert not row["copy_existing_assessments"] and not row["reuse_identity_automatically"]
    assert row["roles_to_remove"] == ["POD_MEMBER"]
    assert report["strategy"] == "archive_existing_then_create_roster"


def test_email_name_disagreement_is_flagged(tmp_path):
    source = audit.read_workbook(workbook(tmp_path))
    people = [{"person_id": "P-1", "full_name": "Other", "email_address": "amy.test@oracle.com"},
              {"person_id": "P-2", "full_name": "Amy Test", "email_address": "old@oracle.com"}]
    report = audit.reconcile(source, people, [], [])
    assert report["rows"][0]["match_status"] == "ambiguous_identity"


def test_archive_order_follows_foreign_keys_and_reports_cycles():
    fks = [{"child_table": "APP_SESSIONS", "parent_table": "APP_ACCOUNTS"},
           {"child_table": "APP_ACCOUNTS", "parent_table": "PEOPLE"}]
    ordered, cycles = audit.archive_order({"APP_SESSIONS", "APP_ACCOUNTS", "PEOPLE"}, fks)
    assert ordered == ["APP_SESSIONS", "APP_ACCOUNTS", "PEOPLE"] and not cycles
    assert audit.archive_order({"PEOPLE"}, [{"child_table": "PEOPLE", "parent_table": "PEOPLE"}]) == ([], ["PEOPLE"])


def test_protected_fingerprint_tracks_same_count_changes_and_reordering():
    metadata = [{"column_name": "ID", "data_type": "VARCHAR2"}]

    def fingerprint(records):
        c = MagicMock()
        c.cursor.return_value.__enter__.return_value.fetchmany.side_effect = [records, []]
        return audit.protected_fingerprint(c, "DELIVERABLES", metadata)

    assert fingerprint([("A",), ("B",)]) == fingerprint([("B",), ("A",)])
    assert fingerprint([("A",), ("B",)]) != fingerprint([("A",), ("C",)])
    with pytest.raises(ServiceError):
        audit.protected_fingerprint(MagicMock(), "APP_ACCOUNTS", metadata)


def test_audit_is_read_only_and_captures_unknown_consumers(tmp_path, monkeypatch):
    source = audit.read_workbook(workbook(tmp_path))
    tables = {"PEOPLE", "APP_ACCOUNTS", "APP_USER_ROLES", "REQUESTS", "POD_ASSIGNMENTS", "NEW_CONSUMER", "AIPS_OLD_BACKUP",
              "RM2_DDL_BACKUP", "DBTOOLS$EXECUTION_HISTORY"}
    sql_seen = []

    def query(c, sql, **binds):
        sql_seen.append(sql)
        assert sql.lstrip().upper().startswith("SELECT")
        assert "PASSWORD_HASH" not in sql.upper() and "TOKEN_HASH" not in sql.upper()
        if "FROM user_tables" in sql:
            return [{"table_name": t} for t in tables]
        if "FROM user_constraints" in sql:
            return [{"child_table": "NEW_CONSUMER", "parent_table": "PEOPLE", "constraint_name": "NEW_FK"}]
        if "COUNT(*)" in sql:
            return [{"n": 0}]
        return []

    monkeypatch.setattr(audit, "rows", query)
    result = audit.audit_database(MagicMock(), source)
    assert result["writes"] == 0 and result["database_audited"]
    assert not result["archive_created"] and not result["recovery_tested"]
    assert result["review_blockers"]["unclassified_tables"] == ["NEW_CONSUMER"]
    assert result["review_blockers"]["incoming_references_outside_scope"][0]["constraint_name"] == "NEW_FK"
    assert result["retained_prior_backups"] == ["AIPS_OLD_BACKUP"]
    assert result["retained_non_application_tables"] == ["DBTOOLS$EXECUTION_HISTORY", "RM2_DDL_BACKUP"]
    assert not any("FROM RM2_DDL_BACKUP" in sql.upper() or "FROM DBTOOLS$EXECUTION_HISTORY" in sql.upper() for sql in sql_seen)
    grant_sql = next(sql for sql in sql_seen if "FROM app_user_roles" in sql)
    assert "ur.effective_from<=TRUNC(SYSDATE)" in grant_sql
    assert "ur.effective_to>=TRUNC(SYSDATE)" in grant_sql
    assert sql_seen
    code = inspect.getsource(audit)
    assert "with db.read()" in code and "db.write(" not in code
    assert "commit(" not in code


def test_offline_report_never_connects_or_overwrites(tmp_path, monkeypatch, capsys):
    path = workbook(tmp_path)
    target = tmp_path / "report.json"
    monkeypatch.setattr("sys.argv", ["roster_audit", "--workbook", str(path), "--output", str(target), "--offline"])
    assert audit.main() == 0
    result = json.loads(target.read_text(encoding="utf-8"))
    assert not result["database_audited"]
    original = target.read_bytes()
    assert audit.main() == 1 and target.read_bytes() == original
    assert "ROSTER_AUDIT_INVALID" in capsys.readouterr().err


def test_scope_preserves_catalogue_settings_and_includes_all_history():
    assert set(audit.ARCHIVE_TABLES).isdisjoint(audit.PROTECTED_TABLES)
    assert {"MVP_P2_REVIEWS", "MVP_P2_SELECTIONS", "MVP_P2_DECISIONS", "MVP_P3_DRAFTS", "MVP_P3_RESOLUTIONS",
            "APP_ACCOUNTS", "APP_SESSIONS", "AUDIT_EVENTS"} <= set(audit.ARCHIVE_TABLES)
    assert {"DELIVERABLES", "DELIVERABLE_SKILLS", "INTERESTS", "STAFFING_RUNTIME", "ROLE_PERMISSIONS"} <= set(audit.PROTECTED_TABLES)
