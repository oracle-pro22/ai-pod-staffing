"""Owned, resumable backups for the Phase-1 demonstration data migration.

DDL is deliberately confined to ``prepare``. Business-data changes and migration
state transitions belong to the caller's later, single DML transaction. This
module never removes a backup and never edits an immutable business history.
"""

import base64
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal

from app.errors import ServiceError
from app.storage import rows


MUTABLE_TABLES = (
    "PEOPLE",
    "PERSON_INTERESTS",
    "APP_USER_ROLES",
    "AVAILABILITY",
    "REQUESTS",
    "REQUIREMENTS",
    "PERSON_CAPACITY_DAYS",
    "STAFFING_RUNTIME",
    "INTERESTS",
)
HISTORY_TABLES = (
    "AGENT_EXECUTIONS",
    "AGENT_EXECUTION_EVENTS",
    "POD_PROPOSALS",
    "POD_PROPOSAL_MEMBERS",
    "APPROVAL_DECISIONS",
    "POD_ASSIGNMENTS",
    "ASSIGNMENT_DAYS",
    "AUDIT_EVENTS",
    "NOTIFICATION_OUTBOX",
)
TRACKED_TABLES = (
    *MUTABLE_TABLES,
    *HISTORY_TABLES,
    "STAFFING_POLICIES",
    "ELIGIBILITY_RULES",
    "LOAD_GUARDRAILS",
    "SCORING_WEIGHTS",
    "PROJECT_TYPES",
    "DELIVERABLES",
    "DELIVERABLE_SKILLS",
    "ROLE_PERMISSIONS",
    "APP_ROLES",
)
BACKUP_TABLES = {name: "AIPS_D1_BK_" + name for name in MUTABLE_TABLES}
BACKUP_TABLES["PERSON_CAPACITY_DAYS"] = "AIPS_D1_BK_CAPACITY_DAYS"
STATE_TABLE = "AIPS_D1_STATE"
OWNER = {"owner": "ai-pod-staffing/demo-data-phase1", "format_version": 1}
_ALLOWED_TABLES = frozenset((*TRACKED_TABLES, *BACKUP_TABLES.values()))


def _demand(condition, message):
    if not condition:
        raise ServiceError("DEMO_BACKUP_CONFLICT", message, 409)


def _canonical(value):
    if hasattr(value, "read"):
        value = value.read()
    if isinstance(value, (datetime, date)):
        return {"date": value.isoformat()}
    if isinstance(value, (bytes, bytearray)):
        return {"bytes": base64.b64encode(value).decode("ascii")}
    if isinstance(value, Decimal):
        return {"number": format(value.normalize(), "f")}
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return {"number": format(Decimal(str(value)).normalize(), "f")}
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    raise TypeError(f"Unsupported backup value type: {type(value).__name__}")


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _object_type(connection, name):
    found = rows(
        connection,
        "SELECT object_type FROM user_objects WHERE object_name=:objectName AND subobject_name IS NULL",
        objectName=name,
    )
    _demand(len(found) <= 1, f"Unexpected objects share the reserved name {name}.")
    return found[0]["object_type"] if found else None


def _columns(connection, table):
    return rows(
        connection,
        """SELECT column_name,data_type,data_length,data_precision,data_scale,
        char_used,char_length,nullable FROM user_tab_columns WHERE table_name=:tableName ORDER BY column_id""",
        tableName=table,
    )


def _json_fetch_columns(connection, table):
    """Use Oracle result metadata, never column naming or JSON-looking content."""
    _demand(table in _ALLOWED_TABLES, "Table is outside the fixed backup allowlist.")
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT * FROM {table} WHERE 1=0")
        _demand(
            not any(getattr(column, "is_oson", False) for column in cursor.description),
            "Binary OSON copy verification requires a separate reviewed decoder.",
        )
        return {column.name for column in cursor.description if column.is_json}


