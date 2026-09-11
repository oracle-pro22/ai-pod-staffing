# Restore adding non-availability

The existing button and Oracle save endpoint were retained, but the official-profile migration set `ROLE_PERMISSIONS.CAN_CREATE=N` for `MY_AVAILABILITY`. That hid the button and denied API writes.

## Apply

1. Deploy this matching application code. It enforces own-person writes for POD Lead and POD Member.
2. Open `sql/oracle/availability_access.sql` in SQL Developer, select **AIPOD / AI_POD_STAFFING**, and press **F5**. Use a worksheet connection without unrelated pending transactions.
3. Confirm SUCCESS. The script changes only `CAN_CREATE` on the two Lead/Member `MY_AVAILABILITY` permission rows. It does not change table structures, business data, or other profiles/resources. It is safe to rerun.
4. Restart the application if needed and refresh the page to load the updated permissions. VM deployment requires `npm run build` and restarting only this application's process/service.
5. Select **POD Lead** or **POD Member → My Availability → Add availability event**. The drawer is titled **Add non-availability**.
6. Select OOO, Leave, Travel, Training or Reduced hours; enter dates, an optional title and total unavailable hours; select **Save event**.

No environment flag is required. This uses the current profile's existing preview identity (Lead `P-006`, Member `P-001`), not a new person selector. Individual employee sign-in remains separate work. Administrator's people-availability view remains read-only; Captain permissions are unchanged.

Dates default to today's configured business date, matching Create request. Start dates cannot be in the past, and end dates cannot precede the start. The API validates the same rules and the maximum hours for the interval. Existing historical events are not modified.

Successful saves insert into `AVAILABILITY`, refresh the screen, and show a confirmation toast. Failed saves keep the form; if a response is lost, check the list before retrying. Duplicate events remain protected by the existing database constraint.

Offline regression tests cover restored button visibility, own-person writes, rejection of other-person/revoked access, and date/type/hour validation. The migration has not been executed by the coding agent; run it as above, then verify a save with your intended employee record.
