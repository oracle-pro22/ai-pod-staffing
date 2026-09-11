# Deliverables & experience

## Deploy

1. Stop only this application's process. Keep the prior deployment available.
2. In SQL Developer, open `sql/oracle/deliverable_experience.sql` on **AIPOD**, logged in as **AI_POD_STAFFING**, using a fresh session without pending work. Press **F5**. The earlier `self_skills.sql` and official catalogue migrations must already be applied.
3. Continue only after the script reports SUCCESS. It adds one nullable JSON CLOB and check constraint to PEOPLE. It never drops/reloads tables or changes existing ratings. No migration is executed automatically by the app.
4. Local: restart `npm run dev`. VM: deploy the matching source, run `npm ci` and `npm run build`, then restart only the AI Pod Staffing service on its configured port.
5. No new environment variables, AI keys or Python/backend process are needed. Rephrasing uses the existing server-side OCI Generative AI configuration and credentials.

If the SQL stops partway through, retain the error and correct that specific issue before rerunning this same additive script. Do not rerun setup or delete tables. Oracle DDL commits, so rollback cannot remove an added column. To roll back the application, restore its previous build and leave the new nullable column and any saved experience intact.

## Use and verify

- Select POD Member or POD Lead, then **Team & Skills → Manage my skills → Deliverables & experience**.
- Search/select an active catalogue deliverable. Project names distinguish same-named deliverables across projects; new free-text catalogue entries are not accepted.
- Choose an experience level and contribution scope. Mark interest independently. Learning requires interest; other levels require an experience note.
- Type experience, then **Rephrase with AI** (10–6,000 input characters). The suggestion replaces the text in that same box. **Undo** restores the prior text. AI failure leaves the original intact. Notes allow up to 8,000 characters; rephrasing does not save anything by itself.
- Click **Save changes**, close and reopen, then refresh the page. Check the saved deliverable, level, interest, scope and note. Confirm the existing skill ratings have not changed.
- Try both profiles and confirm one profile's edit does not change the other's entries. Two drafts of the same profile must yield a conflict after one saves; the other draft is retained for copy/reload.
- Retired deliverables remain visible when already saved. They cannot be added or edited, but may be removed explicitly. Removed items support Undo before saving.

Optional read-only SQL verification (replace P-001 with the intended employee ID):

```sql
SELECT person_id, full_name, skills_version, deliverable_experience_json
FROM AI_POD_STAFFING.PEOPLE
WHERE person_id = 'P-001';
```

## Model and API

- Existing PERSON_INTERESTS remains authoritative for self-rated skills and interests.
- PEOPLE.DELIVERABLE_EXPERIENCE_JSON holds a bounded array (maximum 100) of catalogue deliverable IDs, experience levels, contribution scopes, interest flags and notes. The server stamps catalogue-name snapshots, source `Self-assessment`, actor and time. These stamps are not an immutable audit trail.
- GET/PATCH `/api/me/skills` includes the deliverable catalogue and saved entries. PATCH adds `deliverableUpserts` and `removeDeliverableIds`. Old skill-only PATCH requests preserve all deliverable entries.
- The person-row lock and existing SKILLS_VERSION protect the whole edit. Skills and deliverables commit together; any validation/write failure rolls back both. No unrelated business records or governance tables are changed.
- JSON preserves the existing table count but has **no relational foreign key for each embedded deliverable ID**. The API validates and locks active catalogue rows on upsert; direct SQL writers must preserve this contract. Retire catalogue rows instead of deleting them. JSON_TABLE can support future reporting; a normalized junction table remains a future option if the no-new-tables constraint changes.
- Malformed saved JSON fails visibly, rather than being silently replaced with empty data.
- POST `/api/ai/rephrase` accepts `deliverableExperience`, using the same OWN/write permission and employee resolution as profile saving. Request objectives/outcomes retain their existing request-create permission checks. The prompt preserves contribution, support needs and facts; it must not turn learning goals into experience. Review the result before saving.
- This does not implement agent ranking, assign Project Manager, or automatically award mapped skills. Governance workflows remain on hold.
- Identity remains the application's current preview mapping: POD Lead → P-006, POD Member → P-001. This change does not implement real employee sign-in; authenticated identity integration is still required before multi-employee production use.

## Verification limits

Offline tests cover payload validation, independent skill/deliverable changes, transaction rollback/conflicts, retired catalogue entries, rephrase permission routing and UI rendering. Run `npm run test:skills`, `npm run test:application`, and `npm run build`. These do not substitute for executing the migration and the Oracle/OCI smoke checks above in your environment.
