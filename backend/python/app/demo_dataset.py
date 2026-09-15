"""Deterministic, synthetic demonstration inputs; no database or network access.

Names and IDs refer to the existing demonstration roster, but job histories,
skills, locations and commitments below are *not* verified employee facts.
Catalogue references use exact names and must be resolved/validated by the loader.
Allocation percentages are deliberately absent: capacity and real assignment
days, not a display percentage, are the source of truth.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal


BATCH_ID = "AIPS_DEMO_COMPLETE_V1"
DATASET_VERSION = 1
CAPACITY_WEEKS = 9  # The current Monday-Sunday and eight future weeks.
PROVENANCE = "Synthetic business scenarios for staffing demonstrations; not verified employee information."


@dataclass(frozen=True)
class DemoSkill:
    name: str
    strength: int
    interested: bool
    evidence: str


@dataclass(frozen=True)
class DemoExperience:
    project_type: str
    deliverable_name: str
    experience_level: str
    contribution_scope: str
    interested: bool
    experience: str


@dataclass(frozen=True)
class DemoPerson:
    person_id: str
    full_name: str
    job_title: str
    location: str
    weekly_hours: Decimal
    external_weekly_hours: Decimal
    role_code: str
    email: str
    skills: tuple[DemoSkill, ...]
    deliverables: tuple[DemoExperience, ...]

    @property
    def initials(self) -> str:
        return "".join(part[0] for part in self.full_name.split()[:2])

    @property
    def staffing_eligible(self) -> bool:
        return self.role_code in {"POD_LEAD", "POD_MEMBER"}


@dataclass(frozen=True)
class DemoMember:
    person_id: str
    role: str
    hours: Decimal
    responsibilities: str


@dataclass(frozen=True)
class DemoProject:
    request_id: str
    title: str
    project_type: str
    deliverable_name: str
    captain_id: str
    source_person_id: str
    starts_on: date
    ends_on: date
    members: tuple[DemoMember, ...]
    business_objectives: str
    expected_outcomes: str
    priority: str = "MEDIUM"

    @property
    def total_hours(self) -> Decimal:
        return sum((member.hours for member in self.members), Decimal(0))


@dataclass(frozen=True)
class DemoAvailability:
    person_id: str
    event_type: str
    starts_on: date
    ends_on: date
    title: str
    hours: Decimal
    capacity_kind: str = "NON_AVAILABILITY"


@dataclass(frozen=True)
class DemoDataset:
    anchor: date
    capacity_end: date
    people: tuple[DemoPerson, ...]
    projects: tuple[DemoProject, ...]
    availability: tuple[DemoAvailability, ...]
    batch_id: str = BATCH_ID
    version: int = DATASET_VERSION
    provenance: str = PROVENANCE

    @property
    def capacity_start(self) -> date:
        return self.anchor


def _skill(name: str, strength: int, evidence: str, interested: bool = True) -> DemoSkill:
    return DemoSkill(name, strength, interested, evidence)


def _experience(
    project: str,
    deliverable: str,
    level: str,
    description: str,
    *,
    scope: str = "END_TO_END",
    interested: bool = True,
) -> DemoExperience:
    return DemoExperience(project, deliverable, level, scope, interested, description)


def _person(
    person_id: str,
    name: str,
    title: str,
    location: str,
    role: str,
    external: int,
    skills: tuple[DemoSkill, ...],
    deliverables: tuple[DemoExperience, ...],
    weekly: int = 40,
) -> DemoPerson:
    # Reserved domain prevents these demonstration addresses from reaching people.
    email = f"{name.lower().replace(' ', '.')}@example.invalid"
    return DemoPerson(
        person_id,
        name,
        title,
        location,
        Decimal(weekly),
        Decimal(external),
        role,
        email,
        skills,
        deliverables,
    )


def demonstration_people() -> tuple[DemoPerson, ...]:
    """Existing sixteen IDs plus a standalone administrator, with varied evidence."""
    return (
        _person(
            "P-001",
            "Alex Rivera",
            "Senior Content Strategist",
            "Austin",
            "POD_MEMBER",
            12,
            (
                _skill(
                    "GTM SME", 5, "Translated service capabilities into sales narratives for four launches."
                ),
                _skill(
                    "Comms Plan",
                    4,
                    "Planned audience-specific messages and review milestones for launch content.",
                ),
                _skill(
                    "Script writer (GTM SME)",
                    4,
                    "Wrote demonstration scripts that connect product features to customer needs.",
                ),
                _skill(
                    "Comms Review", 3, "Reviewed technical accuracy and claims in customer-facing collateral."
                ),
            ),
            (
                _experience(
                    "New Service Launch",
                    "Sales Guide (deck)",
                    "MENTOR",
                    "Owned three sales-guide decks from discovery through sales review and coached two contributors.",
                ),
                _experience(
                    "Customer Story",
                    "Story Creation",
                    "INDEPENDENT",
                    "Turned interview notes into a customer story with approved benefit statements.",
                ),
                _experience(
                    "Demo Package",
                    "Demo video",
                    "SUPPORTED",
                    "Prepared scripts and checked messages with the video production team.",
                    scope="CONTRIBUTOR",
                ),
            ),
        ),
        _person(
            "P-002",
            "Maya Chen",
            "Video Producer",
            "Seattle",
            "POD_MEMBER",
            16,
            (
                _skill(
                    "video creation",
                    5,
                    "Produced customer demonstrations with screen capture, editing and final quality checks.",
                ),
                _skill(
                    "visual asset", 5, "Created storyboards and graphics for six product and customer videos."
                ),
                _skill("narration audio", 4, "Recorded, edited and balanced narration for launch videos."),
                _skill(
                    "Comms Review",
                    3,
                    "Checked subtitle accuracy and consistency with approved launch messages.",
                    False,
                ),
            ),
            (
                _experience(
                    "Demo Package",
                    "Demo video",
                    "MENTOR",
                    "Managed scripting handoff, visual production and final delivery for six demonstrations.",
                ),
                _experience(
                    "Demo Package",
                    "Hook video",
                    "INDEPENDENT",
                    "Delivered short promotional cuts with a clear opening message and call to action.",
                ),
                _experience(
                    "Customer Story",
                    "Videos",
                    "INDEPENDENT",
                    "Edited customer interviews into a reviewed case-study video.",
                ),
            ),
        ),
        _person(
            "P-003",
            "Jordan Lee",
            "Technical Writer",
            "Denver",
            "POD_MEMBER",
            8,
            (
                _skill(
                    "GTM SME",
                    4,
                    "Documented service use cases and technical boundaries for sales and customer audiences.",
                ),
                _skill(
                    "Comms Review",
                    5,
                    "Reviewed technical wording, evidence and terminology in service launch materials.",
                ),
                _skill(
                    "Script writer (GTM SME)",
                    4,
                    "Wrote narration drafts and step-by-step demonstration explanations.",
                ),
                _skill(
                    "Portal SME",
                    3,
                    "Maintained reviewed help content and link structure in the internal portal.",
                    False,
                ),
            ),
            (
                _experience(
                    "New Service Launch",
                    "Sales Guide (deck)",
                    "INDEPENDENT",
                    "Wrote objection-handling sections and validated service descriptions before publication.",
                ),
                _experience(
                    "New Service Launch",
                    "Content Communication Review",
                    "MENTOR",
                    "Led technical and editorial review of launch assets with subject-matter experts.",
                ),
                _experience(
                    "Use Case Content",
                    "Create AI Use Case Content",
                    "INDEPENDENT",
                    "Prepared a structured use-case brief with assumptions, steps and expected value.",
                ),
            ),
        ),
        _person(
            "P-004",
            "Priya Nair",
            "Enablement Lead",
            "Bengaluru",
            "POD_LEAD",
            12,
            (
                _skill("GTM", 5, "Led sales-enablement content development for regional service teams."),
                _skill(
                    "GTM SME",
                    4,
                    "Explained service positioning and customer scenarios in enablement sessions.",
                ),
                _skill(
                    "GTM Buddy",
                    5,
                    "Coached facilitators through dry runs and supported live training delivery.",
                ),
                _skill(
                    "Comms Plan",
                    4,
                    "Coordinated learning objectives, audience communications and session follow-up.",
                ),
            ),
            (
                _experience(
                    "Enablement",
                    "Create Training Deck",
                    "MENTOR",
                    "Led the preparation and review of four training decks and coached new content authors.",
                ),
                _experience(
                    "Enablement",
                    "Conduct Enablement Webinar",
                    "MENTOR",
                    "Coordinated presenters, rehearsal, delivery and follow-up for monthly enablement webinars.",
                ),
                _experience(
                    "New Service Launch",
                    "Training Deck",
                    "INDEPENDENT",
                    "Converted a service launch brief into role-based training and practice questions.",
                ),
            ),
        ),
        _person(
            "P-005",
            "Sam Okafor",
            "Creative Director",
            "London",
            "POD_MEMBER",
            12,
            (
                _skill(
                    "Comms Review",
                    5,
                    "Reviewed brand tone, claim consistency and creative direction across campaign assets.",
                ),
                _skill(
                    "visual asset",
                    5,
                    "Designed presentation and video artwork using reusable visual standards.",
                ),
                _skill(
                    "Comms Plan", 4, "Planned consistent message sequencing across creative deliverables."
                ),
                _skill(
                    "Comms Team",
                    4,
                    "Coordinated editorial, design and stakeholder reviews under delivery deadlines.",
                ),
            ),
            (
                _experience(
                    "Demo Package",
                    "Demo video",
                    "INDEPENDENT",
                    "Directed visual treatment and communication review with an editor and script writer.",
                    scope="CONTRIBUTOR",
                ),
                _experience(
                    "Strategic Initiative Campaign Launch",
                    "Customer Assets",
                    "MENTOR",
                    "Guided asset development from creative brief through stakeholder approval.",
                ),
                _experience(
                    "Executive Support",
                    "Executive Decks",
                    "INDEPENDENT",
                    "Designed an executive narrative and presentation layout for a quarterly briefing.",
                ),
            ),
        ),
        _person(
            "P-006",
            "Elena Garcia",
            "Communications Manager",
            "Madrid",
            "POD_LEAD",
            8,
            (
                _skill(
                    "GTM SME", 5, "Coordinated go-to-market communications across multiple service launches."
                ),
                _skill(
                    "Comms Review",
                    5,
                    "Led cross-functional review of launch claims, messaging and editorial consistency.",
                ),
                _skill(
                    "Comms Plan",
                    5,
                    "Owned launch timelines, stakeholder communications and message dependencies.",
                ),
                _skill(
                    "Portal SME",
                    4,
                    "Managed publishing readiness and content ownership for the service portal.",
                ),
                _skill(
                    "Comms Team", 4, "Organized communication contributors and resolved review dependencies."
                ),
            ),
            (
                _experience(
                    "New Service Launch",
                    "Sales Guide (deck)",
                    "MENTOR",
                    "Led a cross-functional team producing launch sales guidance from brief to approved final deck.",
                ),
                _experience(
                    "New Service Launch",
                    "Project Communication Plan",
                    "MENTOR",
                    "Defined audience, review ownership and release sequence for a service launch.",
                ),
                _experience(
                    "Portal & Content Operations",
                    "Portal Updates",
                    "INDEPENDENT",
                    "Managed portal content changes, review checkpoints and publication readiness.",
                ),
                _experience(
                    "Customer Story",
                    "Story Creation",
                    "INDEPENDENT",
                    "Coordinated customer interviews, story drafting and final communication review.",
                ),
            ),
        ),
        _person(
            "P-007",
            "Noah Williams",
            "Video Editor",
            "Chicago",
            "POD_MEMBER",
            8,
            (
                _skill(
                    "video creation",
                    4,
                    "Edited demonstrations with clear pacing, captions and consistent transitions.",
                ),
                _skill(
                    "narration audio",
                    5,
                    "Cleaned recordings and mixed narration with screen-capture demonstrations.",
                ),
                _skill(
                    "visual asset",
                    4,
                    "Prepared lower-thirds, diagrams and thumbnail artwork for service videos.",
                ),
                _skill(
                    "Script writer (GTM SME)", 3, "Adapted written scripts for natural narration and timing."
                ),
            ),
            (
                _experience(
                    "Demo Package",
                    "Demo video",
                    "INDEPENDENT",
                    "Owned editing, narration mixing, captions and export checks for three demonstrations.",
                ),
                _experience(
                    "Enablement",
                    "Create recorded training",
                    "INDEPENDENT",
                    "Edited a training recording into chapters and checked audio and presentation synchronization.",
                ),
                _experience(
                    "Demo Package",
                    "Hook video",
                    "SUPPORTED",
                    "Created short cut-downs from an approved product demonstration.",
                    scope="CONTRIBUTOR",
                ),
            ),
        ),
        _person(
            "P-008",
            "Aisha Patel",
            "Learning Designer",
            "Atlanta",
            "POD_MEMBER",
            4,
            (
                _skill(
                    "GTM", 4, "Turned service positioning into learning objectives and practical exercises."
                ),
                _skill(
                    "GTM SME",
                    3,
                    "Prepared common service scenarios with review from a subject-matter expert.",
                ),
                _skill(
                    "GTM Buddy",
                    4,
                    "Supported facilitators with rehearsal feedback and participant questions.",
                ),
                _skill(
                    "visual asset", 3, "Designed clear instructional diagrams and reusable slide layouts."
                ),
            ),
            (
                _experience(
                    "Enablement",
                    "Create Training Deck",
                    "INDEPENDENT",
                    "Designed a training deck with learning objectives, worked examples and knowledge checks.",
                ),
                _experience(
                    "Enablement",
                    "Prepare for Live Session",
                    "INDEPENDENT",
                    "Prepared facilitator notes, exercises and rehearsal checklists for a live class.",
                ),
                _experience(
                    "Enablement",
                    "Conduct Enablement Webinar",
                    "SUPPORTED",
                    "Supported live facilitation and captured questions for follow-up.",
                    scope="CONTRIBUTOR",
                ),
            ),
        ),
        _person(
            "P-009",
            "Indranie Balkaran",
            "Programme Director",
            "New York",
            "POD_CAPTAIN",
            24,
            (
                _skill(
                    "GTM SME",
                    5,
                    "Defined launch priorities and reviewed service positioning with business stakeholders.",
                ),
                _skill(
                    "Comms Plan",
                    4,
                    "Established audience priorities, milestones and review ownership for delivery programmes.",
                ),
                _skill(
                    "Comms Review",
                    4,
                    "Reviewed customer-facing commitments and message clarity before programme sign-off.",
                ),
                _skill(
                    "GTM Buddy", 3, "Supported programme briefings and new stakeholder onboarding.", False
                ),
            ),
            (
                _experience(
                    "New Service Launch",
                    "Sales Guide (deck)",
                    "INDEPENDENT",
                    "Defined business outcomes and reviewed sales guidance with launch stakeholders.",
                    scope="CONTRIBUTOR",
                ),
                _experience(
                    "Executive Support",
                    "Executive Messaging",
                    "MENTOR",
                    "Shaped executive programme updates around decisions, risks and measurable outcomes.",
                ),
                _experience(
                    "New Service Launch",
                    "Project Communication Plan",
                    "INDEPENDENT",
                    "Reviewed communication priorities and stakeholder accountability for a launch programme.",
                ),
            ),
        ),
        _person(
            "P-010",
            "Brenna Cooper",
            "Customer Programmes Manager",
            "Boston",
            "POD_CAPTAIN",
            20,
            (
                _skill(
                    "GTM SME",
                    4,
                    "Defined customer programme needs and reviewed positioning for service updates.",
                ),
                _skill(
                    "Comms Plan",
                    5,
                    "Planned stakeholder communication for enablement and customer storytelling programmes.",
                ),
                _skill(
                    "Comms Team",
                    4,
                    "Coordinated communications contributors across customer and delivery teams.",
                ),
                _skill(
                    "Comms Review",
                    4,
                    "Reviewed stakeholder feedback and consistency of programme communication.",
                ),
            ),
            (
                _experience(
                    "Customer Story",
                    "Story Creation",
                    "INDEPENDENT",
                    "Defined the customer story brief and coordinated feedback from the account team.",
                    scope="CONTRIBUTOR",
                ),
                _experience(
                    "Enablement",
                    "Conduct Enablement Webinar",
                    "INDEPENDENT",
                    "Set audience outcomes, coordinated speakers and reviewed webinar follow-up.",
                ),
                _experience(
                    "Executive Support",
                    "QBRs",
                    "SUPPORTED",
                    "Prepared customer programme summaries and tracked review actions.",
                    scope="CONTRIBUTOR",
                ),
            ),
        ),
        _person(
            "P-011",
            "Robert Story",
            "Content Operations Specialist",
            "Raleigh",
            "POD_MEMBER",
            12,
            (
                _skill(
                    "Portal SME",
                    5,
                    "Managed content structure, publishing checks and permissions on an internal service portal.",
                ),
                _skill(
                    "GTM SME",
                    4,
                    "Maintained accurate service descriptions and links to current sales resources.",
                ),
                _skill(
                    "GTM",
                    3,
                    "Supported content handoff from service teams into reusable go-to-market assets.",
                ),
                _skill(
                    "Comms Review",
                    3,
                    "Checked content currency, broken links and publication metadata.",
                    False,
                ),
            ),
            (
                _experience(
                    "Portal & Content Operations",
                    "Portal Updates",
                    "MENTOR",
                    "Owned portal publishing, link validation and content-owner handoff for weekly releases.",
                ),
                _experience(
                    "Portal & Content Operations",
                    "Asset Publishing",
                    "INDEPENDENT",
                    "Published approved assets with correct ownership, version and audience metadata.",
                ),
                _experience(
                    "New Service Launch",
                    "Internal Portal Updates",
                    "INDEPENDENT",
                    "Prepared launch pages and checked supporting sales and training asset links.",
                ),
            ),
        ),
        _person(
            "P-900101",
            "Amelia Hart",
            "Enablement Content Specialist",
            "Bengaluru",
            "POD_MEMBER",
            8,
            (
                _skill(
                    "GTM",
                    4,
                    "Prepared service enablement content with role-specific examples and clear learning outcomes.",
                ),
                _skill(
                    "GTM SME",
                    4,
                    "Drafted service briefs and verified customer scenarios with subject-matter experts.",
                ),
                _skill("GTM Buddy", 3, "Supported training rehearsals and participant follow-up."),
                _skill("Comms Plan", 3, "Tracked content-review milestones and contributor handoffs."),
            ),
            (
                _experience(
                    "Enablement",
                    "Create Training Deck",
                    "INDEPENDENT",
                    "Created an enablement slide sequence with examples, presenter notes and follow-up resources.",
                ),
                _experience(
                    "New Service Launch",
                    "Sales Guide (deck)",
                    "INDEPENDENT",
                    "Prepared service benefits, use cases and common objections for a sales guide.",
                ),
                _experience(
                    "Enablement",
                    "Post Replay Assets",
                    "SUPPORTED",
                    "Prepared reviewed slides, replay links and participant follow-up resources.",
                    scope="CONTRIBUTOR",
                ),
            ),
        ),
        _person(
            "P-900102",
            "Mara Bennett",
            "Delivery Programme Lead",
            "Bengaluru",
            "POD_LEAD",
            6,
            (
                _skill(
                    "GTM SME",
                    5,
                    "Led cross-functional content delivery and kept launch messages aligned to the service brief.",
                ),
                _skill(
                    "Comms Review",
                    4,
                    "Coordinated quality review of scripts, stories and sales-facing content.",
                ),
                _skill(
                    "Script writer (GTM SME)",
                    4,
                    "Developed demonstration storylines and reviewed technical narration with specialists.",
                ),
                _skill(
                    "Comms Plan",
                    4,
                    "Managed contributor handoffs, review decisions and delivery dependencies.",
                ),
                _skill(
                    "GTM Buddy", 3, "Supported new contributors during content preparation and rehearsal."
                ),
            ),
            (
                _experience(
                    "Demo Package",
                    "Demo video",
                    "MENTOR",
                    "Led a script, design and editing team from customer scenario to reviewed demonstration video.",
                ),
                _experience(
                    "Customer Story",
                    "Story Creation",
                    "MENTOR",
                    "Guided interview planning, narrative development and stakeholder review for customer stories.",
                ),
                _experience(
                    "New Service Launch",
                    "Sales Guide (deck)",
                    "INDEPENDENT",
                    "Coordinated end-to-end sales-guide delivery and resolved review feedback.",
                ),
            ),
        ),
        _person(
            "P-900103",
            "Carlos Reed",
            "Service Content Specialist",
            "Austin",
            "POD_MEMBER",
            12,
            (
                _skill(
                    "GTM SME",
                    4,
                    "Prepared accurate service summaries and practical customer examples for sales teams.",
                ),
                _skill("Portal SME", 4, "Maintained service-page content and supporting asset references."),
                _skill(
                    "Comms Review",
                    3,
                    "Checked technical wording and consistency across related service assets.",
                ),
                _skill("Comms Plan", 3, "Coordinated asset review dates and publication handoffs.", False),
            ),
            (
                _experience(
                    "Portal & Content Operations",
                    "Portal Updates",
                    "INDEPENDENT",
                    "Updated service pages, validated linked assets and completed publishing checks.",
                ),
                _experience(
                    "New Service Launch",
                    "Sales Guide (deck)",
                    "INDEPENDENT",
                    "Developed use-case and service-benefit sections with examples for sellers.",
                ),
                _experience(
                    "Service Updates",
                    "Update Existing Communications/Content",
                    "INDEPENDENT",
                    "Updated service messaging and retired outdated references after a release change.",
                ),
            ),
        ),
        _person(
            "P-900104",
            "Ava Morgan",
            "Customer Story Writer",
            "Portland",
            "POD_MEMBER",
            8,
            (
                _skill(
                    "GTM SME",
                    4,
                    "Connected customer needs, service use cases and supported outcome statements.",
                ),
                _skill(
                    "Script writer (GTM SME)",
                    4,
                    "Developed interview questions and story outlines with a clear customer narrative.",
                ),
                _skill(
                    "Comms Review", 4, "Checked customer quotes, claim support and editorial consistency."
                ),
                _skill(
                    "Comms Team",
                    3,
                    "Coordinated interview notes and feedback between account and content teams.",
                ),
            ),
            (
                _experience(
                    "Customer Story",
                    "Story Creation",
                    "INDEPENDENT",
                    "Turned interview material into a reviewed story with supported customer benefits.",
                ),
                _experience(
                    "Customer Story",
                    "Interviews",
                    "INDEPENDENT",
                    "Prepared discussion guides, captured interview notes and confirmed the narrative with stakeholders.",
                ),
                _experience(
                    "New Service Launch",
                    "Sales Guide (deck)",
                    "SUPPORTED",
                    "Drafted customer examples and checked language with a service specialist.",
                    scope="CONTRIBUTOR",
                ),
            ),
        ),
        _person(
            "P-900105",
            "Noah Foster",
            "Associate Content Specialist",
            "Dublin",
            "POD_MEMBER",
            4,
            (
                _skill(
                    "GTM SME",
                    3,
                    "Prepared customer scenarios and service summaries with subject-matter review.",
                ),
                _skill(
                    "Comms Review",
                    3,
                    "Checked style, terminology and reviewer comments under editorial guidance.",
                ),
                _skill(
                    "GTM Buddy", 3, "Supported contributor onboarding and tracked content review follow-up."
                ),
                _skill(
                    "visual asset",
                    2,
                    "Created simple draft diagrams while learning the presentation design standards.",
                ),
            ),
            (
                _experience(
                    "Customer Story",
                    "Story Creation",
                    "SUPPORTED",
                    "Prepared research notes, drafted supporting sections and applied editorial feedback.",
                    scope="CONTRIBUTOR",
                ),
                _experience(
                    "New Service Launch",
                    "Sales Guide (deck)",
                    "SUPPORTED",
                    "Contributed customer examples and incorporated reviewer changes with guidance.",
                    scope="CONTRIBUTOR",
                ),
                _experience(
                    "Enablement",
                    "Create Training Deck",
                    "LEARNING",
                    "Practised converting reviewed content into a training-slide outline.",
                    scope="CONTRIBUTOR",
                ),
            ),
        ),
        _person(
            "P-012", "Administrator", "System Administrator", "Bengaluru", "SYSTEM_ADMINISTRATOR", 0, (), ()
        ),
    )


def _member(person_id: str, role: str, responsibility: str, hours: str = "24") -> DemoMember:
    return DemoMember(person_id, role, Decimal(hours), responsibility)


def build_demo_dataset(today: date) -> DemoDataset:
    """Build a rolling capacity window and five coherent, already-started projects.

    Four projects span three working weeks at eight hours/person/week. The story
    project ends next Thursday, avoiding Ava's original Friday travel fixture when
    this dataset is first loaded. The loader must still validate *all* retained
    availability; this function never assumes an existing database is empty.
    """
    if not isinstance(today, date):
        raise TypeError("today must be a date")
    anchor = today - timedelta(days=today.weekday())
    end = anchor + timedelta(days=18)
    projects = (
        DemoProject(
            "REQ-910001",
            "AI service sales readiness guide",
            "New Service Launch",
            "Sales Guide (deck)",
            "P-009",
            "P-010",
            anchor,
            end,
            (
                _member(
                    "P-006",
                    "POD_LEAD",
                    "Coordinate the launch brief, content reviews and final sales-guide delivery.",
                ),
                _member(
                    "P-001",
                    "POD_MEMBER",
                    "Develop the value proposition, customer scenarios and sales narrative.",
                ),
                _member(
                    "P-003",
                    "POD_MEMBER",
                    "Validate service details and prepare accurate objection-handling guidance.",
                ),
            ),
            "Give sellers a clear and accurate guide to the new AI service and its customer use cases.",
            "Deliver a reviewed sales deck with supported service claims, customer examples and objection-handling guidance.",
            "HIGH",
        ),
        DemoProject(
            "REQ-910002",
            "Customer AI demonstration video",
            "Demo Package",
            "Demo video",
            "P-009",
            "P-001",
            anchor,
            end,
            (
                _member(
                    "P-900102",
                    "POD_LEAD",
                    "Own the demonstration storyline, script handoffs and stakeholder review.",
                ),
                _member(
                    "P-002",
                    "POD_MEMBER",
                    "Produce screen captures, sequence the visuals and check the final video.",
                ),
                _member(
                    "P-007",
                    "POD_MEMBER",
                    "Edit the demonstration, record narration and check captions and audio.",
                ),
                _member(
                    "P-005",
                    "POD_MEMBER",
                    "Develop supporting visual assets and review message and brand consistency.",
                ),
            ),
            "Help customer teams understand the AI service through a concise, credible product demonstration.",
            "Publish an approved demonstration video with clear narration, accurate captions and consistent visual treatment.",
            "HIGH",
        ),
        DemoProject(
            "REQ-910003",
            "Regional service enablement training",
            "Enablement",
            "Create Training Deck",
            "P-010",
            "P-004",
            anchor,
            end,
            (
                _member(
                    "P-004",
                    "POD_LEAD",
                    "Set learning outcomes, guide authors and coordinate the training-deck review.",
                ),
                _member(
                    "P-008",
                    "POD_MEMBER",
                    "Design practical exercises, instructional slides and presenter guidance.",
                ),
                _member(
                    "P-900101",
                    "POD_MEMBER",
                    "Prepare service examples, knowledge checks and follow-up resources.",
                ),
            ),
            "Prepare regional customer-facing teams to explain the service consistently and identify suitable customer scenarios.",
            "Deliver a facilitator-ready training deck with learning objectives, worked examples and knowledge checks.",
        ),
        DemoProject(
            "REQ-910004",
            "Service resource portal refresh",
            "Portal & Content Operations",
            "Portal Updates",
            "P-009",
            "P-011",
            anchor,
            end,
            (
                _member(
                    "P-006",
                    "POD_LEAD",
                    "Coordinate content ownership, review checkpoints and portal publication readiness.",
                ),
                _member(
                    "P-011",
                    "POD_MEMBER",
                    "Update portal structure, publishing metadata and linked resource references.",
                ),
                _member(
                    "P-900103",
                    "POD_MEMBER",
                    "Refresh service descriptions and validate current sales and training assets.",
                ),
            ),
            "Make it easier for sellers to find accurate, current service information and approved supporting assets.",
            "Publish reviewed portal updates with working links, clear content ownership and current service descriptions.",
        ),
        DemoProject(
            "REQ-910005",
            "Customer success story package",
            "Customer Story",
            "Story Creation",
            "P-010",
            "P-009",
            anchor,
            anchor + timedelta(days=10),
            (
                _member(
                    "P-900102",
                    "POD_LEAD",
                    "Guide the customer narrative, assign review ownership and coordinate final story approval.",
                    "18",
                ),
                _member(
                    "P-900104",
                    "POD_MEMBER",
                    "Develop interview themes, draft the customer narrative and validate supported benefits.",
                    "18",
                ),
                _member(
                    "P-900105",
                    "POD_MEMBER",
                    "Prepare research notes, supporting story sections and editorial-review updates.",
                    "18",
                ),
            ),
            "Show how a customer used the service to address a business need through an evidence-backed narrative.",
            "Deliver a reviewed customer story with a clear problem, approach and supported outcome statements.",
        ),
    )
    # Future examples avoid baseline assignments. A separate existing event is
    # never silently removed or duplicated by this pure definition.
    availability = (
        DemoAvailability(
            "P-002",
            "Travel",
            anchor + timedelta(days=24),
            anchor + timedelta(days=25),
            "Customer production workshop",
            Decimal("16"),
        ),
        DemoAvailability(
            "P-004",
            "Leave",
            anchor + timedelta(days=32),
            anchor + timedelta(days=32),
            "Planned annual leave",
            Decimal("8"),
        ),
        DemoAvailability(
            "P-900104",
            "Leave",
            anchor + timedelta(days=39),
            anchor + timedelta(days=39),
            "Planned personal leave",
            Decimal("8"),
        ),
    )
    return DemoDataset(
        anchor,
        anchor + timedelta(days=CAPACITY_WEEKS * 7 - 1),
        demonstration_people(),
        projects,
        availability,
    )
