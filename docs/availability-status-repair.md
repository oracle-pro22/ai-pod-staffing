# Own availability and approved-status repair

The availability lifecycle UI and backend already support edits and end/cancel.
The deployed Lead/Member permission baseline grants creation but not updates,
so the UI correctly hides those actions. Do not bypass that check in React.

## Database permission repair

Run `sql/oracle/availability_update_access.sql` with F5 as AI_POD_STAFFING, in a
worksheet without unrelated pending transactions. This repeat-safe transaction:

- Requires existing lifecycle columns and active Lead/Member roles.
- Requires their existing OWN view/create permission.
- Changes only CAN_UPDATE on those two MY_AVAILABILITY rows.
- Does not alter accounts, role grants, assignments, event history, or schema.
- Leaves Captain/Admin role permissions untouched. A multi-role Administrator
  can use their existing Lead/Member grant only for their own events.

If local and VM use the same Oracle schema, apply once, not once per server.
Refresh/sign in again to refresh the frontend permissions. On distinct databases,
apply separately after reviewing the same preconditions. Do not rerun setup.sql.

## Code deployment

Approval/closure changes request revision without invalidating staffing history.
The UI now preserves the historical execution for STAFFED/CLOSED requests and
shows a final status instead of a rerun warning. Pending requests with an older
execution still require a fresh run. No trigger or assignment writes are changed.

Deploy the matching code, rebuild the VM frontend with `npm ci && npm run build`
while ai-pod-web is stopped, then start that service. No backend code change is
required for this repair. Do not build into the .next directory of a running web
service. Locally, the dev server hot-reloads these React changes.

## Verification

Run `node --test scripts/test-selections.cjs scripts/test-roster-multirole.cjs` and
the Python availability/lifecycle tests. In the UI verify own future Edit and
End/cancel, ongoing Adjust remaining, other-person read-only access, and history
preservation. Verify a staffed request retains its approved assignments and
offers execution history without saying Awaiting execution. Genuine pending
revisions and rejection/rerun must remain supported.
