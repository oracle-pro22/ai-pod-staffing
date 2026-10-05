"""Offline history authorization, filters and pagination; no Oracle writes."""
import unittest
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.admin_audit import SOURCES, AuditQuery, decode_cursor, read_audit
from app.auth import Actor, Permission
from app.config import Settings
from app.errors import ServiceError
from app.main import create_app


def admin(scope='FULL', role='SYSTEM_ADMINISTRATOR'):
    return Actor('admin-subject', 'ADMIN', frozenset({role}),
                 (Permission(role, 'ADMINISTRATION', scope, frozenset({'view'})),))


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.connection = object()
        @contextmanager
        def read():
            yield self.connection
        self.database = SimpleNamespace(read=read, write=MagicMock(side_effect=AssertionError('Read only')))

    def test_role_and_full_scope_required_before_history(self):
        for actor in (admin(role='POD_CAPTAIN'), admin('OWN'), admin('SCOPED')):
            with self.subTest(actor=actor), patch('app.admin_audit.rows') as history, self.assertRaises(ServiceError):
                read_audit(self.database, actor, AuditQuery())
            history.assert_not_called()
        self.database.write.assert_not_called()

    def test_current_account_and_permission_are_rechecked(self):
        for records in ([], [{'active_flag': 'N'}], [{'active_flag': 'Y'}]):
            with self.subTest(records=records), patch('app.roster_lifecycle.rows', side_effect=[records, []]), \
                 patch('app.admin_audit.rows') as history, self.assertRaises(ServiceError):
                read_audit(self.database, admin(), AuditQuery())
            history.assert_not_called()

    def test_filters_are_bound_and_history_is_explicitly_projected(self):
        query = AuditQuery(kind='assignments', from_date='2026-10-01', to_date='2026-10-05',
                           request_id='REQ-1', actor="name' OR 1=1 --", action='CONFIRMED')
        with patch('app.admin_audit.authorize') as auth, patch('app.admin_audit.rows', return_value=[]) as read:
            result = read_audit(self.database, admin(), query)
        auth.assert_called_once_with(self.connection, admin(), 'ADMINISTRATION', 'view', 'SYSTEM_ADMINISTRATOR')
        sql, binds = read.call_args.args[1], read.call_args.kwargs
        self.assertNotIn(query.actor, sql)
        self.assertEqual(binds['actorText'], query.actor)
        self.assertEqual(binds['firstDay'], datetime(2026, 10, 1))
        self.assertEqual(binds['afterDay'], datetime(2026, 10, 6))
        self.assertEqual(binds['take'], 51)
        self.assertTrue(result['read_only'])
        self.assertEqual(result['records'], [])
        self.database.write.assert_not_called()
        for source in SOURCES.values():
            for forbidden in ('SELECT *', 'before_state_json', 'after_state_json', 'password', 'idempotency_key', 'app_sessions'):
                self.assertNotIn(forbidden, source)

    def test_keyset_cursor_ties_and_changed_filters(self):
        query = AuditQuery(kind='decisions', limit=1)
        records = [dict(record_id='D2', occurred_at='2026-10-05T01:02:03.000000'),
                   dict(record_id='D1', occurred_at='2026-10-05T01:02:03.000000')]
        with patch('app.admin_audit.authorize'), patch('app.admin_audit.rows', return_value=records):
            page = read_audit(self.database, admin(), query)
        self.assertEqual(len(page['records']), 1)
        next_query = query.model_copy(update={'cursor': page['next_cursor']})
        self.assertEqual(decode_cursor(next_query), (datetime(2026, 10, 5, 1, 2, 3), 'D2'))
        with patch('app.admin_audit.authorize'), patch('app.admin_audit.rows', return_value=records[1:]) as read:
            last = read_audit(self.database, admin(), next_query)
        self.assertIn('record_id<:beforeId', read.call_args.args[1])
        self.assertEqual(read.call_args.kwargs['beforeId'], 'D2')
        self.assertIsNone(last['next_cursor'])
        with self.assertRaises(ServiceError):
            decode_cursor(next_query.model_copy(update={'kind': 'events'}))
        for cursor in ('a', '____', 'e30'):
            with self.subTest(cursor=cursor), self.assertRaises(ServiceError):
                decode_cursor(AuditQuery(cursor=cursor))

    def test_query_limits_and_dates(self):
        for values in ({'kind': 'people'}, {'limit': 0}, {'limit': 101}, {'request_id': "' OR 1=1"},
                       {'from_date': '2026-10-06', 'to_date': '2026-10-05'}, {'to_date': '9999-12-31'}):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                AuditQuery(**values)

    def test_http_query_validation_and_read_only_route(self):
        database = MagicMock()
        client = TestClient(create_app(Settings(backend_env='test', backend_auth_mode='local',
            backend_local_token='x'*32, backend_local_subject='admin-subject'), database,
            verifier=SimpleNamespace(subject=lambda _: 'admin-subject'),
            authorization=SimpleNamespace(resolve=lambda _: admin())))
        with patch('app.main.read_audit', return_value={'records': [], 'read_only': True}) as history:
            response = client.get('/v1/admin/audit?kind=decisions&limit=25')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(history.call_args.args[2].limit, 25)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            history.reset_mock()
            for query in ('from_date=2026-10-06&to_date=2026-10-05', 'kind=people', 'limit=101'):
                self.assertEqual(client.get('/v1/admin/audit?' + query).status_code, 422)
            history.assert_not_called()
            self.assertEqual(client.post('/v1/admin/audit', json={}).status_code, 405)
