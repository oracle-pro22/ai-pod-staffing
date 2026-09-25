from unittest.mock import patch

import pytest

from app import onboarding_schema as schema
from app.errors import ServiceError


def catalog(c, query, **binds):
    table = binds.get('name')
    if 'user_tab_columns' in query:
        result = []
        for name in schema.COLUMNS[table]:
            kind = ('CLOB' if name.endswith('_JSON') else 'NUMBER' if name in ('CONTROL_ID', 'REVISION', 'TOTAL_HOURS')
                else 'DATE' if name in ('STARTS_ON', 'ENDS_ON') else 'TIMESTAMP(6) WITH TIME ZONE' if name.endswith('_AT') else 'VARCHAR2')
            result.append({'column_name': name, 'data_type': kind, 'nullable': 'Y' if name in schema.NULLABLE else 'N'})
        return result
    if "status<>'ENABLED'" in query:
        return []
    if "constraint_type='P'" in query:
        return [{'column_name': schema.PRIMARY_KEYS[table]}]
    if "constraint_type='C'" in query:
        return [{'condition': s} for s in schema.CHECKS[table]]
    if "constraint_type='R'" in query:
        return [{'table_name': a, 'parent_table': b, 'column_name': col, 'parent_column': col} for a, b, col in [
            ('ROSTER_ONBOARDING', 'PEOPLE', 'PERSON_ID'), ('ROSTER_POD_CLAIMS', 'ROSTER_ONBOARDING', 'PERSON_ID'),
            ('ROSTER_POD_CLAIMS', 'POD_ASSIGNMENTS', 'ASSIGNMENT_ID')]]
    if "constraint_type='U'" in query:
        return [{'column_name': 'ASSIGNMENT_ID'}]
    if 'roster_access_control' in query:
        return [{'revision': 1}]
    raise AssertionError(query)


def test_schema_check_is_readonly_and_checks_all_structures():
    with patch.object(schema, 'rows', side_effect=catalog) as sql:
        result = schema.verify(None)
    assert result['verified'] and result['writes'] == 0 and result['accounts_enrolled'] == 0
    assert all(call.args[1].lstrip().startswith('SELECT') for call in sql.call_args_list)


@pytest.mark.parametrize('defect', ['missing_column', 'wrong_type', 'nullable_required', 'disabled', 'wrong_pk', 'missing_check', 'wrong_fk', 'missing_unique', 'missing_lock'])
def test_schema_drift_fails_closed(defect):
    def changed(c, query, **binds):
        result = catalog(c, query, **binds)
        if 'user_tab_columns' in query:
            if defect == 'missing_column':
                return result[1:]
            if defect == 'wrong_type':
                result[0]['data_type'] = 'BLOB'
            if defect == 'nullable_required':
                result[0]['nullable'] = 'Y'
        if defect == 'disabled' and "status<>'ENABLED'" in query:
            return [{'constraint_name': 'DISABLED'}]
        if defect == 'wrong_pk' and "constraint_type='P'" in query:
            return [{'column_name': 'STATUS'}]
        if defect == 'missing_check' and "constraint_type='C'" in query:
            return []
        if defect == 'wrong_fk' and "constraint_type='R'" in query:
            result[0]['parent_column'] = 'OTHER'
        if defect == 'missing_unique' and "constraint_type='U'" in query:
            return []
        if defect == 'missing_lock' and 'roster_access_control' in query:
            return []
        return result
    with patch.object(schema, 'rows', side_effect=changed), pytest.raises(ServiceError):
        schema.verify(None)


def test_check_normalization_does_not_erase_boolean_grouping():
    assert schema.normalized_check('("X" = 1 OR "X" = 2) AND Y = 3') != schema.normalized_check('"X" = 1 OR ("X" = 2 AND Y = 3)')
