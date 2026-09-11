# Skills and interests — Phase 2

The interface is implemented. It uses the existing Create request modal, form typography, warm neutral cards, and coral dropdown highlighting. Phase 1's database migration is sufficient; **do not rerun the migration or recreate tables for Phase 2**.

## Where to find it

1. Run the latest local application, or deploy the matching build on the VM.
2. Select **POD Member** or **POD Lead** in the demo profile dropdown.
3. Open **Team & Skills**.
4. In **My skills & interests**, select **Manage my skills**.

The panel reads `/api/me/skills`. It shows saved proficiency, interest indicators, evidence, source, and read-only role capabilities. Missing or revoked access fails closed with a retry/error state. Captain and Administrator do not receive this self-service control; Administrator's Add person feature is unchanged.

## Saving to Oracle

Save skills writes directly to Oracle after validation and permission checks. There is no separate saving feature flag. The former `STAFFING_SKILLS_PREVIEW_WRITES` setting is no longer read, even if an old environment file sets it to false.

The app still uses preview identities: POD Member corresponds to `P-001`, and POD Lead to `P-006`. Saves update those actual records; removing the extra flag does not introduce individual employee sign-in. Keep existing Oracle credentials unchanged. Restart the app and refresh the page after deploying this update. No SQL or environment changes are required.

Local:

```powershell
npm run dev
```

VM: pull the intended committed changes, run `npm run build`, then restart **only this application's existing service/process** on port 8005. No additional backend process, port, package or database change is needed. Never use broad `pkill node` commands on the shared VM.

## User journey

1. Search by catalogue skill name and select a dropdown result. No free-text skill creation is possible. Already selected skills are excluded from the list.
2. A new entry starts as **interest only**: Interested checked, proficiency not rated.
3. If the person has experience, select a proficiency of **1–5** and enter a short evidence note. Interest is independent of proficiency and can remain checked or unchecked.
4. Edit existing entries or select Remove. Existing entries removed from the draft have **Undo removal** before saving.
5. Select **Save skills**. Only changed assessments and explicit removals are sent to Oracle. Existing unrelated skills are not overwritten.
6. On success, the modal closes, a confirmation toast appears, and the personal panel plus shared application data refresh.

Project Manager is not in the selector and has no rating control. Its read-only section explains that it comes from a role. The role-to-capability mapping still awaits business confirmation; selecting POD Lead in the demo does not confer it.

Interest-only entries display **Not rated**, not zero stars, and do not contribute to average proficiency. Existing decimal ratings remain unchanged unless edited; modifying such an assessment requires selecting a whole-number rating. Ratings remain self-assessments, not verified expertise.

## Errors and draft safety

- Client validation catches missing evidence, invalid ratings, duplicate skills and invalid interest-only combinations. Backend validation remains authoritative.
- Save is disabled while a save is in progress; repeated clicks do not issue duplicate saves.
- Failed saves keep the draft and show an inline message.
- A stale-version 409 or uncertain network result blocks another save until the latest saved skills are reloaded. There is no automatic retry or silent overwrite.
- **Copy draft** preserves a reference in the clipboard if the browser permits it. **Reload saved skills** asks for explicit confirmation before replacing the local draft. If reload fails, the draft remains.
- Closing a changed form asks whether to discard the draft. A browser leave/reload warning is also registered while changes are unsaved. Drafts are not stored in local storage and do not survive a confirmed page exit.

## Verification

Automated checks:

```powershell
npm run test:application
npm run test:skills
npx tsc --noEmit
npm run build
```

Implementation-time browser checks used actual Oracle **reads only**:

- Member and Lead resolved to their respective profiles.
- The form opened with saved assessments.
- Searching `Comms` showed name-only catalogue matches; selecting Comms Team created an interest-only local draft.
- Selecting a rating changed the evidence label to required.
- Searching Project Manager produced no selectable result.
- Unsaved-change confirmation retained/discarded the draft as requested.
- Desktop and 390px mobile layouts were inspected; controls and footer fit the viewport.
- That initial browser verification used the former disabled-saving mode; no database save or deletion was performed. The later direct-save update removes that extra gate and its banners, with regression coverage for both an absent and an obsolete false environment flag.

Before the demo, save an approved test employee's assessment and verify it after refresh in both the panel and SQL Developer. Also verify a two-client stale-version conflict as described in the [Phase 1 runbook](self-skills-phase1.md). Backend transaction and conflict behavior has offline coverage; actual target-database writes still require this acceptance check.
