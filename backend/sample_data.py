"""Reproducible synthetic staffing data. No model calls or production writes.

The generator returns append-only records for the existing workbook schema.
Synthetic identities use SYN-* IDs and are visibly labelled in their names.
Proficiency, expressed preference and dated availability are separate records.
"""
import argparse
import json
import random
from datetime import date, timedelta
from pathlib import Path

SOURCE = "Synthetic staffing scenario v2; fictional, not an employee assessment"
AS_OF = date(2026, 9, 11)
FAMILIES = [
    ("GTM Program Manager", ["SK-001", "SK-002", "SK-006", "SK-011"], ["SK-012", "SK-013", "MOCK-5"]),
    ("Communications Strategist", ["SK-002", "SK-003", "SK-004", "SK-013", "MOCK-1"], ["SK-007", "MOCK-4"]),
    ("Portal and Reporting Consultant", ["SK-002", "SK-005", "SK-011", "SK-012", "SK-013"], ["SK-006", "MOCK-5"]),
    ("Enablement Consultant", ["SK-002", "SK-006", "SK-011", "SK-012", "MOCK-5"], ["SK-003", "SK-004"]),
    ("Content Writer", ["SK-007", "SK-002", "SK-003", "MOCK-4", "MOCK-3"], ["MOCK-1", "SK-004"]),
    ("Video Producer", ["SK-008", "SK-009", "SK-010", "MOCK-2", "MOCK-3"], ["SK-007", "SK-002"]),
    ("Motion and Visual Designer", ["SK-009", "SK-010", "MOCK-3", "MOCK-2"], ["SK-008", "SK-007"]),
    ("Technical Content Consultant", ["SK-002", "SK-011", "SK-012", "MOCK-4", "MOCK-5"], ["SK-013", "SK-003"]),
]


def working_start(day):
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def generate_sample(as_of=AS_OF):
    rng = random.Random(260911)
    data = {k: [] for k in ("people", "personSkills", "preferences", "availability")}
    first_names = ["Avery", "Cameron", "Morgan", "Taylor", "Riley", "Casey", "Jordan", "Quinn"]
    surnames = ["Brooks", "Hayes", "Morgan", "Bennett", "Sullivan", "Reed", "Foster", "Ellis"]
    locations = ["Austin", "Seattle", "Denver", "Bengaluru", "London", "Madrid", "Chicago", "Atlanta"]
    all_skills = sorted({s for _, primary, secondary in FAMILIES for s in primary + secondary})
    for family, (title, primary, secondary) in enumerate(FAMILIES):
        for member in range(8):
            number = family * 8 + member + 1
            person_id = f"SYN-{number:03d}"
            lead = member in {0, 2, 4, 6}
            allocation = [20, 30, 40, 50, 60, 65, 72, 80][member]
            daily = 6 if member == 4 else 8
            name = f"{first_names[member]} {surnames[family]}"
            data["people"].append(dict(person_id=person_id, full_name=name + " (Synthetic)", initials=first_names[member][0] + surnames[family][0],
                                       job_title=("Senior " if lead else "") + title, location=locations[(family + member) % 8],
                                       allocation_pct=allocation, active_pods=max(1, allocation // 25), can_lead=lead, daily_hours=daily))
            recorded = []
            for skill in primary:
                proficiency = rng.choices([3, 4, 5], weights=[2, 5, 3])[0]
                recorded.append(skill)
                data["personSkills"].append(dict(person_id=person_id, skill_id=skill, proficiency=proficiency,
                                                evidence=f"Synthetic {title.lower()} portfolio: {3 + number % 7} comparable assets; mock peer-review proficiency {proficiency}/5.", source=SOURCE))
            for skill in rng.sample(secondary, k=min(2, len(secondary))):
                recorded.append(skill)
                data["personSkills"].append(dict(person_id=person_id, skill_id=skill, proficiency=rng.choice([2, 3, 4]),
                                                evidence="Synthetic adjacent-capability practice; limited or working proficiency.", source=SOURCE))
            # Learning interests can exist without proficiency, and proficiency
            # can exist without expressed interest. Never derive one from the other.
            learning = rng.sample([s for s in all_skills if s not in recorded], 2)
            for skill in recorded + learning:
                if skill in recorded and rng.random() < 0.12:
                    continue
                data["preferences"].append(dict(person_id=person_id, skill_id=skill, interest_level=rng.randint(1, 5),
                                                source="Synthetic expressed preference; sampled independently of proficiency"))
            for quarter in range(4):
                start = working_start(as_of + timedelta(days=quarter * 90 + 7 + (number * 11) % 55))
                end = start + timedelta(days=11)
                data["availability"].append(dict(event_id=f"SYN-AV-{number:03d}-C{quarter}", person_id=person_id, event_type="Commitment",
                                                 starts_on=start.isoformat(), ends_on=end.isoformat(),
                                                 title="Synthetic project commitment (additional to baseline BAU)", allocated_hours=rng.choice([8, 12, 16, 20])))
            for half in range(2):
                start = working_start(as_of + timedelta(days=half * 180 + 14 + (number * 17) % 110))
                end = start + timedelta(days=rng.choice([1, 2, 4]))
                data["availability"].append(dict(event_id=f"SYN-AV-{number:03d}-L{half}", person_id=person_id, event_type="Leave",
                                                 starts_on=start.isoformat(), ends_on=end.isoformat(), title="Synthetic planned leave", allocated_hours=0))
            if number % 2 == 0:
                start = working_start(as_of + timedelta(days=30 + (number * 13) % 220))
                data["availability"].append(dict(event_id=f"SYN-AV-{number:03d}-T", person_id=person_id, event_type="Travel",
                                                 starts_on=start.isoformat(), ends_on=(start + timedelta(days=1)).isoformat(), title="Synthetic customer workshop travel", allocated_hours=0))
    return data


def append_sample(db, additions=None):
    """Pure in-memory merge used for audits/tests; existing IDs are never replaced."""
    additions = additions or generate_sample()
    keys = {"people": ("person_id",), "personSkills": ("person_id", "skill_id"), "preferences": ("person_id", "skill_id"), "availability": ("event_id",)}
    for table, columns in keys.items():
        existing = {tuple(r[k] for k in columns) for r in db[table]}
        for row in additions[table]:
            key = tuple(row[k] for k in columns)
            if key not in existing:
                db[table].append(dict(row))
                existing.add(key)
    return db


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate synthetic staffing records as JSON; does not modify Excel.")
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args()
    payload = generate_sample()
    if args.output_json:
        args.output_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print({k: len(v) for k, v in payload.items()})
    else:
        print(json.dumps(payload, indent=2))
