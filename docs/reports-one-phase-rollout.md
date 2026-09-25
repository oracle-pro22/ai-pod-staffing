# Reports one-phase rollout

This release installs the complete reporting feature in one application deployment. It does not change people, requests, POD assignments, capacity days, catalogues, policies, or archived data.

## Delivered behavior

- **Administrator:** all projects, all employee capacity, all PODs, and Excel export.
- **POD Captain:** all projects, all employee capacity, all PODs, and Excel export.
- **POD Lead:** only projects where the person has a final Lead or Member assignment; scoped teammate visibility; no export.
- **POD Member:** only projects where the person has a final assignment; own capacity; no export.
- Overview, Capacity, Projects & PODs, My PODs, and permission-checked Excel exports.
- Capacity separates confirmed POD work, onboarding-reported POD work, external commitments, and leave.
- Projects show Lead, Members, assigned hours, schedule, delivery state, and whether staffing came from the agent or a manual override.
- Login and workspace loading now have bounded timeouts and actionable retry messages.
- Capacity is loaded with a fixed set of batched database reads instead of repeating the same reads for every person.

## Database step

With the application services stopped, connect as `AI_POD_STAFFING` and run:

```sql
@sql/oracle/reports_scoped_access.sql
```

Expected message:

```text
Reports access installed. Four permission rows reviewed; no staffing data changed.
```

The script creates `AIPS_RPT_ACCESS_BK` once as the recovery copy of the four previous REPORTS permission rows. To restore those rows, run:

```sql
@sql/oracle/rollback_reports_scoped_access.sql
```

## Application rollout

Build the web application after pulling the code, then restart the API, worker, and web services. Existing browser sessions may refresh permissions; signing out and back in always reloads them.

## Acceptance checks

1. Sign in as Administrator and Captain: Reports is visible, all five tabs work, and Excel downloads are enabled.
2. Sign in as a Lead assigned to at least one final POD: only that person's final projects are listed, and Excel is disabled.
3. Sign in as a Member: only that person's projects and capacity are listed, and Excel is disabled.
4. Change the reporting week and confirm the capacity breakdown changes while project status remains the current status.
5. Open Projects & PODs and verify Lead, Members, schedule, hours, and staffing method against one known request.
6. Confirm a profile with incomplete capacity says `Needs refresh` and is not counted as zero capacity.

## Verified locally

- TypeScript check
- Application permission and workflow tests
- Agentic integration and report-model tests
- Backend report, capacity, directory, and privacy tests
- Roles/catalogue migration tests
- Optimized Next.js production build
