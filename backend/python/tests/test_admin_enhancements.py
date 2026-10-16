"""Offline shared-notepad contract, permission and transaction checks."""
import copy
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import oracledb
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.admin_enhancements import EnhancementUpdate, get_enhancements, read_document, save_enhancements
from app.auth import Actor, Permission
from app.config import Settings
from app.errors import ServiceError
from app.main import create_app


def admin(role='SYSTEM_ADMINISTRATOR', scope='FULL', actions=frozenset({'view', 'update'})):
    return Actor('admin-subject', 'ADMIN', frozenset({role}),
                 (Permission(role, 'ADMINISTRATION', scope, actions),), 'Test Administrator')


class NotepadTests(unittest.TestCase):
    def setUp(self):
        self.stored = dict(content='', revision=1, updated_by_name=None, updated_at=None)
        self.events = []
        self.connection = object()
        self.commits = 0

        @contextmanager
        def read():
            yield self.connection

        @contextmanager
        def write():
            old, events = copy.deepcopy(self.stored), list(self.events)
            try:
                yield self.connection
            except BaseException:
                self.stored, self.events = old, events
                raise
            else:
                self.commits += 1

        self.database = SimpleNamespace(read=read, write=write)

    def query(self, *_args, **_kwargs):
        return [dict(self.stored)]

    def execute(self, _connection, sql, binds, clobs=()):
        if sql.startswith('UPDATE'):
            self.assertEqual(clobs, ('content',))
            self.assertIn('NVL(:content,EMPTY_CLOB())', sql)
            self.stored.update(content=binds['content'], revision=self.stored['revision'] + 1,
                               updated_by_name=binds['name'], updated_at='2026-10-14T10:00:00.000000Z')
        else:
            self.events.append(binds)
        return 1

    @contextmanager
    def storage(self):
        with patch('app.admin_enhancements.authorize') as auth, \
             patch('app.admin_enhancements.rows', side_effect=self.query) as query, \
             patch('app.admin_enhancements.execute', side_effect=self.execute) as execute:
            yield auth, query, execute

    def test_full_admin_permission_required_for_read_and_write(self):
        for actor in (admin(role='POD_CAPTAIN'), admin(role='POD_LEAD'), admin(role='POD_MEMBER'), admin(scope='OWN')):
            with self.subTest(actor=actor), self.storage() as (_, query, execute):
                for action in (lambda: get_enhancements(self.database, actor),
                               lambda: save_enhancements(self.database, actor, EnhancementUpdate(content='x', expected_revision=1))):
                    with self.assertRaises(ServiceError) as caught:
                        action()
                    self.assertEqual(caught.exception.status, 403)
                query.assert_not_called()
                execute.assert_not_called()

    def test_view_only_admin_cannot_save(self):
        with self.storage(), self.assertRaises(ServiceError):
            save_enhancements(self.database, admin(actions=frozenset({'view'})), EnhancementUpdate(content='x', expected_revision=1))

    def test_permissions_rechecked_inside_transaction(self):
        with self.storage() as (auth, query, execute):
            auth.side_effect = ServiceError('FORBIDDEN', 'Permission withdrawn', 403)
            with self.assertRaises(ServiceError):
                save_enhancements(self.database, admin(), EnhancementUpdate(content='x', expected_revision=1))
            query.assert_not_called()
            execute.assert_not_called()
        self.assertEqual(self.commits, 0)

    def test_save_read_metadata_and_plain_text_preserved(self):
        content = '  Future ideas\n• Unicode: café 日本語\n<script>alert(1)</script>\n'
        with self.storage() as (auth, query, _):
            result = save_enhancements(self.database, admin(), EnhancementUpdate(content=content, expected_revision=1))
            self.assertEqual(result['content'], content)
            self.assertEqual(result['revision'], 2)
            self.assertEqual(result['updated_by_name'], 'Test Administrator')
            self.assertIn('FOR UPDATE WAIT 5', query.call_args_list[0].args[1])
            self.assertEqual(get_enhancements(self.database, admin()), result)
            self.assertEqual(auth.call_args.args[2:], ('ADMINISTRATION', 'view', 'SYSTEM_ADMINISTRATOR'))
        self.assertEqual(len(self.events), 1)
        self.assertNotIn(content, str(self.events))

    def test_two_admins_same_revision_cannot_overwrite(self):
        with self.storage():
            save_enhancements(self.database, admin(), EnhancementUpdate(content='First admin', expected_revision=1))
            with self.assertRaises(ServiceError) as caught:
                save_enhancements(self.database, admin(), EnhancementUpdate(content='Second admin', expected_revision=1))
        self.assertEqual((caught.exception.code, caught.exception.status), ('ENHANCEMENTS_CONFLICT', 409))
        self.assertEqual(self.stored['content'], 'First admin')
        self.assertEqual(len(self.events), 1)

    def test_unchanged_save_is_noop_and_empty_document_allowed(self):
        with self.storage() as (_, _, execute):
            save_enhancements(self.database, admin(), EnhancementUpdate(content='', expected_revision=1))
            execute.assert_not_called()
            save_enhancements(self.database, admin(), EnhancementUpdate(content='Some text', expected_revision=1))
            result = save_enhancements(self.database, admin(), EnhancementUpdate(content='', expected_revision=2))
        self.assertEqual(result['content'], '')
        self.assertEqual(result['revision'], 3)

    def test_audit_failure_rolls_back_note(self):
        def failure(connection, sql, binds, clobs=()):
            if sql.startswith('INSERT'):
                raise RuntimeError('audit failed')
            return self.execute(connection, sql, binds, clobs)
        with self.storage(), patch('app.admin_enhancements.execute', side_effect=failure), self.assertRaises(RuntimeError):
            save_enhancements(self.database, admin(), EnhancementUpdate(content='Not committed', expected_revision=1))
        self.assertEqual(self.stored['content'], '')
        self.assertEqual(self.commits, 0)

    def test_limits_types_and_forged_metadata(self):
        EnhancementUpdate(content='a' * 50000, expected_revision=1)
        for changes in ({'content': 'a' * 50001}, {'content': None}, {'expected_revision': 0},
                        {'expected_revision': True}, {'expected_revision': '1'}, {'updated_by_name': 'forged'}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                EnhancementUpdate(**({'content': 'x', 'expected_revision': 1} | changes))

    def test_missing_table_or_seed_is_explicit_setup_error(self):
        for value in ([], oracledb.DatabaseError(SimpleNamespace(code=942))):
            with patch('app.admin_enhancements.rows', **({'return_value': value} if isinstance(value, list) else {'side_effect': value})), \
                 self.assertRaises(ServiceError) as caught:
                read_document(self.connection)
            self.assertEqual(caught.exception.code, 'ENHANCEMENTS_SETUP_REQUIRED')

    def test_clob_is_read_before_connection_closes(self):
        lob = SimpleNamespace(read=lambda: 'Text from Oracle')
        with patch('app.admin_enhancements.rows', return_value=[self.stored | {'content': lob}]):
            self.assertEqual(read_document(self.connection)['content'], 'Text from Oracle')

    def test_http_validation_permissions_and_no_store(self):
        identity = admin()
        verifier = SimpleNamespace(subject=lambda _: 'subject')
        client = TestClient(create_app(Settings(backend_env='test', backend_auth_mode='local',
            backend_local_token='x' * 32, backend_local_subject='subject'), self.database, verifier=verifier,
            authorization=SimpleNamespace(resolve=lambda _: identity)))
        with self.storage():
            response = client.get('/v1/admin/enhancements')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertEqual(client.post('/v1/admin/enhancements', json={'content': 'Saved', 'expected_revision': 1}).status_code, 200)
            self.assertEqual(client.post('/v1/admin/enhancements', json={'content': 'Stale', 'expected_revision': 1}).status_code, 409)
            self.assertEqual(client.post('/v1/admin/enhancements', json={'content': 'Missing revision'}).status_code, 422)
            identity = admin(role='POD_MEMBER')
            self.assertEqual(client.get('/v1/admin/enhancements').status_code, 403)
            self.assertEqual(client.post('/v1/admin/enhancements', json={'content': 'Denied', 'expected_revision': 2}).status_code, 403)
            verifier.subject = MagicMock(side_effect=ServiceError('UNAUTHENTICATED', 'Sign in', 401))
            self.assertEqual(client.get('/v1/admin/enhancements').status_code, 401)
