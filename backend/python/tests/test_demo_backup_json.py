"""Offline regressions for Oracle JSON decoding differences after CTAS.

These tests deliberately retain the legacy raw fingerprint contract. They do
not connect to Oracle, create backup tables, or write business data.
"""

import hashlib
import json
import unittest
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import demo_backup
from app.errors import ServiceError


SOURCE = "PEOPLE"
BACKUP = demo_backup.BACKUP_TABLES[SOURCE]
JSON_COLUMN = "DELIVERABLE_EXPERIENCE_JSON"
COLUMNS = [
    {"column_name": "PERSON_ID", "data_type": "VARCHAR2", "data_length": 30, "nullable": "N"},
    {"column_name": JSON_COLUMN, "data_type": "CLOB", "data_length": 4000, "nullable": "Y"},
    {"column_name": "NOTES", "data_type": "CLOB", "data_length": 4000, "nullable": "Y"},
]


def lob(value):
    return SimpleNamespace(read=lambda: value)


class JsonFingerprintTests(unittest.TestCase):
    def calculate(self, table, records, *, normalize=False, already_json=False, columns=None):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.__iter__.return_value = iter(records)
        cursor.description = [
            SimpleNamespace(name=column["column_name"], is_json=already_json and i == 1, is_oson=False)
            for i, column in enumerate(columns or COLUMNS)
        ]

        def json_columns(_connection, name):
            return {JSON_COLUMN} if name == SOURCE or already_json else set()

        with (
            patch("app.demo_backup._object_type", return_value="TABLE"),
            patch("app.demo_backup._columns", return_value=columns or COLUMNS),
            patch("app.demo_backup._json_fetch_columns", side_effect=json_columns),
        ):
            kwargs = {"json_source": SOURCE} if normalize else {}
            return demo_backup.fingerprint(connection, table, **kwargs)

    def test_nested_json_lob_matches_decoded_source_without_changing_raw_hash(self):
        decoded = [{"id": "DL-001", "rating": Decimal("2.50"), "interested": True, "extra": None}]
        raw = '[ {"extra":null,"interested":true,"rating":2.50,"id":"DL-001"} ]'
        source = self.calculate(SOURCE, [("P-001", decoded, lob("Ordinary text"))])
        backup = self.calculate(BACKUP, [("P-001", lob(raw), lob("Ordinary text"))])
        normalized = self.calculate(BACKUP, [("P-001", lob(raw), lob("Ordinary text"))], normalize=True)
        self.assertNotEqual(source["data_hash"], backup["data_hash"])
        self.assertEqual(source, normalized)
        self.assertEqual(backup, self.calculate(BACKUP, [("P-001", lob(raw), lob("Ordinary text"))]))

    def test_json_scalars_arrays_objects_and_sql_null(self):
        cases = [
            ("null", None),
            ("true", True),
            ("false", False),
            ('"A name"', "A name"),
            ("1e-7", Decimal("0.0000001")),
            ("123456789.123456789", Decimal("123456789.123456789")),
            ("[]", []),
            ("{}", {}),
        ]
        for raw, decoded in cases:
            with self.subTest(raw=raw):
                source = self.calculate(SOURCE, [("P-001", decoded, None)])
                normalized = self.calculate(BACKUP, [("P-001", lob(raw), None)], normalize=True)
                self.assertEqual(source, normalized)
        source = self.calculate(SOURCE, [("P-001", None, None)])
        normalized = self.calculate(BACKUP, [("P-001", None, None)], normalize=True)
        self.assertEqual(source, normalized)

    def test_already_decoded_scalar_is_not_parsed_twice(self):
        for decoded in ("true", "null", "[]", "A name"):
            with self.subTest(decoded=decoded):
                source = self.calculate(SOURCE, [("P-001", decoded, None)])
                normalized = self.calculate(
                    BACKUP, [("P-001", decoded, None)], normalize=True, already_json=True
                )
                self.assertEqual(source, normalized)

    def test_non_json_text_that_looks_like_json_remains_exact(self):
        source = self.calculate(SOURCE, [("P-001", [], lob('[ 1, 2 ]'))])
        normalized = self.calculate(BACKUP, [("P-001", lob("[]"), lob('[ 1, 2 ]'))], normalize=True)
        changed_text = self.calculate(BACKUP, [("P-001", lob("[]"), lob('[1,2]'))], normalize=True)
        self.assertEqual(source, normalized)
        self.assertNotEqual(source["data_hash"], changed_text["data_hash"])

    def test_changed_json_value_and_duplicated_rows_do_not_match(self):
        source = self.calculate(SOURCE, [("P-001", {"rating": Decimal(3)}, None)])
        changed = self.calculate(BACKUP, [("P-001", lob('{"rating":4}'), None)], normalize=True)
        duplicate = self.calculate(
            BACKUP, [("P-001", lob('{"rating":3}'), None)] * 2, normalize=True
        )
        self.assertNotEqual(source["data_hash"], changed["data_hash"])
        self.assertNotEqual(source["data_hash"], duplicate["data_hash"])
        self.assertEqual(duplicate["row_count"], 2)

    def test_default_data_hash_is_the_exact_legacy_raw_algorithm(self):
        raw_json = '[ {"rating": 3} ]'
        result = self.calculate(BACKUP, [("P-001", lob(raw_json), None)])

        def digest(value):
            data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            return hashlib.sha256(data.encode("utf-8")).hexdigest()

        expected = digest([digest(["P-001", raw_json, None])])
        self.assertEqual(result["data_hash"], expected)

    def test_normalization_cannot_target_an_unrelated_or_injected_source(self):
        for source in ("REQUESTS", "PEOPLE; DROP TABLE PEOPLE"):
            with self.subTest(source=source), self.assertRaises(ServiceError):
                demo_backup.fingerprint(MagicMock(), BACKUP, json_source=source)


