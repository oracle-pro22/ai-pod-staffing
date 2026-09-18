from collections import Counter
from contextlib import ExitStack
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.demo_dataset import demonstration_people
from app.errors import ServiceError
from app.mvp_phase1 import (GUARDS, PROTECTED, REQUEST_TABLES, SNAPSHOT_TABLES, Manifest, archive_requests,
                           canonical, check_preservation, digest, fingerprints, packed, profile_fingerprints,
                           selected_request_rows, snapshot_hash)
from app.mvp_roster import PERSON_RENAMES, additional_people, placeholder_email
from app import mvp_phase1 as migration


def manifest(**changes):
    return Manifest(batch_id='mvp1-test', anchor=date(2026,9,14), account_emails={'P-001': 'alex@oracle.com'},
                    expected_snapshot='a'*64, **changes)


def test_manifest_is_strict_normalized_and_immutable():
    m = manifest()
    assert m.model_copy(update={}).account_emails == {'P-001': 'alex@oracle.com'}
    with pytest.raises(ValidationError):
        m.batch_id = 'changed'
    with pytest.raises(ValidationError):
        manifest(person_id_map={'P-001': 'P-002', 'P-002': 'P-003'})
    with pytest.raises(ValidationError):
        manifest(person_id_map={'P-001': 'P-003', 'P-002': 'P-003'})
    with pytest.raises(ValidationError):
        manifest(archive_request_ids=("REQ-1';DELETE",))
    with pytest.raises(ValidationError):
        manifest(archive_request_ids=('REQ-1', 'REQ-1'))


def test_roster_totals_keep_one_administrator_and_existing_profiles_untouched():
    before = demonstration_people()
    added = additional_people()
    assert Counter(p.role_code for p in (*before, *added)) == {
        'POD_CAPTAIN': 4, 'POD_LEAD': 6, 'POD_MEMBER': 20, 'SYSTEM_ADMINISTRATOR': 1}
    assert len(added) == 14 and len(set(p.person_id for p in added)) == 14
    assert not set(p.person_id for p in before) & set(p.person_id for p in added)
    assert before == demonstration_people()
    assert all(p.skills and p.deliverables and p.external_weekly_hours > 0 for p in added)
    assert placeholder_email('Alex Rivera') == 'alex.rivera@oracle.com'
    assert set(PERSON_RENAMES.values()) == {f'P-{n:03}' for n in range(13,18)}


def test_archival_serializer_preserves_dates_decimals_and_large_evidence():
    value = {'day': date(2026,9,14), 'timestamp': datetime(2026,9,14,1,2,3,4), 'hours': Decimal('12.35'), 'evidence': 'x'*100000}
    encoded = packed(value)
    assert encoded['hours'] == {'$decimal': '12.35'}
    assert canonical(encoded) == canonical(value)
    assert digest(encoded) == digest(value)
    assert migration.unpacked(encoded) == value


def empty_snapshot():
    return {table: [] for table in (*PROTECTED, *SNAPSHOT_TABLES)}


def test_request_selection_follows_only_listed_foreign_keys():
    saved = empty_snapshot()
    for table in REQUEST_TABLES:
        if table not in ('ASSIGNMENT_DAYS','POD_PROPOSAL_MEMBERS','AGENT_EXECUTION_EVENTS'):
            saved[table] = [{'request_id':'REQ-1'}, {'request_id':'REQ-2'}]
    for table, key in (('POD_PROPOSALS','proposal_id'), ('POD_ASSIGNMENTS','assignment_id'), ('AGENT_EXECUTIONS','execution_id')):
        for i,r in enumerate(saved[table], 1): r[key]=f'parent-{i}'
    for table,key in (('ASSIGNMENT_DAYS','assignment_id'), ('POD_PROPOSAL_MEMBERS','proposal_id'), ('AGENT_EXECUTION_EVENTS','execution_id')):
        saved[table]=[{key:'parent-1'}, {key:'parent-2'}]
    chosen = selected_request_rows(saved, ['REQ-1'])
    assert all(len(v)==1 for v in chosen.values())
    assert all('REQ-2' not in str(v) and 'parent-2' not in str(v) for v in chosen.values())