def _decode_copied_json(value):
    """Restore JSON types lost when CTAS omits an IS JSON check constraint.

    The stored raw-copy fingerprint remains the drift guard. This decoding is
    used only to compare the copy with an unchanged, typed source snapshot.
    """
    if hasattr(value, "read"):
        value = value.read()
    if value is None:
        return None

    def unique_object(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = item
        return result

    def reject_constant(_value):
        raise ValueError("Non-finite JSON number")

    try:
        if not isinstance(value, (str, bytes, bytearray)):
            raise ValueError("Expected copied JSON text")
        return json.loads(
            value, parse_float=Decimal, object_pairs_hook=unique_object, parse_constant=reject_constant
        )
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise ServiceError(
            "DEMO_BACKUP_CONFLICT",
            "A copied JSON value is invalid or ambiguous; keep backups and inspect the source column.",
            409,
        ) from error


def fingerprint(connection, table, *, json_source=None):
    """Hash every row, independent of order; default hashes remain unchanged.

    json_source is allowed only for the corresponding fixed backup table. It
    supplies an additional copy-equivalence hash, never a replacement for the
    raw source/backup hashes saved in existing migration manifests.
    """
    _demand(table in _ALLOWED_TABLES, "Table is outside the fixed backup allowlist.")
    if json_source is not None:
        _demand(
            BACKUP_TABLES.get(json_source) == table,
            "JSON comparison requires the corresponding allowlisted source and backup.",
        )
    _demand(
        _object_type(connection, table) == "TABLE",
        f"Required table {table} is missing or has an unexpected object type.",
    )
    columns = _columns(connection, table)
    # CTAS does not copy every constraint, so compare storage types separately
    # from source-schema nullability; both signatures are retained in the manifest.
    storage_columns = [
        {key: value for key, value in column.items() if key != "nullable"} for column in columns
    ]
    json_columns = (
        _json_fetch_columns(connection, json_source) - _json_fetch_columns(connection, table)
        if json_source is not None
        else set()
    )
    json_positions = {index for index, column in enumerate(columns) if column["column_name"] in json_columns}
    row_hashes = []
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT * FROM {table}")
        for record in cursor:
            if json_positions:
                record = tuple(
                    _decode_copied_json(value) if index in json_positions else value
                    for index, value in enumerate(record)
                )
            row_hashes.append(_hash(_canonical(record)))
    row_hashes.sort()
    return {
        "row_count": len(row_hashes),
        "data_hash": _hash(row_hashes),
        "column_hash": _hash(_canonical(storage_columns)),
        "schema_hash": _hash(_canonical(columns)),
    }


def copy_matches_source(connection, source, before, actual):
    """Keep exact schema/row checks while accommodating Oracle JSON fetch types."""
    _demand(source in BACKUP_TABLES, "Source is outside the fixed backup allowlist.")
    if any(actual[key] != before[key] for key in ("row_count", "column_hash")):
        return False
    if actual["data_hash"] == before["data_hash"]:
        return True
    comparable = fingerprint(connection, BACKUP_TABLES[source], json_source=source)
    return all(comparable[key] == before[key] for key in ("row_count", "data_hash", "column_hash"))


def fingerprints(connection, tables=MUTABLE_TABLES):
    return {table: fingerprint(connection, table) for table in tables}


def read_state(connection, key="migration"):
    found = rows(connection, f"SELECT value_json FROM {STATE_TABLE} WHERE state_key=:stateKey", stateKey=key)
    if not found:
        return None
    value = found[0]["value_json"]
    if hasattr(value, "read"):
        value = value.read()
    return value if isinstance(value, dict) else json.loads(value)


def save_state(connection, key, value):
    """No commit: caller can atomically save APPLIED/RECOVERED with its data changes."""
    _demand(isinstance(key, str) and 0 < len(key) <= 80, "Invalid migration state key.")
    with connection.cursor() as cursor:
        # Explicit CLOB binding avoids Oracle's SQL VARCHAR2 size limit.
        import oracledb

        cursor.setinputsizes(stateValue=oracledb.DB_TYPE_CLOB)
        cursor.execute(
            f"""MERGE INTO {STATE_TABLE} target
            USING (SELECT :stateKey state_key, :stateValue value_json FROM dual) source
            ON (target.state_key=source.state_key)
            WHEN MATCHED THEN UPDATE SET target.value_json=source.value_json
            WHEN NOT MATCHED THEN INSERT(state_key,value_json) VALUES(source.state_key,source.value_json)""",
            stateKey=key,
            stateValue=_json(value),
        )


def _verify_state_table(connection):
    _demand(
        _object_type(connection, STATE_TABLE) == "TABLE", "The migration state name is not an owned table."
    )
    columns = _columns(connection, STATE_TABLE)
    _demand(
        len(columns) == 2
        and columns[0]["column_name"] == "STATE_KEY"
        and columns[0]["data_type"] == "VARCHAR2"
        and columns[0]["data_length"] == 80
        and columns[0]["nullable"] == "N"
        and columns[1]["column_name"] == "VALUE_JSON"
        and columns[1]["data_type"] == "CLOB"
        and columns[1]["nullable"] == "N",
        "Migration state table structure is not recognized.",
    )
    constraints = rows(
        connection,
        """SELECT constraint_name,constraint_type,status,validated
        FROM user_constraints WHERE table_name=:tableName AND constraint_name IN ('AIPS_D1_STATE_PK','AIPS_D1_STATE_JSON')""",
        tableName=STATE_TABLE,
    )
    _demand(
        {
            (item["constraint_name"], item["constraint_type"], item["status"], item["validated"])
            for item in constraints
        }
        == {
            ("AIPS_D1_STATE_PK", "P", "ENABLED", "VALIDATED"),
            ("AIPS_D1_STATE_JSON", "C", "ENABLED", "VALIDATED"),
        },
        "Migration state constraints changed.",
    )
    _demand(
        read_state(connection, "owner") == OWNER,
        "Unknown migration state ownership; nothing will be overwritten.",
    )


def verify_backups(connection):
    """Verify all owned immutable copies against their committed fingerprints."""
    _verify_state_table(connection)
    result = {}
    for table, backup in BACKUP_TABLES.items():
        step = read_state(connection, "backup:" + table)
        _demand(step and step.get("status") == "COPIED", f"Backup step {table} is incomplete.")
        actual = fingerprint(connection, backup)
        _demand(actual == step["backup"], f"Backup {backup} changed; recovery must stop.")
        result[table] = step["before"]
    return result


def owned_metadata(connection):
    """Read an existing manifest only after validating its schema and ownership."""
    _verify_state_table(connection)
    state = read_state(connection)
    if state and state.get("status") in {"APPLIED", "RECOVERED"}:
        verify_backups(connection)
    return state


def prepare(database, anchor, operator, *, dataset_signature=None):
    """Prepare copies once; resume known interrupted copies but never overwrite one.

    All services must be stopped first. The caller must also disable both runtime
    switches; this helper does not silently change operational controls.
    """
    anchor_value = anchor.isoformat() if isinstance(anchor, date) else str(anchor)
    _demand(
        bool(operator and operator.strip()) and len(operator) <= 128,
        "A nonblank demonstration operator is required.",
    )
    _demand(date.fromisoformat(anchor_value).weekday() == 0, "The data anchor must be a Monday.")
    with database.write() as connection:
        runtime = rows(
            connection, "SELECT agents_enabled,notifications_enabled FROM staffing_runtime WHERE runtime_id=1"
        )
        _demand(
            len(runtime) == 1 and runtime[0] == {"agents_enabled": "N", "notifications_enabled": "N"},
            "Stop application/worker services and disable agent and email switches before preparing data.",
        )
        jobs = rows(
            connection, "SELECT COUNT(*) n FROM agent_executions WHERE status IN ('QUEUED','RUNNING')"
        )[0]["n"]
        _demand(
            jobs == 0,
            "Queued or running executions exist; finish or explicitly cancel them before preparing data.",
        )
        state_type = _object_type(connection, STATE_TABLE)
        if state_type is None:
            _demand(
                not any(_object_type(connection, name) for name in BACKUP_TABLES.values()),
                "Unowned reserved backup tables exist. Nothing will be overwritten.",
            )
            with connection.cursor() as cursor:
                cursor.execute(f"""CREATE TABLE {STATE_TABLE} (
                    state_key VARCHAR2(80 BYTE) NOT NULL, value_json CLOB NOT NULL,
                    CONSTRAINT AIPS_D1_STATE_PK PRIMARY KEY(state_key),
                    CONSTRAINT AIPS_D1_STATE_JSON CHECK(value_json IS JSON STRICT WITH UNIQUE KEYS))""")
            save_state(connection, "owner", OWNER)
            connection.commit()
        _verify_state_table(connection)
        metadata = read_state(connection)
        if metadata:
            _demand(
                metadata.get("anchor") == anchor_value and metadata.get("operator") == operator,
                "This backup belongs to another anchor/operator. Reuse its original parameters.",
            )
            if dataset_signature is not None:
                _demand(
                    metadata.get("dataset_signature") == dataset_signature,
                    "The prepared dataset changed. Keep backups and review before applying another version.",
                )
            _demand(
                metadata.get("status") in {"PREPARING", "PREPARED", "APPLIED", "RECOVERED"},
                "Unrecognized migration status.",
            )
            if metadata["status"] in {"APPLIED", "RECOVERED"}:
                verify_backups(connection)
                return metadata
        else:
            metadata = {**OWNER, "status": "PREPARING", "anchor": anchor_value, "operator": operator}
            if dataset_signature is not None:
                metadata["dataset_signature"] = dataset_signature
            save_state(connection, "migration", metadata)
            connection.commit()
        for table, backup in BACKUP_TABLES.items():
            step = read_state(connection, "backup:" + table)
            if step is None:
                _demand(_object_type(connection, backup) is None, f"Unowned reserved backup {backup} exists.")
                step = {"status": "PLANNED", "before": fingerprint(connection, table)}
                save_state(connection, "backup:" + table, step)
                connection.commit()
            _demand(step.get("status") in {"PLANNED", "COPIED"}, f"Invalid backup state for {table}.")
            _demand(
                fingerprint(connection, table) == step["before"],
                f"Source {table} changed after backup preparation began. Stop services and inspect; no backup was overwritten.",
            )
            backup_type = _object_type(connection, backup)
            if backup_type is None:
                _demand(step["status"] == "PLANNED", f"Verified backup {backup} is missing.")
                with connection.cursor() as cursor:
                    cursor.execute(f"CREATE TABLE {backup} AS SELECT * FROM {table}")
            actual = fingerprint(connection, backup)
            _demand(
                copy_matches_source(connection, table, step["before"], actual),
                f"Backup {backup} does not match its original source fingerprint.",
            )
            if step["status"] == "COPIED":
                _demand(actual == step["backup"], f"Verified backup {backup} changed.")
            else:
                save_state(connection, "backup:" + table, {**step, "status": "COPIED", "backup": actual})
                connection.commit()
        before = verify_backups(connection)
        _demand(
            fingerprints(connection) == before,
            "Business inputs changed while preparing backups. Stop services and inspect.",
        )
        metadata = {**metadata, "status": "PREPARED", "before": before}
        save_state(connection, "migration", metadata)
        return metadata
