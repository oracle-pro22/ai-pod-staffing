# Shared administrator enhancement notepad

Administration → Enhancements is one plain-text document shared by all authorized
administrators. Save is explicit; Refresh loads another admin's saved changes. Notes
are not sent to the staffing agent and do not change policies or assignments.

## Deployment

1. In SQL Developer, connect as `AI_POD_STAFFING` and run
   `sql/oracle/admin_enhancements.sql` with F5 once per distinct database/schema.
   It adds one table and seeds its empty singleton row. Reruns preserve saved notes.
   Oracle DDL commits implicitly; the script never alters business tables or grants.
2. Deploy the API and web changes together. Rebuild the web app with `npm run build`
   and restart the API/web services. No worker change or new environment variable is needed.
3. As an Administrator, open Enhancements, save a note, refresh, then read it using
   another Administrator account. The feature reports a setup error if SQL is missing;
   it does not prevent other Administration tabs from loading.

Local and VM copies pointing at the same schema share these notes; they are not
separate notepads. Existing maintenance snapshots do not automatically include this
new table; include `ADMIN_ENHANCEMENT_NOTES` in any full database backup/export.

## Behavior and safety

- Only active Administrators with FULL Administration view/update permissions can
  read/save. Identity is taken from the authenticated server context, never the form.
- Text, whitespace and line breaks are preserved, up to 50,000 characters. Empty
  notes are allowed. Text is never rendered as HTML.
- Every changed save increments the revision and records an audit event in the same
  transaction. A row lock and expected revision prevent silent concurrent overwrites.
- On conflict, the editor retains the draft and displays the latest saved version.
  Choose Edit latest version, copy any missing ideas from the retained draft, then Save.
  A second concurrent edit still triggers another conflict.
- Failed saves retain the editor text. After an uncertain network outcome, inspect the
  saved version before retrying. There is no autosave or offline browser persistence.
- Refresh and switching Administration tabs warn before discarding an unsaved draft;
  closing/reloading the browser uses its native unsaved-change warning. Save before
  navigating to another workspace screen or signing out. Expired sessions still follow
  the application's existing session rules.
- Audit contains save metadata, not note contents. This version has no note-history
  viewer or automatic merge/restore. Other admins see changes on load or Refresh.

## Checks

Run `npm run test:enhancements`, `node node_modules/typescript/bin/tsc --noEmit`, and,
from `backend/python`, `.venv/Scripts/python.exe -m unittest tests.test_admin_enhancements tests.test_admin_audit -v`
(Linux: `.venv/bin/python`). Tests use fixtures, not the live database.

After migration, test two admin browser sessions loading the same revision: save in
one, then attempt a different save in the other. The second must show a conflict and
preserve both versions. Verify a member's API access is denied, multiline/Unicode and
empty saves persist, service restart retains notes, and existing admin tabs still work.