def test_delete_commands_are_bound_scoped_and_child_first():
    with patch('app.mvp_phase1.sql') as execute:
        archive_requests(MagicMock(), manifest(archive_request_ids=('REQ-1',)))
    commands = [call.args[1] for call in execute.call_args_list]
    assert len(commands) == len(REQUEST_TABLES)
    assert all('WHERE' in query and ':id' in query for query in commands)
    assert all(call.kwargs == {'id': 'REQ-1'} for call in execute.call_args_list)
    assert commands.index('DELETE FROM POD_ASSIGNMENTS WHERE request_id=:id') < commands.index('DELETE FROM POD_PROPOSALS WHERE request_id=:id')
    assert all(not any(f'DELETE FROM {t} ' in q for t in PROTECTED) for q in commands)


def test_protected_fingerprints_detect_content_change_with_same_row_count():
    a, b = empty_snapshot(), empty_snapshot()
    a['DELIVERABLES'] = [{'deliverable_id':'D-1', 'active_flag':'Y'}]
    b['DELIVERABLES'] = [{'deliverable_id':'D-1', 'active_flag':'N'}]
    assert snapshot_hash(a) != snapshot_hash(b)
    with patch('app.mvp_phase1.snapshot', return_value=b), pytest.raises(ServiceError) as error:
        check_preservation(MagicMock(), a, manifest())
    assert error.value.code == 'MVP_PROTECTED_CHANGE'


def test_existing_evidence_comparison_allows_only_id_relink():
    a, b = empty_snapshot(), empty_snapshot()
    a['PEOPLE'] = [{'person_id':'P-900101', 'deliverable_experience_json':'[]'}]
    a['PERSON_INTERESTS'] = [{'person_id':'P-900101','interest_id':'SK-1','strength':4,'evidence_note':'Preserve this'}]
    b['PEOPLE'] = [{'person_id':'P-013', 'deliverable_experience_json':'[]'}]
    b['PERSON_INTERESTS'] = [{**a['PERSON_INTERESTS'][0], 'person_id':'P-013'}]
    assert profile_fingerprints(a, {'P-900101':'P-013'}) == profile_fingerprints(b)
    b['PERSON_INTERESTS'][0]['strength'] = 5
    assert profile_fingerprints(a, {'P-900101':'P-013'}) != profile_fingerprints(b)


def test_fingerprints_ignore_query_order_not_values():
    assert fingerprints({'T':[{'a':1},{'a':2}]}) == fingerprints({'T':[{'a':2},{'a':1}]})
    assert fingerprints({'T':[{'a':1},{'a':2}]}) != fingerprints({'T':[{'a':1},{'a':1}]})


def test_migration_has_no_catalogue_or_permission_writes_or_global_reset():
    root = Path(__file__).resolve().parents[3]
    sql = (root/'sql/oracle/mvp_phase1.sql').read_text()
    assert 'DROP TABLE' not in sql and 'TRUNCATE' not in sql
    source = (root/'backend/python/app/mvp_phase1.py').read_text()
    for table in PROTECTED:
        assert f'UPDATE {table.lower()} ' not in source
        assert f'INSERT INTO {table.lower()}(' not in source
        assert f'DELETE FROM {table.lower()} ' not in source
    assert set(GUARDS) == {'P2_MEMBER_FREEZE','P2_PROPOSAL_FREEZE','P2_DECISION_APPEND','P2_EVENT_APPEND'}


def test_capacity_preview_compares_decimal_values_without_float_false_positives():
    day = date(2026, 9, 14)
    data = [[{'weekly_work_hours': 40, 'availability_version': 1}], [],
            [{'work_date': day, 'available_hours': 8.0, 'external_committed_hours': 1.6}]]
    with patch.object(migration, 'rows', side_effect=data), patch.object(migration, 'build_days', return_value={day: {'available': Decimal(8), 'external': Decimal('1.6')}}):
        migration.capacity_inputs(MagicMock(), 'P-001', day, day)
    data[-1][0]['external_committed_hours'] = 2
    with patch.object(migration, 'rows', side_effect=data), patch.object(migration, 'build_days', return_value={day: {'available': Decimal(8), 'external': Decimal('1.6')}}), pytest.raises(ServiceError):
        migration.capacity_inputs(MagicMock(), 'P-001', day, day)


