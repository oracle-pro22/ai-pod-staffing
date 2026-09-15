"""Exercise the actual staffing gate with synthetic inputs and mocked SELECTs."""

import unittest
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from app.demo_dataset import build_demo_dataset
from app.demo_simulation import classify_event, distribute_external, resolve_project, simulate
from app.errors import ServiceError


PROJECT_SKILLS = {
    ("New Service Launch", "Sales Guide (deck)"): ("GTM SME",),
    ("Demo Package", "Demo video"): (
        "Comms Review",
        "Script writer (GTM SME)",
        "narration audio",
        "video creation",
        "visual asset",
    ),
    ("Enablement", "Create Training Deck"): ("GTM",),
    ("Portal & Content Operations", "Portal Updates"): ("GTM SME",),
    ("Customer Story", "Story Creation"): ("GTM SME",),
}


def catalogs(dataset):
    names = sorted({skill.name for person in dataset.people for skill in person.skills})
    skills = {
        name: {
            "interest_id": f"SK-{i:03}",
            "interest_name": name,
            "assessment_type": "SELF_RATED",
            "derived_role_code": None,
        }
        for i, name in enumerate(names, 1)
    }
    references = sorted(
        {
            (item.project_type, item.deliverable_name)
            for person in dataset.people
            for item in person.deliverables
        }
    )
    catalogue = {reference: {"deliverable_id": f"DEL-{i:03}"} for i, reference in enumerate(references, 1)}
    mapped = {
        catalogue[reference]["deliverable_id"]: [{"skill_id": skills[name]["interest_id"]} for name in names]
        for reference, names in PROJECT_SKILLS.items()
    }
    return skills, catalogue, mapped


