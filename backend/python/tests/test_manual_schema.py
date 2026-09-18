from pathlib import Path
import unittest
from unittest.mock import patch
from app import manual_schema as schema
from app.errors import ServiceError


class ManualSchemaTests(unittest.TestCase):
    def metadata(self, c, sql, **b):
        self.assertTrue(sql.lstrip().startswith('SELECT '))
        if 'FROM user_tab_columns' in sql:
            table = b['tableName']
            expected = {**schema.TABLES, 'POD_PROPOSALS': {'EXECUTION_ID': ('VARCHAR2',64,'Y'), 'ORIGIN_TYPE': ('VARCHAR2',8,'N')},
                        'POD_PROPOSAL_MEMBERS': {'SCORE': ('NUMBER',5,'Y'), 'MANUAL_FLAG': ('CHAR',1,'N')}}[table]
            return [{'column_name': n,'data_type': t,'char_length': s,'data_precision': s,'nullable': v,
                     'data_scale': 2 if n == 'SCORE' else 0, 'data_default': "'AGENT'" if n == 'ORIGIN_TYPE' else "'N'"}
                    for n,(t,s,v) in expected.items()]
        if 'parent_columns' in sql:
            table,kind,columns,parent = schema.KEYS[b['constraintName']]
            return [{'table_name': table, 'constraint_type': kind, 'columns_list': columns, 'parent_table': parent,
                     'parent_columns': columns, 'status': 'ENABLED','validated': 'VALIDATED','r_owner': 'AI_POD_STAFFING','delete_rule': 'NO ACTION'}]
        if 'search_condition_vc' in sql:
            table,expression = schema.CHECKS[b['constraintName']]
            return [{'table_name': table,'constraint_type':'C','status':'ENABLED','validated':'VALIDATED','search_condition_vc':expression}]
        if 'FROM user_triggers' in sql:
            name = b['triggerName']
            return [{'status':'ENABLED','table_name':schema.TRIGGERS[name][0] if name in schema.TRIGGERS else 'EXISTING'}]
        if 'FROM user_source' in sql:
            name = b['triggerName']
            return [{'text': f'TRIGGER {name} {schema.TRIGGERS[name][1]}'}]
        if 'FROM user_errors' in sql: return []
        if 'mvp_p3_ddl_backup' in sql: return [{'object_name':'POD_PROPOSALS'}, {'object_name':'POD_PROPOSAL_MEMBERS'}]
        raise AssertionError(sql)

    def test_expected_structure_and_existing_phase2_verified_without_writes(self):
        with patch.object(schema, 'rows', side_effect=self.metadata), patch.object(schema, 'verify_phase2') as phase2:
            result = schema.verify(None)
        phase2.assert_called_once()
        self.assertTrue(result['verified']); self.assertEqual(result['writes'], 0)
        self.assertEqual(result['manual_limit_pct'], 100)

    def test_wrong_defaults_keys_score_scale_or_disabled_freeze_fail_closed(self):
        for target,field,value in (('FROM user_tab_columns','nullable','N'), ('FROM user_tab_columns','data_scale',3),
                                   ('parent_columns','parent_columns','WRONG_COLUMN'), ('FROM user_triggers','status','DISABLED'),
                                   ('FROM user_source','text','TRIGGER changed BEGIN NULL; END;'),
                                   ('search_condition_vc','search_condition_vc','1=1')):
            def read(c, sql, **b):
                data = self.metadata(c, sql, **b)
                if target in sql:
                    for r in data: r[field] = value
                return data
            with self.subTest(field=field), patch.object(schema,'verify_phase2'), patch.object(schema,'rows',side_effect=read), self.assertRaises(ServiceError):
                schema.verify(None)

    def test_sql_preserves_catalogue_and_history_and_keeps_execution_link_for_agents(self):
        sql = (Path(__file__).resolve().parents[3] / 'sql/oracle/mvp_phase3.sql').read_text().upper()
        self.assertIn("ORIGIN_TYPE='AGENT' AND EXECUTION_ID IS NOT NULL", sql)
        self.assertIn("ORIGIN_TYPE='MANUAL' AND EXECUTION_ID IS NULL", sql)
        self.assertIn('DBMS_METADATA.GET_DDL', sql)
        self.assertIn("EXECUTE IMMEDIATE 'INSERT INTO MVP_P3_DDL_BACKUP", sql)
        self.assertNotRegex(sql, r'SELECT\s+COUNT\(\*\)\s+INTO\s+N\s+FROM\s+MVP_P3_DDL_BACKUP')
        self.assertIn("SCORE IS NULL", sql)
        self.assertIn("AGENTS_ENABLED='N' AND NOTIFICATIONS_ENABLED='N'", sql)
        self.assertIn("STATUS IN ('QUEUED','RUNNING')", sql)
        for forbidden in ('DROP TABLE','TRUNCATE TABLE','DELETE FROM','DISABLE ALL TRIGGERS','CREATE OR REPLACE',
                          'UPDATE PEOPLE','UPDATE DELIVERABLES','UPDATE INTERESTS','UPDATE LOAD_GUARDRAILS'):
            self.assertNotIn(forbidden, sql)
        # Trigger bodies cannot drift separately between migration and verifier.
        for name, (_, body) in schema.TRIGGERS.items():
            self.assertIn(schema.normalized(f'CREATE TRIGGER {name} {body}'), schema.normalized(sql))


if __name__ == '__main__': unittest.main()