def test_guard_recovery_attempts_every_guard_even_if_one_enable_fails():
    def failure(_c, query, **_binds):
        if GUARDS[0] in query:
            raise RuntimeError('Simulated disconnect')
    with patch.object(migration, 'sql', side_effect=failure) as sql, pytest.raises(ServiceError) as error:
        migration.enable_guards(MagicMock(), GUARDS)
    assert error.value.code == 'MVP_GUARD_RECOVERY'
    assert len(sql.call_args_list) == len(GUARDS)


def test_apply_failure_rolls_back_before_reenabling_all_guards():
    c = MagicMock()
    saved = empty_snapshot()
    m = manifest().model_copy(update={'expected_snapshot': snapshot_hash(saved)})
    guards = {name: {'status': 'ENABLED', 'sha256': 'hash'} for name in migration.RESTORE_GUARDS}
    events = []
    c.rollback.side_effect = lambda: events.append('rollback')
    with ExitStack() as stack:
        for name in ('require_schema', 'require_stopped', 'archive_requests', 'rename_people', 'verify_archive'):
            stack.enter_context(patch.object(migration, name))
        stack.enter_context(patch.object(migration, 'rows', return_value=[]))
        stack.enter_context(patch.object(migration, 'preflight', return_value=(saved, {}, MagicMock())))
        stack.enter_context(patch.object(migration, 'guard_fingerprints', return_value=guards))
        stack.enter_context(patch.object(migration, 'archive_snapshot', return_value={'guards': guards}))
        stack.enter_context(patch.object(migration, 'snapshot', return_value=saved))
        stack.enter_context(patch.object(migration, 'sql', side_effect=lambda _c, query: events.append(query)))
        stack.enter_context(patch.object(migration, 'insert_people', side_effect=RuntimeError('injected failure')))
        with pytest.raises(RuntimeError, match='injected'):
            migration.apply(c, m, 'test-operator', 'shared-test-password')
    c.commit.assert_not_called()
    c.rollback.assert_called_once()
    for name in GUARDS:
        assert events.index('rollback') < events.index(f'ALTER TRIGGER {name} ENABLE')


def test_restore_refuses_later_business_changes_before_any_ddl_or_delete():
    m = manifest()
    metadata = {'manifest': m.model_dump(mode='json'), 'after_snapshot': 'not-current'}
    with ExitStack() as stack:
        for name in ('require_schema', 'require_stopped', 'verify_archive'):
            stack.enter_context(patch.object(migration, name))
        stack.enter_context(patch.object(migration, 'rows', return_value=[{'status': 'APPLIED', 'metadata_json': metadata}]))
        stack.enter_context(patch.object(migration, 'snapshot', return_value=empty_snapshot()))
        sql = stack.enter_context(patch.object(migration, 'sql'))
        with pytest.raises(ServiceError, match='Business data changed'):
            migration.restore(MagicMock(), m.batch_id, commit=True)
        sql.assert_not_called()


def test_restore_serializes_oracle_decoded_json_and_preserves_timestamp_precision():
    types = {'person_id': 'VARCHAR2', 'deliverable_experience_json': 'CLOB', 'updated_at': 'TIMESTAMP(9) WITH TIME ZONE'}
    record = {'person_id': 'P-001', 'deliverable_experience_json': [{'experience': 'Unchanged evidence'}],
              'updated_at': '2026-09-14T10:12:13.123456789+05:30'}
    with patch.object(migration, 'column_types', return_value=types), patch.object(migration, 'execute') as sql:
        migration.insert_record(MagicMock(), 'PEOPLE', record, update_person=True)
    query, values, clobs = sql.call_args.args[1:]
    assert 'TO_TIMESTAMP_TZ(:updated_at,' in query
    assert values['updated_at'] == record['updated_at']
    assert values['deliverable_experience_json'] == canonical(record['deliverable_experience_json'])
    assert clobs == ('deliverable_experience_json',)


