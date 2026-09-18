"""Additional synthetic employees only. Existing profiles and catalogue are never reseeded."""
from dataclasses import replace
from decimal import Decimal
import re
import unicodedata

from app.demo_dataset import demonstration_people

PERSON_RENAMES = {f"P-90010{i}": f"P-{12+i:03}" for i in range(1, 6)}
# Two Captains, three Leads and nine Members. Keep the existing one Administrator.
ADDITIONS = (
    ("Devon Brooks", "POD_CAPTAIN", "P-009", 16),
    ("Sofia Martinez", "POD_CAPTAIN", "P-010", 20),
    ("Nina Shah", "POD_LEAD", "P-004", 12),
    ("Owen Carter", "POD_LEAD", "P-006", 16),
    ("Lena Park", "POD_LEAD", "P-900102", 8),
    ("Lucas Bennett", "POD_MEMBER", "P-001", 8),
    ("Zoe Kim", "POD_MEMBER", "P-002", 20),
    ("Ethan Price", "POD_MEMBER", "P-003", 12),
    ("Isabel Torres", "POD_MEMBER", "P-005", 24),
    ("Arjun Mehta", "POD_MEMBER", "P-007", 16),
    ("Chloe Davis", "POD_MEMBER", "P-008", 8),
    ("Daniel Ross", "POD_MEMBER", "P-011", 20),
    ("Leila Hassan", "POD_MEMBER", "P-900104", 12),
    ("Marcus Chen", "POD_MEMBER", "P-900105", 28),
)


def placeholder_email(name):
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    parts = re.findall(r"[a-z0-9]+", text)
    if not parts:
        raise ValueError("Cannot derive placeholder email")
    return ".".join(parts) + "@oracle.com"


def additional_people():
    source = {p.person_id: p for p in demonstration_people()}
    return tuple(replace(source[template], person_id=f"P-{18+i:03}", full_name=name,
                         email=placeholder_email(name), role_code=role,
                         external_weekly_hours=Decimal(hours))
                 for i, (name, role, template, hours) in enumerate(ADDITIONS))