class DemoSimulationTests(unittest.TestCase):
    def setUp(self):
        self.dataset = build_demo_dataset(date(2026, 9, 13))
        self.travel = {
            "person_id": "P-900104",
            "availability_id": 41,
            "event_type": "Travel",
            "capacity_kind": "NON_AVAILABILITY",
            "starts_on": date(2026, 9, 18),
            "ends_on": date(2026, 9, 18),
            "allocated_hours": Decimal(8),
            "title": "Customer workshop",
        }

    def run_simulation(self, dataset=None, events=None, mappings=None):
        dataset = dataset or self.dataset
        skills, catalogue, mapped = catalogs(dataset)
        if mappings:
            mapped.update(mappings)
        calls = []

        def select(_connection, sql, **binds):
            calls.append(sql)
            self.assertTrue(sql.strip().upper().startswith("SELECT "))
            if "FROM availability" in sql:
                return events if events is not None else [dict(self.travel)]
            if "FROM deliverable_skills" in sql:
                return mapped[binds["deliverableId"]]
            self.fail("Unexpected SQL during simulation")

        with patch("app.demo_simulation.rows", side_effect=select):
            result = simulate(object(), dataset, skills, catalogue)
        self.assertEqual(len(calls), 6)
        return result

    def test_current_data_passes_actual_gate_without_writes(self):
        result = self.run_simulation()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["writes"], 0)
        self.assertEqual(result["assignments"], 16)
        self.assertEqual(result["assignment_days"], 222)
        self.assertEqual(result["planned_hours"], "366")
        self.assertEqual(result["weeks_validated"], 9)
        self.assertEqual(len(result["first_week_allocation"]), 16)
        allocation = {item["person_id"]: item for item in result["first_week_allocation"]}
        self.assertEqual(allocation["P-006"]["allocation_pct"], "60.00")
        self.assertEqual(allocation["P-900102"]["allocation_pct"], "60.00")
        self.assertEqual(allocation["P-006"]["active_pods_in_week"], 2)

    def test_future_anchor_shortens_new_story_before_retained_travel(self):
        result = self.run_simulation(build_demo_dataset(date(2026, 9, 14)))
        story = next(item for item in result["projects"] if item["request_id"] == "REQ-910005")
        self.assertEqual(story["ends_on"], "2026-09-17")
        self.assertEqual(story["original_ends_on"], "2026-09-24")
        self.assertTrue(story["date_adjusted"])
        self.assertEqual(story["person_hours"], "54")
        ava = next(item for item in result["first_week_allocation"] if item["person_id"] == "P-900104")
        self.assertEqual(ava["available_hours"], "32")
        self.assertEqual(ava["allocation_pct"], "81.25")

    def test_resolver_does_not_mutate_the_original_or_external_commitments(self):
        story = self.dataset.projects[-1]
        event = {
            **self.travel,
            "starts_on": story.starts_on + timedelta(days=4),
            "ends_on": story.starts_on + timedelta(days=4),
        }
        resolved = resolve_project(story, [event])
        self.assertEqual(story.ends_on, date(2026, 9, 17))
        self.assertEqual(resolved.ends_on, date(2026, 9, 10))
        self.assertEqual(resolved.total_hours, story.total_hours)
        self.assertEqual(resolve_project(story, [{**event, "capacity_kind": "EXTERNAL_WORK"}]), story)

    def test_absence_at_start_requires_explicit_schedule_review(self):
        story = self.dataset.projects[-1]
        event = {**self.travel, "starts_on": story.starts_on, "ends_on": story.starts_on}
        with self.assertRaises(ServiceError) as error:
            resolve_project(story, [event])
        self.assertEqual(error.exception.code, "DEMO_BASELINE_SCHEDULE")

    def test_invalid_catalogue_coverage_stops_simulation(self):
        skills, catalogue, _mapped = catalogs(self.dataset)
        guide = catalogue["New Service Launch", "Sales Guide (deck)"]["deliverable_id"]
        with self.assertRaises(ServiceError) as error:
            self.run_simulation(mappings={guide: [{"skill_id": skills["video creation"]["interest_id"]}]})
        self.assertIn("CAPABILITY_GAP", error.exception.message)

    def test_sequential_project_capacity_is_checked(self):
        portal = self.dataset.projects[3]
        portal = replace(
            portal,
            members=tuple(
                replace(member, hours=Decimal(90)) if member.person_id == "P-006" else member
                for member in portal.members
            ),
        )
        dataset = replace(
            self.dataset, projects=self.dataset.projects[:3] + (portal,) + self.dataset.projects[4:]
        )
        with self.assertRaises(ServiceError) as error:
            self.run_simulation(dataset)
        self.assertIn("CAPACITY_EXCEEDED:P-006", error.exception.message)

    def test_later_week_retained_overload_is_not_hidden(self):
        event = {
            **self.travel,
            "person_id": "P-009",
            "capacity_kind": "EXTERNAL_WORK",
            "event_type": "Commitment",
            "starts_on": self.dataset.anchor + timedelta(days=49),
            "ends_on": self.dataset.anchor + timedelta(days=49),
            "allocated_hours": Decimal(9),
        }
        with self.assertRaises(ServiceError):
            self.run_simulation(events=[event])

    def test_unknown_event_classification_is_in_memory_only(self):
        event = {**self.travel, "capacity_kind": "UNKNOWN"}
        self.assertEqual(classify_event(event)["capacity_kind"], "NON_AVAILABILITY")
        self.assertEqual(event["capacity_kind"], "UNKNOWN")
        with self.assertRaises(ServiceError) as error:
            classify_event({**event, "event_type": "Unreviewed"})
        self.assertEqual(error.exception.code, "EVENT_CLASSIFICATION")

    def test_external_work_uses_available_headroom_and_exact_total(self):
        days = {
            date(2026, 9, 14): {"available": Decimal(8), "external": Decimal(7)},
            date(2026, 9, 15): {"available": Decimal(8), "external": Decimal(0)},
            date(2026, 9, 16): {"available": Decimal(0), "external": Decimal(0)},
        }
        assigned = distribute_external(days, Decimal("8.01"))
        self.assertEqual(sum(assigned.values()), Decimal("8.01"))
        self.assertEqual(assigned[date(2026, 9, 14)], Decimal(1))
        self.assertNotIn(date(2026, 9, 16), assigned)
        with self.assertRaises(ServiceError):
            distribute_external(days, Decimal(10))


if __name__ == "__main__":
    unittest.main()