def test_verify_rejects_missing_account_links():
    with patch.object(migration, 'rows', return_value=[]), pytest.raises(ServiceError, match='roster is incomplete'):
        migration.check_account_links(MagicMock(), empty_snapshot(), manifest())


def test_sequence_advance_is_forward_only_and_does_not_loop_through_old_ids():
    for maximum, next_value, target in ((31, 13, 32), (900105, 32, 900106), (31, 900106, None)):
        result = [[{'n': maximum}], [{'last_number': next_value, 'increment_by': 1, 'cache_size': 0, 'cycle_flag': 'N'}]]
        with patch.object(migration, 'rows', side_effect=result), patch.object(migration, 'sql') as sql:
            migration.advance_sequence(MagicMock())
        if target:
            assert sql.call_args.args[1] == f'ALTER SEQUENCE person_id_seq RESTART START WITH {target}'
        else:
            sql.assert_not_called()


def test_person_copy_metadata_uses_oracle_virtual_column_dictionary():
    columns = [{'column_name': 'PERSON_ID'}, {'column_name': 'FULL_NAME'}]
    with patch.object(migration, 'rows', return_value=columns) as read:
        assert migration.person_copy_columns(MagicMock()) == ['PERSON_ID', 'FULL_NAME']
    query = read.call_args.args[1].upper()
    assert 'FROM USER_TAB_COLS' in query and 'USER_TAB_COLUMNS' not in query
    assert "VIRTUAL_COLUMN='NO'" in query and "USER_GENERATED='YES'" in query
    with patch.object(migration, 'rows', return_value=[]), pytest.raises(ServiceError):
        migration.person_copy_columns(MagicMock())


def test_rename_copies_parent_before_relinking_children_and_deleting_old_parent():
    m = manifest(person_id_map={'P-900101': 'P-013'})
    with patch.object(migration, 'person_copy_columns', return_value=['PERSON_ID', 'FULL_NAME', 'DELIVERABLE_EXPERIENCE_JSON']), \
         patch.object(migration, 'rows', side_effect=[[], [{'email_address': 'placeholder@oracle.com', 'external_identity_subject': 'previous-subject'}]]), \
         patch.object(migration, 'sql') as sql:
        migration.rename_people(MagicMock(), m)
    commands = [call.args[1] for call in sql.call_args_list]
    copy = 'INSERT INTO people(PERSON_ID,FULL_NAME,DELIVERABLE_EXPERIENCE_JSON) SELECT :newId,FULL_NAME,DELIVERABLE_EXPERIENCE_JSON FROM people WHERE person_id=:oldId'
    parent_index = commands.index(copy)
    delete_index = commands.index('DELETE FROM people WHERE person_id=:id')
    for table in migration.PERSON_CHILDREN - {'APP_ACCOUNTS'}:
        child_index = commands.index(f'UPDATE {table} SET person_id=:newId WHERE person_id=:oldId')
        assert parent_index < child_index < delete_index
    assert 'UPDATE people SET email_address=NULL,external_identity_subject=NULL WHERE person_id=:id' in commands[:parent_index]
    assert sql.call_args_list[parent_index].kwargs == {'newId': 'P-013', 'oldId': 'P-900101'}


def test_cli_reports_wrapped_oracle_code_without_driver_message_or_inputs():
    import oracledb
    underlying = oracledb.DatabaseError(SimpleNamespace(full_code='ORA-00904', message='private SQL and credential values'))
    wrapped = ServiceError('DATABASE_UNAVAILABLE', 'Generic failure', 503)
    wrapped.__cause__ = underlying
    assert migration.driver_error_details(wrapped) == {'driver_code': 'ORA-00904'}
    for code in ('DPY-4011', 'DPI-1080'):
        assert migration.driver_error_details(oracledb.DatabaseError(SimpleNamespace(full_code=code))) == {'driver_code': code}
    assert migration.driver_error_details(oracledb.DatabaseError(SimpleNamespace(full_code='ORA-00904 private-value'))) == {}
    wrapped.__cause__ = wrapped
    assert migration.driver_error_details(wrapped) == {}
