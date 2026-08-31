# Screen and Interaction Inventory

## Shared application shell

| Area | Approved content and behavior |
|---|---|
| Brand | `AI` brandmark, `AI Pod Staffing`, `Customer Success Services` |
| Sidebar | Workspace label, nine navigation items, active/hover/locked states, signed-in persona |
| Topbar | Mobile menu, `AI Pod › <workspace>` breadcrumb, global search, role selector and notifications |
| Persona selector | Operations Lead, Request Lead, Pod Lead, POD Member, Executive and System Administrator |
| Global overlays | Right drawer, modal, toast stack and Ask AI Pod chat |
| Responsive shell | Fixed desktop sidebar; off-canvas mobile sidebar below 760 px |

## Workspace inventory

| Screen ID | Visible title | Major components | Primary actions |
|---|---|---|---|
| `dashboard` | Good morning, Indranie | Four KPI cards, staffing queue or personal preview, Capacity Watch/My Capacity, Upcoming Demand, Audit Trail | New request, View all, Review request, Open audit trail |
| `requests` | Staffing requests | Status selector, search, priority/project/deliverable filters, request table | New request, Export CSV, Open request |
| `fitment` | AI fitment review | Request selector, request summary, factor evidence, recommended Pod Lead, contributors | Re-run, Approve pod, select candidate, open request |
| `calendar` | Allocation calendar | Week controls, skill/capacity filters, alternates toggle, weekly schedule, legend | Previous/next/current week, Allocate |
| `interests` | Team & skills | Profile summary, skill strength/evidence, team directory | Search, Add person, View person |
| `availability` | My availability | Availability event list and capacity snapshot | Add availability event |
| `agent` | Agent execution | Request selector, execution pipeline, execution log and result | Run fitment |
| `reports` | Executive reports | Report KPIs, demand chart, allocation chart, outcomes and callouts | Print / PDF |
| `admin` | Administration | Roles & access, Taxonomies, Agent rules and Audit trail | Preview POD Member, Save changes, switch tabs |

## Drawer inventory

| Drawer | Trigger | Required content/actions |
|---|---|---|
| Request details | Review/Open request | Project, deliverables, capabilities, request source, dates, effort, pod size, description, objectives, outcomes, scoped recommendations; Close and Open fitment |
| Create staffing request | New request | Controlled request form with workbook defaults and custom deliverables/capabilities; Cancel and Save request |
| Quick allocation | Allocate | Person, request, date, hours and guardrail notice; Cancel and Save allocation |
| Person details | View person | Profile, allocation, active pods, capabilities, strength and evidence |
| Add availability | Add availability event | Event type, dates, title and hours; Cancel and Save prototype event |
| Notifications | Notification icon | Fitment-ready and capacity-risk messages; Close |

## Modal inventory

| Modal | Trigger | Required content/actions |
|---|---|---|
| Human approval checkpoint | Approve pod | Current request, non-persistence notice, Cancel and Confirm prototype action |
| Allocation guardrail | Overload attempt | Guardrail explanation, alternate candidates and human-review actions |

## Create-request field inventory

1. Request title
2. Project type
3. Request source
4. Project description
5. Key deliverables — multiple catalogue selections plus custom entries
6. Priority
7. Needed by date
8. Estimated start date
9. Estimated completion date
10. Estimated effort value and unit
11. Requested pod size
12. Required capabilities — mapped defaults, optional additions/removals and custom values
13. Customer catalogue note — read-only
14. Business objectives
15. Expected outcomes

## Application-state inventory

The React provider in Phase 2 must explicitly represent:

- workbook view model;
- selected role and active workspace;
- active request ID and selected fitment candidates;
- request search and filter values;
- calendar week and temporary allocations;
- draft requests, custom deliverables and custom capabilities;
- local availability entries;
- current drawer, modal and toast state;
- active Administration tab;
- Agent Execution run state and timers;
- Ask AI Pod conversation state.

## Current calculation behaviors

- Open requests exclude status `Closed`.
- Staffing progress is staffed active requests divided by active requests.
- Team allocation is the average allocation percentage of people visible to the selected persona.
- Constrained count is visible people with allocation at or above 70%.
- Pending recommendations count persona-scoped recommendations whose decision status contains `Pending`.
- Allocation progress color becomes amber at 70% and red at 80%.

