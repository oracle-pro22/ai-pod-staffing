# Phase 4 — parity, accessibility and regression hardening

Status: **complete**

Phase 4 validates the component-based React preview against the locked Phase 1 HTML baselines. The React implementation remains at `/react-preview`; the approved HTML experience at `/` is still the live root until Phase 5 cutover.

## Completed work

- Compared the principal desktop screens at `1440 × 900` and mobile screens at `390 × 844` against the Phase 1 captures.
- Restored the approved compact KPI dimensions, request filter geometry, capacity ordering, fitment evidence proportions, request-summary structure and mobile breadcrumb behavior.
- Matched the create-request drawer’s prefilled project description, mapped deliverable selection, helper copy, fixed footer and mobile layout.
- Added visible keyboard focus styling throughout the shell.
- Added focus containment, Escape-to-close, background scroll locking and focus restoration for drawers and modals.
- Added Escape behavior to the mobile navigation and Ask AI Pod panel.
- Removed closed drawers from the rendered accessibility tree.
- Associated form-group labels with their controls for assistive technology.
- Re-ran all screen, overlay, persona, guardrail and session-draft flows.

## Intentional content differences from older captures

The visual baseline controls spacing, color, typography and interaction shape. Later approved business changes remain in place, including:

- `POD Member` and `Executive` persona terminology.
- POD Member identity and data scoping to Alex Rivera.
- Staffing progress as the third operational KPI.
- Multiple/custom deliverables and capabilities in the create-request flow.
- Separate Business objectives and Expected outcomes fields.
- Current workbook-backed content and catalogue values.

## Cutover boundary

The following remain intentionally unchanged in Phase 4:

- `app/page.tsx`
- `public/prototype.html`
- `public/prototype-app.js`

Phase 5 can promote the verified React implementation to `/`, remove the iframe dependency and perform final cleanup.

