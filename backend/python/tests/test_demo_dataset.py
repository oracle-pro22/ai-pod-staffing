"""Pure fixture checks: no Oracle, OCI, network or writes."""

import unittest
from collections import Counter
from dataclasses import FrozenInstanceError
from datetime import date, timedelta
from decimal import Decimal

from app.demo_dataset import BATCH_ID, CAPACITY_WEEKS, build_demo_dataset


class DemoDatasetTests(unittest.TestCase):
    def setUp(self):
        self.dataset = build_demo_dataset(date(2026, 9, 13))

    def test_repeatable_rolling_nine_week_window(self):
        self.assertEqual(self.dataset, build_demo_dataset(date(2026, 9, 13)))
        self.assertEqual(self.dataset.anchor, date(2026, 9, 7))
        self.assertEqual(self.dataset.capacity_end, date(2026, 11, 8))
        self.assertEqual((self.dataset.capacity_end - self.dataset.anchor).days + 1, CAPACITY_WEEKS * 7)
        shifted = build_demo_dataset(date(2026, 9, 14))
        self.assertEqual(shifted.anchor, self.dataset.anchor + timedelta(days=7))

    def test_exact_role_distribution_with_standalone_admin(self):
        counts = Counter(person.role_code for person in self.dataset.people)
        self.assertEqual(
            counts, {"POD_CAPTAIN": 2, "POD_LEAD": 3, "POD_MEMBER": 11, "SYSTEM_ADMINISTRATOR": 1}
        )
        names = {person.person_id: person.full_name for person in self.dataset.people}
        self.assertEqual(names["P-009"], "Indranie Balkaran")
        self.assertEqual(names["P-010"], "Brenna Cooper")
        self.assertEqual(names["P-900101"], "Amelia Hart")
        self.assertEqual(names["P-012"], "Administrator")
        self.assertEqual(len(names), 17)

    def test_every_employee_has_realistic_evidence_without_self_rating_project_manager(self):
        for person in self.dataset.people:
            self.assertTrue(person.job_title and person.location and person.initials)
            self.assertTrue(person.email.endswith("@example.invalid"))
            self.assertIn(person.weekly_hours, {Decimal(32), Decimal(40)})
            self.assertGreaterEqual(person.external_weekly_hours, 0)
            self.assertLess(person.external_weekly_hours, person.weekly_hours)
            if person.role_code == "SYSTEM_ADMINISTRATOR":
                self.assertFalse(person.staffing_eligible)
                self.assertEqual(person.skills, ())
                continue
            self.assertTrue(3 <= len(person.skills) <= 5)
            self.assertTrue(2 <= len(person.deliverables) <= 4)
            self.assertEqual(len(person.skills), len({skill.name for skill in person.skills}))
            self.assertEqual(
                len(person.deliverables),
                len({(item.project_type, item.deliverable_name) for item in person.deliverables}),
            )
            for skill in person.skills:
                self.assertNotIn("Project Manager", skill.name)
                self.assertTrue(1 <= skill.strength <= 5)
                self.assertGreater(len(skill.evidence), 30)
            for item in person.deliverables:
                self.assertIn(item.experience_level, {"LEARNING", "SUPPORTED", "INDEPENDENT", "MENTOR"})
                self.assertIn(item.contribution_scope, {"CONTRIBUTOR", "END_TO_END"})
                self.assertGreater(len(item.experience), 30)

    def test_projects_cover_every_eligible_person_and_no_captains_or_admin(self):
        by_id = {person.person_id: person for person in self.dataset.people}
        expected = {person.person_id for person in self.dataset.people if person.staffing_eligible}
        actual = {member.person_id for project in self.dataset.projects for member in project.members}
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), 14)
        self.assertEqual(len(self.dataset.projects), 5)
        self.assertEqual(
            sum((project.total_hours for project in self.dataset.projects), Decimal(0)), Decimal(366)
        )
        for project in self.dataset.projects:
            self.assertEqual(by_id[project.captain_id].role_code, "POD_CAPTAIN")
            self.assertIn(project.source_person_id, by_id)
            self.assertEqual(len(project.members), len({member.person_id for member in project.members}))
            self.assertEqual(sum(member.role == "POD_LEAD" for member in project.members), 1)
            self.assertLessEqual(project.starts_on, date(2026, 9, 13))
            self.assertGreaterEqual(project.ends_on, date(2026, 9, 13))
            for member in project.members:
                person = by_id[member.person_id]
                self.assertEqual(person.role_code, member.role)
                self.assertGreaterEqual(member.hours, Decimal(2))
                self.assertGreater(len(member.responsibilities), 30)
                self.assertIn(
                    (project.project_type, project.deliverable_name),
                    {(item.project_type, item.deliverable_name) for item in person.deliverables},
                )

    def test_baseline_daily_load_does_not_overbook(self):
        by_id = {person.person_id: person for person in self.dataset.people}
        daily = Counter()
        for project in self.dataset.projects:
            dates = [
                project.starts_on + timedelta(days=offset)
                for offset in range((project.ends_on - project.starts_on).days + 1)
                if (project.starts_on + timedelta(days=offset)).weekday() < 5
            ]
            for member in project.members:
                for day in dates:
                    daily[member.person_id, day] += member.hours / len(dates)
        for (person_id, _day), assigned in daily.items():
            person = by_id[person_id]
            external = person.external_weekly_hours / 5
            self.assertLessEqual(assigned + external, person.weekly_hours / 5)

    def test_leave_does_not_overlap_project_assignments(self):
        for event in self.dataset.availability:
            self.assertGreater(event.hours, 0)
            self.assertGreaterEqual(event.starts_on, self.dataset.anchor)
            self.assertLessEqual(event.ends_on, self.dataset.capacity_end)
            self.assertEqual(event.capacity_kind, "NON_AVAILABILITY")
            for project in self.dataset.projects:
                if event.person_id in {member.person_id for member in project.members}:
                    self.assertTrue(event.starts_on > project.ends_on or event.ends_on < project.starts_on)
        ava_project = next(
            project
            for project in self.dataset.projects
            if any(member.person_id == "P-900104" for member in project.members)
        )
        self.assertLess(ava_project.ends_on, date(2026, 9, 18))

    def test_provenance_and_immutability_are_internal(self):
        self.assertEqual(self.dataset.batch_id, BATCH_ID)
        self.assertIn("Synthetic", self.dataset.provenance)
        for project in self.dataset.projects:
            self.assertNotIn("dummy", project.title.lower())
            self.assertNotIn("fixture", project.title.lower())
        with self.assertRaises(FrozenInstanceError):
            self.dataset.people[0].role_code = "SYSTEM_ADMINISTRATOR"


if __name__ == "__main__":
    unittest.main()