class CopiedJsonDecoderTests(unittest.TestCase):
    def test_decimal_precision_and_json_primitive_types(self):
        decoded = demo_backup._decode_copied_json(
            lob('{"number":0.123456789123456789,"flag":false,"nothing":null,"name":"true"}')
        )
        self.assertEqual(decoded["number"], Decimal("0.123456789123456789"))
        self.assertIs(decoded["flag"], False)
        self.assertIsNone(decoded["nothing"])
        self.assertEqual(decoded["name"], "true")

    def test_invalid_ambiguous_or_nonfinite_json_fails_without_payload(self):
        for raw in (
            '{"private-name":"DO_NOT_ECHO",',
            '{"duplicate":1,"duplicate":2}',
            '{"nested":{"duplicate":1,"duplicate":2}}',
            "NaN",
            "Infinity",
            "-Infinity",
        ):
            with self.subTest(raw=raw), self.assertRaises(ServiceError) as raised:
                demo_backup._decode_copied_json(lob(raw))
            self.assertEqual(raised.exception.code, "DEMO_BACKUP_CONFLICT")
            self.assertNotIn("DO_NOT_ECHO", str(raised.exception))
            self.assertNotIn(raw, str(raised.exception))


class JsonFetchMetadataTests(unittest.TestCase):
    def test_json_detection_uses_driver_metadata_not_column_name(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.description = [
            SimpleNamespace(name="EXPERIENCE", is_json=True, is_oson=False),
            SimpleNamespace(name="NOT_ACTUALLY_JSON", is_json=False, is_oson=False),
        ]
        self.assertEqual(demo_backup._json_fetch_columns(connection, SOURCE), {"EXPERIENCE"})
        cursor.execute.assert_called_once_with("SELECT * FROM PEOPLE WHERE 1=0")
        cursor.fetchall.assert_not_called()

    def test_binary_oson_requires_explicit_decoder_instead_of_text_json_parser(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.description = [SimpleNamespace(name="BINARY_DOCUMENT", is_json=True, is_oson=True)]
        with self.assertRaises(ServiceError) as raised:
            demo_backup._json_fetch_columns(connection, SOURCE)
        self.assertEqual(raised.exception.code, "DEMO_BACKUP_CONFLICT")
        self.assertIn("OSON", raised.exception.message)


class CopyEquivalenceTests(unittest.TestCase):
    before = {"row_count": 16, "data_hash": "decoded", "column_hash": "columns", "schema_hash": "source"}
    actual = {"row_count": 16, "data_hash": "raw", "column_hash": "columns", "schema_hash": "copy"}

    def test_raw_match_needs_no_json_normalization(self):
        same = {**self.actual, "data_hash": "decoded"}
        with patch("app.demo_backup.fingerprint") as fingerprint:
            self.assertTrue(demo_backup.copy_matches_source(None, SOURCE, self.before, same))
        fingerprint.assert_not_called()

    def test_row_count_and_storage_schema_mismatch_stop_before_normalizing(self):
        for field, changed in (("row_count", 17), ("column_hash", "changed")):
            with self.subTest(field=field), patch("app.demo_backup.fingerprint") as fingerprint:
                self.assertFalse(
                    demo_backup.copy_matches_source(None, SOURCE, self.before, {**self.actual, field: changed})
                )
                fingerprint.assert_not_called()

    def test_normalized_copy_is_compared_to_original_legacy_source(self):
        with patch("app.demo_backup.fingerprint", return_value={**self.before, "schema_hash": "copy"}) as fp:
            self.assertTrue(demo_backup.copy_matches_source(None, SOURCE, self.before, self.actual))
        fp.assert_called_once_with(None, BACKUP, json_source=SOURCE)

    def test_changed_normalized_data_still_fails(self):
        changed = {**self.before, "data_hash": "different-data"}
        with patch("app.demo_backup.fingerprint", return_value=changed):
            self.assertFalse(demo_backup.copy_matches_source(None, SOURCE, self.before, self.actual))


class JsonBackupResumeTests(unittest.TestCase):
    def run_prepare(self, *, status="PLANNED", raw_changed=False, source_changed=False):
        connection = MagicMock()
        before = {"row_count": 16, "data_hash": "decoded", "column_hash": "columns", "schema_hash": "schema"}
        raw = {**before, "data_hash": "raw-json-with-original-whitespace"}
        step = {"status": status, "before": before}
        if status == "COPIED":
            step["backup"] = raw
        state = {
            "migration": {"status": "PREPARING", "anchor": "2026-09-14", "operator": "operator"},
            "backup:PEOPLE": step,
        }

        @contextmanager
        def write():
            yield connection

        def read(_connection, sql, **_binds):
            if "staffing_runtime" in sql:
                return [{"agents_enabled": "N", "notifications_enabled": "N"}]
            if "agent_executions" in sql:
                return [{"n": 0}]
            raise AssertionError("Unexpected mocked query")

        def fingerprint(_connection, table, *, json_source=None):
            if table == SOURCE:
                return {**before, "data_hash": "changed-source"} if source_changed else before
            self.assertEqual(table, BACKUP)
            if json_source:
                self.assertEqual(json_source, SOURCE)
                return before
            return {**raw, "data_hash": "changed-raw-whitespace"} if raw_changed else raw

        def save(_connection, key, value):
            state[key] = value

        with (
            patch("app.demo_backup.BACKUP_TABLES", {SOURCE: BACKUP}),
            patch("app.demo_backup._verify_state_table"),
            patch("app.demo_backup._object_type", return_value="TABLE"),
            patch("app.demo_backup.rows", side_effect=read),
            patch("app.demo_backup.read_state", side_effect=lambda _c, key="migration": state.get(key)),
            patch("app.demo_backup.save_state", side_effect=save) as saved,
            patch("app.demo_backup.fingerprint", side_effect=fingerprint),
            patch("app.demo_backup.fingerprints", return_value={SOURCE: before}),
        ):
            if raw_changed or source_changed:
                with self.assertRaises(ServiceError) as raised:
                    demo_backup.prepare(SimpleNamespace(write=write), date(2026, 9, 14), "operator")
                saved.assert_not_called()
                result = raised.exception
            else:
                result = demo_backup.prepare(SimpleNamespace(write=write), date(2026, 9, 14), "operator")
        connection.cursor.assert_not_called()  # Existing CTAS copy is never recreated.
        return result, state, before, raw

    def test_legacy_planned_step_resumes_and_saves_raw_copy_fingerprint(self):
        result, state, before, raw = self.run_prepare()
        self.assertEqual(result["status"], "PREPARED")
        self.assertEqual(state["backup:PEOPLE"], {"status": "COPIED", "before": before, "backup": raw})
        self.assertNotEqual(raw["data_hash"], before["data_hash"])

    def test_existing_copied_step_uses_original_raw_manifest(self):
        result, state, before, raw = self.run_prepare(status="COPIED")
        self.assertEqual(result["status"], "PREPARED")
        self.assertEqual(state["backup:PEOPLE"], {"status": "COPIED", "before": before, "backup": raw})

    def test_existing_copied_raw_whitespace_change_is_still_rejected(self):
        error, _, _, _ = self.run_prepare(status="COPIED", raw_changed=True)
        self.assertIn("changed", error.message)

    def test_source_drift_is_rejected_before_resume(self):
        error, _, _, _ = self.run_prepare(source_changed=True)
        self.assertIn("Source PEOPLE changed", error.message)


if __name__ == "__main__":
    unittest.main()
