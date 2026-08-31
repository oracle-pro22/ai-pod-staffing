# Workbook and API Data Contract

## Current flow

```text
data/ai-pod-staffing-prototype.xlsx
  → lib/staffing-data.ts
  → StaffingViewModel
  → GET /api/staffing
  → public/prototype-app.js
```

The workbook is read-only at runtime. Draft requests, availability events, allocations, approvals and Administration changes are demonstration state and are not written back to Excel.

## Workbook inventory

| Sheet | Used range | Data rows | Purpose |
|---|---:|---:|---|
| People | `A1:G9` | 8 | Person identity, job, location, allocation and active pods |
| Interests | `A1:F14` | 13 | Customer capability/skill taxonomy |
| Person Interests | `A1:E28` | 27 | Person-to-capability strength and evidence |
| Requests | `A1:N4` | 3 | Staffing requests and their primary catalogue mapping |
| Requirements | `A1:G11` | 10 | Required capabilities per request/deliverable |
| Availability | `A1:F5` | 4 | Leave, travel and commitment events |
| Recommendations | `A1:G4` | 3 | Candidate recommendation evidence and decision status |
| Customer Mapping | `A1:H68` | 67 | Original customer project/deliverable/capability mapping, including separator rows |
| Project Types | `A1:E12` | 11 | Normalized project-type catalogue |
| Deliverables | `A1:H56` | 55 | Normalized deliverable catalogue |
| Deliverable Skills | `A1:E88` | 87 | Normalized deliverable-to-capability relationships |

## Sheet columns

| Sheet | Columns |
|---|---|
| People | `person_id`, `full_name`, `initials`, `job_title`, `location`, `allocation_pct`, `active_pods` |
| Interests | `interest_id`, `interest_name`, `category`, `source`, `source_version`, `customer_controlled` |
| Person Interests | `person_id`, `interest_id`, `strength`, `evidence_note`, `source` |
| Requests | `request_id`, `title`, `project_type_id`, `project_type`, `deliverable_id`, `deliverable`, `skills_type_of_work`, `owner_name`, `needed_by`, `estimated_hours`, `priority`, `status`, `business_context`, `mapping_version` |
| Requirements | `request_id`, `deliverable_id`, `interest_id`, `skill_name`, `required_strength`, `requirement_source`, `source_version` |
| Availability | `person_id`, `event_type`, `starts_on`, `ends_on`, `title`, `allocated_hours` |
| Recommendations | `request_id`, `person_id`, `role_in_pod`, `score`, `rationale`, `decision_status`, `source` |
| Customer Mapping | `Projects`, `Project Description`, `Deliverables`, `Skills (Type of work)`, `Note`, `source_version`, `source_row`, `customer_controlled` |
| Project Types | `project_type_id`, `project_name`, `project_description`, `source_version`, `source_row` |
| Deliverables | `deliverable_id`, `project_type_id`, `project_name`, `deliverable_name`, `skills_raw`, `customer_note`, `source_version`, `source_row` |
| Deliverable Skills | `deliverable_id`, `skill_id`, `skill_name`, `source_version`, `source_row` |

## `StaffingViewModel` boundaries

The current server view model contains:

- `source`: workbook filename, modification time and source version;
- `catalog.projects`: project types with nested deliverables and mapped skills;
- `catalog.skills`: normalized customer-controlled capability catalogue;
- `people`: profile, allocation, active pods, capabilities/evidence and availability;
- `requests`: request, primary project/deliverable, required skills and recommendations;
- `metrics`: counts and allocation/recommendation totals;
- `demoIdentity`: POD Member `P-001`, Pod Lead `P-006`;
- `integrity`: relationship-check status and row counts.

## APIs

### `GET /api/staffing`

Returns:

```text
source mode
workbook path
typed staffing view model
```

The route uses Node runtime and disables caching.

### `POST /api/chat`

Accepts a message and selected role. It returns a workbook-derived, role-scoped prototype answer. It is currently deterministic keyword/rule logic, not a production enterprise AI agent.

## Integrity rules that must remain server-side

- Every person capability references an existing person and capability.
- Every request references valid project and deliverable records.
- Every requirement references valid request, deliverable and capability records.
- Every recommendation references valid request and person records.
- Every availability event references a valid person.

## Type gaps to resolve in Phase 2

The UI now supports fields that are not fully represented in the exported `StaffingViewModel` request type:

- multiple deliverables;
- request source distinct from owner;
- project description;
- estimated start and completion dates;
- estimated effort value and unit;
- requested pod size;
- business objectives;
- expected outcomes;
- custom capabilities and custom deliverables.

Phase 2 must define one canonical `StaffingRequest` type covering workbook records and local drafts. Compatibility helpers may translate the current workbook's singular deliverable and `business_context` into the richer UI model.

