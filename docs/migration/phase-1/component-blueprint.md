# React Component and Route Blueprint

## Route map

| Approved workspace | Target route | Page component |
|---|---|---|
| Command Center | `/` | `CommandCenterPage` |
| Requests | `/requests` | `RequestsPage` |
| AI Fitment | `/ai-fitment` | `AiFitmentPage` |
| Allocation Calendar | `/allocation-calendar` | `AllocationCalendarPage` |
| Team & Skills | `/team-skills` | `TeamSkillsPage` |
| My Availability | `/availability` | `AvailabilityPage` |
| Agent Execution | `/agent-execution` | `AgentExecutionPage` |
| Reports | `/reports` | `ReportsPage` |
| Administration | `/administration` | `AdministrationPage` |

## Target component tree

```text
RootLayout (server)
└── StaffingDataBoundary (server)
    └── StaffingAppProvider (client)
        └── AppShell
            ├── Sidebar
            │   ├── Brand
            │   ├── WorkspaceNavigation
            │   └── PersonaIdentity
            ├── Topbar
            │   ├── MobileMenuButton
            │   ├── Breadcrumb
            │   ├── GlobalSearch
            │   ├── RoleSelector
            │   └── NotificationsButton
            ├── Active route page
            ├── DrawerHost
            ├── ModalHost
            ├── ToastHost
            └── AskAiPod
```

## Feature components

```text
command-center/
  CommandCenter.tsx
  KpiCard.tsx
  PriorityStaffingQueue.tsx
  PodMemberFitmentPreview.tsx
  CapacityWatch.tsx
  MyCapacity.tsx
  UpcomingDemand.tsx
  AuditTrailCard.tsx

requests/
  RequestFilters.tsx
  RequestTable.tsx
  RequestDetailsDrawer.tsx
  CreateRequestForm.tsx
  DeliverablesEditor.tsx
  CapabilitiesEditor.tsx

fitment/
  FitmentRequestSelector.tsx
  RequestSummary.tsx
  RecommendationFactors.tsx
  CandidateList.tsx
  CandidateCard.tsx
  ApprovalCheckpointModal.tsx

calendar/
  CalendarToolbar.tsx
  WeeklySchedule.tsx
  CalendarLegend.tsx
  QuickAllocationDrawer.tsx
  GuardrailModal.tsx

team/
  ProfileSummary.tsx
  SkillsAndStrength.tsx
  TeamDirectory.tsx
  PersonDetailsDrawer.tsx

availability/
  AvailabilityEventList.tsx
  CapacitySnapshot.tsx
  AvailabilityForm.tsx

agent-execution/
  ExecutionPipeline.tsx
  ExecutionLog.tsx
  ExecutionResult.tsx

reports/
  ReportKpis.tsx
  DemandChart.tsx
  AllocationChart.tsx
  RecommendationOutcomes.tsx

administration/
  AdminTabs.tsx
  RoleMatrix.tsx
  TaxonomyPanel.tsx
  AgentRulesPanel.tsx
  AuditPanel.tsx
```

## Shared UI primitives

`Button`, `IconButton`, `Card`, `Pill`, `Avatar`, `ProgressBar`, `TextField`, `SelectField`, `TextArea`, `Drawer`, `Modal`, `Toast`, `EmptyState`, `Icon`.

Only repeated, visually stable patterns become shared primitives. One-off screen structures should remain feature components during the parity migration to avoid premature abstraction.

## Server/client boundary

- Server: workbook file access, parsing, integrity validation and initial view-model construction.
- Client: persona switching, navigation state, forms, filters, overlays, temporary prototype changes, chat and execution animation.
- Shared: pure domain types, formatting utilities, selectors and role-policy definitions.

## State design

Use a `StaffingAppProvider` with `useReducer`. Keep workbook data immutable and store user-created prototype changes separately.

Derived selectors include:

- `selectVisibleRequests`
- `selectVisiblePeople`
- `selectActiveRequest`
- `selectScopedRecommendations`
- `selectDashboardMetrics`
- `selectCalendarRows`
- `selectRoleAccess`

## Cutover strategy

The HTML version remains reachable at `/prototype.html` until Phase 5 acceptance. React routes are built and compared independently. The iframe is removed from `app/page.tsx` only after all screens pass parity checks.

