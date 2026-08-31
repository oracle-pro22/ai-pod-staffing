# Phase 2 — Typed React foundation

Status: **complete**

Phase 2 establishes the reusable Next.js/React foundation beside the approved HTML prototype. The public root route remains unchanged and still serves `public/prototype.html` through the existing iframe. The React implementation is intentionally isolated at `/react-preview` until the later cutover phase.

## Delivered

- Canonical TypeScript models for roles, catalog data, people, availability, requests, recommendations, UI state, and actions.
- A normalized workbook adapter that presents one consistent request shape to React while retaining compatibility with the HTML prototype.
- Central role policy with full, scoped, own-data, and locked access behavior.
- Selectors for role-scoped requests, people, recommendations, identities, and dashboard metrics.
- Stable workbook date and effort formatting utilities.
- A shared reducer/provider for role, screen, request, filter, overlay, draft, and toast state.
- Reusable React UI primitives for buttons, cards, pills, avatars, progress, drawers, modals, empty states, icons, and toasts.
- The exact persistent application shell: brand, navigation, persona selector, search, notifications, signed-in identity, and Ask AI Pod.
- An isolated server-backed preview route at `/react-preview`.

## Component structure

```text
ReactPreviewPage (server)
└── StaffingAppProvider (client state)
    └── AppShell
        ├── Sidebar
        │   ├── Brand
        │   └── Navigation → role policy
        ├── Topbar
        │   └── RoleSelector
        ├── Screen content
        ├── AskAiPod → /api/chat
        ├── NotificationDrawer → scoped selectors
        └── ToastHost
```

## State boundary

The workbook remains the read-only source for catalog, people, requests, availability, and recommendation evidence. `StaffingAppProvider` owns only session-level UI and prototype mutations. The provider does not write back to Excel.

## Access behavior verified

- Operations Lead: all nine workspaces available.
- Pod Lead: Allocation Calendar, Agent Execution, Reports, and Administration are locked.
- Pod Lead identity: Elena Garcia.
- POD Member identity: Alex Rivera and own/scoped selectors are active.
- A click on a locked workspace does not navigate and produces an access message.
- Changing persona resets an inaccessible active screen to Command Center.

## Verification

- `npm run build`: passed with strict TypeScript checking.
- `/react-preview`: server-rendered successfully from the Excel-backed view model.
- Desktop shell visually inspected against the approved prototype.
- Role selector, access locks, notifications, and Ask AI Pod interactions checked in the browser.
- Existing `/` route and `public/prototype.html` were not modified.

## Deferred to Phase 3

The nine workspace screen bodies remain on the HTML prototype. Phase 3 will move them into typed React screen components using this shell, provider, policy, selectors, and primitives.
