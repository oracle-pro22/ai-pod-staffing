"""Offline migration tests. This does not connect to or compile code in Oracle."""
import importlib.util
import re
import sqlite3
import sys
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("builder", Path(__file__).with_name("build_roles_catalog_migration.py"))
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
SOURCE = Path(sys.argv.pop(1)) if len(sys.argv)>1 and not sys.argv[1].startswith("-") else Path.home()/"Downloads/Project-Deliverable-Skills-Mapping-v260810.csv"
PRIMARY, RECOVERY, MANIFEST = b.build(SOURCE)


def statements(text):
    return re.findall(r"EXECUTE IMMEDIATE q'~(.*?)~';", text, re.S)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.db.execute("PRAGMA foreign_keys=ON")
        for table,cols in b.TABLES.items():
            definitions=[]
            for c in cols.split():
                dtype="INTEGER" if c=="source_row" else "TEXT"
                default=" DEFAULT 'Y'" if c=="active_flag" else " DEFAULT '2026-09-10T10:00:00.000000+00:00'" if c in ("created_at","assigned_at") else ""
                definitions.append(c+" "+dtype+default)
            definitions.append("PRIMARY KEY ("+",".join(b.KEYS[table].split())+")")
            if table=="DELIVERABLES":
                definitions.extend(["UNIQUE(project_type_id,deliverable_name)","FOREIGN KEY(project_type_id) REFERENCES PROJECT_TYPES(project_type_id)"])
            if table=="INTERESTS": definitions.append("UNIQUE(interest_name)")
            if table=="APP_ROLES": definitions.append("UNIQUE(role_name)")
            if table=="DELIVERABLE_SKILLS": definitions.extend(["FOREIGN KEY(deliverable_id) REFERENCES DELIVERABLES(deliverable_id)","FOREIGN KEY(skill_id) REFERENCES INTERESTS(interest_id)"])
            if table in ("APP_USER_ROLES","ROLE_PERMISSIONS"): definitions.append("FOREIGN KEY(role_code) REFERENCES APP_ROLES(role_code)")
            self.db.execute(f"CREATE TABLE {table} ({','.join(definitions)})")
            for r in b.seed_rows(table):
                self.db.execute(f"INSERT INTO {table} ({','.join(r)}) VALUES ({','.join('?' for _ in r)})",list(r.values()))
        for code in ("OPERATIONS_LEAD","REQUEST_LEAD"):
            self.db.execute("INSERT INTO APP_USER_ROLES (identity_subject,role_code,person_id,active_flag,effective_from,assigned_by) VALUES ('demo-captain',?,'P-009','Y','2026-09-01','existing-admin')",(code,))
        self.db.execute("INSERT INTO APP_USER_ROLES (identity_subject,role_code,person_id,active_flag,effective_from,assigned_by) VALUES ('demo-member','POD_MEMBER','P-001','Y','2026-09-01','existing-admin')")
        for table in b.TABLES:
            self.db.execute(f"CREATE TABLE AIPS_BK_{table} AS SELECT * FROM {table}")
        self.db.commit()
        self.before=self.snapshot()

    def tearDown(self): self.db.close()

    def snapshot(self):
        return {t:self.db.execute(f"SELECT {','.join(cols.split())} FROM {t} ORDER BY {','.join(b.KEYS[t].split())}").fetchall() for t,cols in b.TABLES.items()}

    def apply_data(self):
        start=PRIMARY.index("Applying catalogue and profile changes in ONE transaction")
        end=PRIMARY.index("-- Acceptance checks",start)
        self.db.execute("BEGIN")
        for sql in statements(PRIMARY[start:end]): self.db.execute(sql)

    def test_catalogue_and_profiles(self):
        self.apply_data()
        for table,count in [("PROJECT_TYPES",11),("INTERESTS",14),("DELIVERABLES",78),("DELIVERABLE_SKILLS",129),("ROLE_PERMISSIONS",48)]:
            self.assertEqual(self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],count)
        self.assertEqual(self.db.execute("SELECT role_name FROM APP_ROLES WHERE active_flag='Y' ORDER BY role_name").fetchall(),[("Administrator",),("POD Captain",),("POD Lead",),("POD Member",)])
        for r in MANIFEST["rows"]:
            record=self.db.execute("SELECT project_type_id,deliverable_name,skills_raw,active_flag FROM deliverables WHERE deliverable_id=?",(r["id"],)).fetchone()
            self.assertEqual(record,(r["project_id"],r["name"],r["skills"] or None,"Y"))
            actual=self.db.execute("SELECT skill_name FROM deliverable_skills WHERE deliverable_id=? ORDER BY skill_name",(r["id"],)).fetchall()
            self.assertEqual(actual,[(s,) for s in sorted(r["skill_list"])])
        for r in MANIFEST["retired"]:
            self.assertEqual(self.db.execute("SELECT active_flag FROM deliverables WHERE deliverable_id=?",(r["deliverable_id"],)).fetchone(),("N",))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM customer_mapping WHERE source_version=?",(b.VERSION,)).fetchone()[0],85)
        self.assertEqual(self.db.execute("SELECT role_code FROM app_user_roles WHERE identity_subject='demo-captain'").fetchall(),[("POD_CAPTAIN",)])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM role_permissions WHERE role_code<>'POD_CAPTAIN' AND can_approve='Y'").fetchone()[0],0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM role_permissions WHERE role_code='POD_MEMBER' AND (can_create='Y' OR can_update='Y' OR can_approve='Y')").fetchone()[0],0)

    def test_injected_error_rolls_back_all_dml(self):
        self.apply_data()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO deliverable_skills (deliverable_id,skill_id) VALUES ('DEL-NOT-REAL','SK-014')")
        self.db.rollback()
        self.assertEqual(self.snapshot(),self.before)

    def test_recovery_data_restores_original_records(self):
        self.apply_data()
        self.db.commit()
        self.db.execute("BEGIN")
        recovery_ops=statements(RECOVERY)
        merges=[s for s in recovery_ops if s.startswith("MERGE INTO")]
        self.assertEqual(len(merges),8)
        # Execute the generated MERGE's equivalent upsert in SQLite, in the
        # actual recovery order. Oracle syntax itself requires Oracle validation.
        for sql in merges:
            table=re.match(r"MERGE INTO (\w+)",sql).group(1)
            cols=b.TABLES[table].split(); keys=b.KEYS[table].split()
            updates=",".join(f"{c}=excluded.{c}" for c in cols if c not in keys)
            self.db.execute(f"INSERT INTO {table} ({','.join(cols)}) SELECT {','.join(cols)} FROM AIPS_BK_{table} WHERE 1 ON CONFLICT ({','.join(keys)}) DO UPDATE SET {updates}")
        deletes=[s for s in recovery_ops if s.startswith("DELETE FROM")]
        self.assertEqual(len(deletes),8)
        for sql in deletes:
            # Oracle omits AS on a DELETE alias; SQLite requires it.
            self.db.execute(re.sub(r"^(DELETE FROM \w+) t ",r"\1 AS t ",sql))
        self.assertEqual(self.snapshot(),self.before)

    def test_script_safeguards_and_regeneration(self):
        for name,content in [("roles_catalog.sql",PRIMARY),("rollback_roles_catalog.sql",RECOVERY)]:
            self.assertEqual((b.ROOT/"sql/oracle"/name).read_text(encoding="utf-8"),content)
            self.assertIn("WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK",content)
            self.assertIn("DISABLE PARALLEL DML",content)
            self.assertIn("SESSION_USER",content)
            self.assertIn("DBMS_LOB.COMPARE",content)
            self.assertNotIn("INSERT ALL",content)
            self.assertNotIn("DROP TABLE",content)
        self.assertIn("Conflicting Operations Lead / Request Lead mappings",PRIMARY)
        self.assertIn("Executive has active or future assignments",PRIMARY)
        self.assertIn("DATA_RESTORED",RECOVERY)
        self.assertIn("Requests now use the new catalogue revision",RECOVERY)
        self.assertIn("A person now has a newly added skill",RECOVERY)
        self.assertIn("RETURNING CLOB) ORDER BY",PRIMARY)


if __name__=="__main__": unittest.main(verbosity=2)
