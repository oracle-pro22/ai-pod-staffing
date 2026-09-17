"""Repository boundary: replace ExcelRepository with a transactional 26ai adapter."""
import json
import os
import shutil
import time
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Callable, Protocol, TypeVar
from uuid import uuid4

from .config import ROOT, config
from .excel_file import EPOCH, ExcelFile
from .models import Database

TABLES = {
    "people": ("People", "person_id full_name initials job_title location allocation_pct active_pods can_lead daily_hours"),
    "skills": ("Skills", "skill_id skill_name category source"),
    "personSkills": ("Person Skills", "person_id skill_id proficiency evidence source"),
    "preferences": ("Preferences", "person_id skill_id interest_level source"),
    "availability": ("Availability Events", "event_id person_id event_type starts_on ends_on title allocated_hours"),
    "requests": ("Staffing Requests", "request_id title work_type owner_name starts_on needed_by estimated_hours contributor_count priority status business_context created_at submission_key latest_run_id project_type_id deliverable_id"),
    "requirements": ("Request Skills", "request_id skill_id min_proficiency mandatory"),
    "runs": ("Workflow Runs", "run_id request_id status stage created_at updated_at lease_until lease_owner revision provider model weights_json proposed_ids_json summary error feedback master_hash"),
    "candidates": ("Fitment Candidates", "run_id person_id rank eligible can_lead skills_score allocation_score future_score interests_score total_score current_allocation peak_allocation per_day_hours evidence_json exclusions rationale recommended_role"),
    "events": ("Workflow Events", "event_id run_id occurred_at component component_type tool status detail"),
    "decisions": ("Approval Decisions", "decision_id run_id request_id action reviewer reason selected_ids_json occurred_at idempotency_key"),
    "assignments": ("Assignments", "assignment_id request_id run_id person_id role_in_pod starts_on ends_on allocated_hours per_day_hours approved_by approved_at"),
    "notifications": ("Notifications", "notification_id run_id recipient message created_at delivery_status"),
    "policies": ("Staffing Policies", "policy_id title guidance version"),
    "settings": ("Agent Settings", "key value description"),
}


def json_string(value) -> str:
    # Match the former JS JSON.stringify for integral Excel numeric cells. This
    # keeps existing run master hashes valid across the backend migration.
    def normalize(item):
        if isinstance(item, float) and item.is_integer():
            return int(item)
        if isinstance(item, list):
            return [normalize(v) for v in item]
        if isinstance(item, dict):
            return {k: normalize(v) for k, v in item.items()}
        return item
    return json.dumps(normalize(value), ensure_ascii=False, separators=(",", ":"), allow_nan=False)


T = TypeVar("T")


class StaffingRepository(Protocol):
    def read(self) -> Database: ...
    def transaction(self, operation: Callable[[Database], T]) -> T: ...


class ExcelRepository:
    def __init__(self, file: Path | str | None = None):
        self.file = Path(file) if file else config().workbook

    @contextmanager
    def lock(self):
        """Exclusive PID lock interoperable with the previous backend.

        A live process's lock is never stolen. Dead-process locks recover after
        ten seconds; a failed transaction never partially publishes a workbook.
        """
        lock_path = Path(str(self.file) + ".lock")
        handle = None
        for _ in range(120):
            try:
                handle = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.write(handle, str(os.getpid()).encode())
                break
            except FileExistsError:
                try:
                    if time.time() - lock_path.stat().st_mtime > 10:
                        pid = int(lock_path.read_text())
                        if pid > 0:
                            try:
                                os.kill(pid, 0)
                            except ProcessLookupError:
                                lock_path.unlink(missing_ok=True)
                except (FileNotFoundError, ValueError, PermissionError):
                    pass
                time.sleep(0.1)
        if handle is None:
            raise ValueError("Workbook is busy. Please retry.")
        try:
            yield
        finally:
            os.close(handle)
            lock_path.unlink(missing_ok=True)

    def initialize(self):
        self.file.parent.mkdir(parents=True, exist_ok=True)
        if not self.file.exists():
            with self.lock():
                if not self.file.exists():
                    shutil.copyfile(ROOT / "data/agentic-staffing.xlsx", self.file)

    def _read(self):
        workbook = ExcelFile(self.file)
        db = {}
        for key, (name, column_text) in TABLES.items():
            columns = column_text.split()
            rows = workbook.read_rows(name)
            if not rows or any(c not in rows[0] for c in columns):
                raise ValueError(f"Missing required columns in {name}.")
            indices = [rows[0].index(c) for c in columns]
            records = []
            for row in rows[1:]:
                if not any(i < len(row) and row[i] != "" for i in indices):
                    continue
                record = {}
                for column, index in zip(columns, indices):
                    value = row[index] if index < len(row) else ""
                    if column in {"starts_on", "ends_on", "needed_by"} and isinstance(value, (int, float)):
                        value = (EPOCH + timedelta(days=value)).isoformat()
                    record[column] = value
                records.append(record)
            db[key] = records
        return workbook, db

    def read(self) -> Database:
        # Atomic rename ensures readers see the previous or complete next file.
        return self._read()[1]

    def transaction(self, operation: Callable[[Database], T]) -> T:
        with self.lock():
            temporary = Path(f"{self.file}.{uuid4()}.tmp.xlsx")
            try:
                workbook, db = self._read()
                before = {key: json_string(rows) for key, rows in db.items()}
                result = operation(db)
                changed = False
                for key, (sheet, columns) in TABLES.items():
                    if before[key] != json_string(db[key]):
                        workbook.replace_rows(sheet, columns.split(), db[key])
                        changed = True
                if changed:
                    workbook.save(temporary)
                    with temporary.open("rb") as handle:
                        os.fsync(handle.fileno())
                    shutil.copyfile(self.file, str(self.file) + ".backup")
                    os.replace(temporary, self.file)
                return result
            finally:
                temporary.unlink(missing_ok=True)
