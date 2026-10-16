# Core UI testing issues

Live UI testing of the VM application identified the following issues. The tested request approval, availability editing and leave cancellation saved successfully; the findings below concern misleading wording and unexpected navigation or confirmation behavior. No application fixes have been applied as part of this log.

- Test date: October 12, 2026.
- Application: http://140.245.228.123:8005/.
- Method: normal browser interactions with the application's test accounts and dummy data.
- Status: testing is ongoing. These observations are not a complete application audit.
- Priorities below are proposed triage priorities, not verified root causes.

## Issue summary

| ID | Priority | Issue | Evidence status | Tracking status |
| --- | --- | --- | --- | --- |
| UI-001 | Low | Approved staffing review retains pre-approval wording | Observed on REQ-1061; assignments and calendar bookings verified | Open |
| UI-002 | Medium | Onboarding saves after Continue without a fresh final confirmation following validation recovery | Observed once on Maya's first-login flow; repeat reproduction needed | Open |
| UI-003 | Low | Ending or cancelling availability unexpectedly returns to Command Center | Reproduced for Maya's leave and Kristie's external commitment; saved results verified | Open |
| UI-004 | Low | No-feasible-POD result retains waiting-for-completion placeholder text | Observed on completed REQ-1062 execution; no final assignment created | Open |
| UI-005 | Low | Recommendation prose displays a skill ID instead of its name | REQ-1063 shows SK-003 in explanations while capability chips correctly show Comms Review | Open |
| UI-006 | Low | Lead AI Fitment navigation opens Requests under a mismatched breadcrumb | Observed as Christine, POD Lead; no approval controls exposed | Open |
| UI-007 | Medium | Infeasible rerun retains an actionable stale recommendation | REQ-1075 after competing REQ-1074 approval; persists after Refresh; earlier stale approval was blocked | Open |

## UI-007 Infeasible rerun retains an actionable stale recommendation

**Priority:** Medium. **Status:** Open. **Account:** Kristie Mayfield, POD Captain.

**Reproduction and evidence:** Created REQ-1074 Customer Portal Launch Story and REQ-1075 Customer Portal Adoption Story for December 7–11, 2026. Both requested Customer Story / Story Creation, GTM SME and Portal SME, one lead and one member, 7.5 days / 60 person-hours. Both completed Ready for review before either was approved: REQ-1074 proposed Christine and Maya, 30 hours each; REQ-1075 proposed Indranie and Maya, 30 hours each. Maya showed 0% before and 75% after each independent proposal.

Approved REQ-1074 successfully. Without recalculating REQ-1075, attempted its approval. The application rejected it with Decision not confirmed — Evidence or workload changed. Recalculate the selected POD, review the new figures and approve again. Its request drawer remained Needs recommendation with No final assignment yet. This passes sequential approval-time revalidation after a competing request reserves capacity; it is not a simultaneous-concurrency test.

Reran unchanged REQ-1075. Its latest execution completed No feasible POD (NO_FEASIBLE_POD), consistent with Maya's newly reserved 30 hours. However, the review retained the older Indranie/Maya recommendation, its obsolete 0% → 75% figures, Ready for review labels, and enabled Approve pod, Reject and alternative-selection controls. Clicking Refresh and waiting for loading to finish reproduced the same mixed state.

**Expected:** Clearly identify the previous proposal as stale/historical and prevent it from appearing to be the current approvable result. Show the latest infeasible outcome prominently; retain deliberate recalculation or manual-override workflows as appropriate. Do not weaken backend revalidation.

**Impact and limits:** Misleading/actionable stale UI is confirmed. The pre-rerun approval guard prevented the competing assignment, and no final assignment existed at that check. No second approval attempt was made after the infeasible rerun. Root cause is unverified; no code or SQL changes were made. REQ-1074 remains Staffed; REQ-1075 remains unapproved.

**Capacity cross-check:** After the blocked approval and infeasible rerun, Reports for December 7–13 showed 60h committed in total, Christine at 75%, Maya at 75%, and Indranie at 0%. This is consistent with only REQ-1074 booking 30 hours for each assigned person, not both competing requests. Reports also displayed 5 ready for review; whether that aggregate includes the stale REQ-1075 proposal should be checked when investigating stale proposal presentation.

## UI-001 Approved review retains pre-approval wording


**Account and record:** Indranie Balkaran; REQ-1061, Customer Success Renewal Story.

### Reproduction

1. Create a request and let the agent produce a recommendation.
2. Open AI Fitment and approve the proposed POD.
3. Inspect the review after the request becomes Staffed.

**Observed:** The footer correctly displays "Staffed · Assignments approved," but the selection section still displays "Recommended POD selected" and "No capacity is reserved until approval." Alternative descriptions also continue explaining replacement selection even though their buttons are disabled.

**Expected:** The final state should clearly describe approved assignments and booked capacity. Pre-approval instructions should be hidden or explicitly labelled as historical recommendation information.

**Impact:** Users can mistake a completed approval for an unbooked proposal. No booking failure was observed: Kristie Mayfield and Christine Loba each have a confirmed 12-hour assignment, and the October 19–23 calendar shows 2.4 hours per weekday and 30% allocation for each.

**Suggested investigation:** Review the final-state copy and alternative sections in the staffing review UI. Do not change assignment calculations to address a wording issue.

**Retest acceptance:** Pending proposals retain the correct warning; Staffed and Closed records show accurate final/historical wording, retain execution history and cannot be accidentally reapproved.

## UI-002 Onboarding confirmation is reused after validation recovery

**Account:** Maya Bennett, maya.bennett@oracle.com; newly created POD Member.

### Observed sequence

1. Select GTM SME and a proficiency rating of 3/5, leaving experience blank.
2. Continue through Current work & leave to Review & confirm.
3. Check the review declaration and click Confirm and save profile.
4. Validation correctly returns to Skills with an experience-required message.
5. Change the skill to "Not rated — interest only" rather than inventing experience.
6. Continue to Current work & leave and enter an external commitment and a leave event.
7. Click Continue.

**Observed:** The review screen briefly appeared with its declaration already checked and the save action in progress. The profile then saved and opened the member workspace without another explicit click on Confirm and save profile.

**Expected:** Continue should open the final review without saving. Material edits after a confirmation should require reviewing the updated details and explicitly confirming the final submission again.

**Impact:** A user can save changed information without a fresh review action. The recorded data matched the entered test details; the mandatory experience check itself worked.

**Uncertainty:** This was observed once. Retained declaration state and step-button/form event handling are investigation candidates, not established causes. Reproduce with a fresh dummy onboarding account before implementing a fix.

**Retest acceptance:** Test both fresh onboarding and recovery from a rejected submission. Step navigation must not submit the profile. After material edits, the final declaration must reflect the application's chosen reconfirmation rule, and saving must require a distinct final action.

## UI-003 Availability ending returns to Command Center

**Account and record:** Maya Bennett; Annual leave on October 26, 2026, originally 8 hours.

### Reproduction

1. Open My Availability and select End / cancel for the future leave.
2. Inspect the preview: stop counting from October 12, with 8 future hours removed.
3. After explicit user confirmation, click Confirm end / cancel.

**Observed:** The application returned to Command Center after saving instead of remaining in My Availability.

**Expected:** Stay in My Availability, show a success result, update upcoming events and allow the user to inspect history without navigating back.

**Impact:** The navigation makes a successful operation harder to verify. Reopening My Availability showed the leave removed from upcoming events. Show history retained it as "Cancelled" with 0 hours. The separate Customer account planning commitment remained unchanged at 6 hours.

**Second reproduction:** Ending Kristie's Quarterly leadership communications commitment from October 13 also returned to Command Center. Reopening My Availability showed the correct retained October 12 segment of 4 hours and the separate October 5–11 historical segment of 30 hours. The calendar showed 4 hours on October 12, zero hours on October 13–16 and 10% weekly allocation.

**Uncertainty:** The navigation is now reproduced across two accounts and event types. Check whether session refresh, an application remount or another navigation event is involved; no root cause has been confirmed. A later Captain calendar check showed Maya's October 26–30 row with no leave entry and 0 hours on each day. This confirms removal from the affected week's display; with no committed work that week, 0% alone does not prove the available-hours denominator.

**Retest acceptance:** Cancel a future event and end an ongoing event from a permitted effective date. Verify stable navigation, success feedback, preservation of earlier history and correct remaining capacity in the affected week.

## UI-004 Infeasible result retains waiting placeholders

**Account and record:** Kristie Mayfield; REQ-1062, Customer Adoption Briefing.

**Reproduction:** Submit 40 person-hours for October 15 only, with one lead and one member, then wait for the automatic staffing execution to finish.

**Observed:** The execution correctly returned "No feasible POD" with NO_FEASIBLE_POD. However, the review still said "Recommendation evidence will appear when fitment completes" and "A validated recommendation will appear after fitment completes" in the candidate sections, despite the run having finished.

**Expected:** Replace waiting placeholders with a clear completed-but-infeasible explanation. Distinguish this result from a running execution. Do not imply that waiting alone will produce a recommendation.

**Impact:** Misleading presentation only in this test. No Approve pod control was shown, no candidate POD was proposed, and request details explicitly showed "No final assignment yet." The request remains open and unstaffed for follow-up testing; no manual override was attempted.

**Retest acceptance:** Running, successful, infeasible and failed executions each display appropriate candidate/evidence messages without weakening staffing validation.

## UI-005 Recommendation explanation exposes a skill ID

**Account and record:** Kristie Mayfield; REQ-1063, Customer Story Editorial Review.

**Observed:** Agent Execution and AI Fitment describe recorded capability coverage as "GTM SME, SK-003." The request and candidate capability chips correctly show GTM SME and Comms Review. The wording occurs for selected candidates and alternatives, before and after approval.

**Expected:** Resolve catalogue IDs to readable skill names consistently in the explanation. This test does not show a skill-matching failure: both selected people have the required rated skills.

**Retest acceptance:** Required capabilities, candidate chips and saved explanation text use the same readable catalogue names without changing the underlying matched IDs or staffing decisions.

## UI-006 Lead AI Fitment navigation shows Requests

**Account:** Christine Loba, christine.loba@oracle.com, signed in with the POD Lead profile.

**Reproduction:** Open My Availability, open navigation and select the enabled AI Fitment item.

**Observed:** The breadcrumb changes to AI Fitment, but the page heading is Staffing requests and its content is the same scoped request list. A subsequent DOM observation confirmed this was not a temporary loading state. There were no recommendation, approval, rejection or rerun controls.

**Expected:** Navigation should match the permitted destination. If Leads cannot use the fitment review, hide or lock that item, or redirect with a correct Requests breadcrumb. If read-only fitment is intended, show that view consistently.

**Impact:** Confusing navigation; no unauthorized staffing mutation was observed. This UI check is not proof of backend authorization enforcement.

## Passed checks and remaining work

- Maya could sign in, complete onboarding and enter the POD Member workspace.
- Rated skills with blank experience were blocked both during onboarding submission and in the normal skill editor. Interest-only GTM SME saved without a proficiency claim and showed 0 rated skills.
- Onboarding external work appeared as External commitment in My Availability and could be edited from 8 to 6 hours without an event-type error.
- Maya's UI locked Administration, AI Fitment, Agent Execution and Allocation Calendar; Requests did not show unrelated requests. This is a UI access check, not a complete backend authorization assessment.
- REQ-1061 creation, automatic agent execution, approval and confirmed calendar bookings passed.
- Indranie's 4-hour leave and 6-hour external commitment produced the expected 16.67% allocation for October 19–23: 6 / (40 - 4).
- Dashboard pending/staffed separation and project-type demand filtering passed in the tested scenario.
- Earlier Add employee configuration and availability edit-control blockers are not reopened here; subsequent tests succeeded.
- Kristie signed in as POD Captain while holding the POD Lead assignment on REQ-1061. Her request view showed both confirmed assignments correctly. This does not establish lead-only account restrictions.
- Kristie's closure form blocked blank and whitespace-only closure notes. After explicit user approval, REQ-1061 was closed on October 12. Both assignment records remain visible as Closed with their original 12 planned hours each. No project records were deleted.
- Project closure released all 24 future hours: the October 19–23 calendar showed Kristie and Christine at 0%, with 0 hours on each weekday, compared with 30% and 2.4 hours per weekday before closure. REQ-1061 no longer appeared in that week's calendar. REQ-1060 webinar bookings for Brenna and Tamar remained at 25% and 2 hours per weekday.
- Maya's separate 6-hour commitment showed 15% for October 19–23, and her cancelled October 26 leave was absent from the following week's calendar.
- The inactivity warning appeared while the closure form was open. Stay signed in dismissed it, preserved the closure note, and allowed the authorized closure to complete.
- Kristie's ongoing Quarterly leadership communications commitment was adjusted from October 12 onward: 30 remaining hours became 20. History retained October 5–11 at 30 hours. Calendar verification showed October 5–9 unchanged at 6 hours per weekday and 75%, while October 12–16 changed to 4 hours per weekday and 50%. At this stage the original 60-hour commitment consisted of 30 historical hours plus 20 current/future hours.
- With explicit user confirmation, that commitment was then ended from October 13. The saved result removed 16 hours on October 13–16, retained 4 hours on October 12 and kept the earlier 30 hours. Current-week allocation dropped from 50% to 10%; the calendar independently showed 4 hours on Monday and 0 hours Tuesday through Friday. Final retained total is 34 hours across the two historical/retained segments. The record was not deleted. Navigation issue UI-003 reproduced during this operation.
- After REQ-1061 closure, the dashboard showed six open staffed projects and no pending staffing. Reports retained REQ-1061 in Kristie's My PODs as Closed with the original 12-hour contribution and both team members.
- REQ-1062 was created as a deliberately infeasible 40-hour, one-day request for October 15 with one lead and one member. Automatic execution returned No feasible POD and request details showed no final assignment. It remains open and unstaffed.
- Reports showed six staffed projects, one closed project and one awaiting staffing after REQ-1062 creation, and the same staffing-utilization-v1 policy and 85% limit as the calendar.
- Remaining coverage includes preservation of elapsed project hours when closing an already-started project, lead-only permissions, additional staffing edge cases and successful rated-skill submission using user-provided experience.

## REQ-1063: leave, external work and rated skills

- Created Customer Story Editorial Review through the VM UI as Kristie: October 12–16, 2026; 24 person-hours (3 days), one lead and one member; required GTM SME plus Comms Review.
- Checked existing skill records before approval: Christine has GTM SME 5/5 and Comms Review 4/5; Kristie has both at 5/5. No skill data or experience text was changed.
- Automatic recommendation selected Christine as lead for 12 hours and Kristie as member for 12 hours. Christine's projected allocation was 50%: 12 / (40 - 16 leave hours). Kristie's was 40%: (12 project + 4 retained external hours) / 40. Brenna's alternative also included existing REQ-1060 work, showing 25% before and 55% after a hypothetical 12-hour replacement.
- Approved the recommended POD. The request became Staffed, both candidates became Approved, and rerun/replacement controls were disabled. UI-001's stale pre-approval wording reproduced.
- Independently checked the saved calendar. Christine retained 8-hour leave on October 12 and 13 with no REQ-1063 work on those dates; her project work was 4 hours/day on October 14–16. Kristie had 2.4 project hours/day across October 12–16, plus the existing 4-hour commitment on October 12 (6.4 total that day). Weekly totals remained 50% and 40% respectively.
- Krista's full-week leave remained visible as No available hours and she was not proposed. Maya's interest-only profile was not proposed. Absence from the displayed shortlist alone is not proof of the precise exclusion reason; explicit negative eligibility tests remain outstanding.
- In Kristie's account, Reports > My PODs showed REQ-1063 as Staffed, POD Member, 12 hours, with Christine and Kristie as the team. The request opened successfully from that row.
- Christine subsequently signed in as POD Lead. Her dashboard and Requests list showed REQ-1063; request details showed Christine as confirmed lead for 12 hours and Kristie as confirmed member for 12 hours. A Close project control was available but was not used.
- Christine's My Availability retained Personal leave on October 12–13 for 16 hours, with Edit and End / cancel controls. Her own capacity displayed 50%, one active POD and the 85% policy limit. No availability was changed.
- Christine's Reports > My PODs showed REQ-1063 as POD Lead, 12h, Staffed, with the correct team and October 12–16 dates. Her closed REQ-1061 member assignment remained visible as history.
- Lead UI scope checks: Requests showed her four assigned/historical projects (REQ-1056, REQ-1059, REQ-1063, REQ-1061), not the unrelated pending REQ-1062. No New request button was shown. Administration and Agent Execution were locked. The enabled AI Fitment item produced UI-006 rather than a staffing review. Backend authorization was not tested.
- Assigned-member verification for Tamar is recorded below. No code or SQL was changed during these tests.

## Tamar's assigned webinar and capacity after its end

- Signed in as tamar.steiner@oracle.com. The account profile is POD Lead, while her assignment on REQ-1060 is POD Member. These checks establish member-assignment behavior, not member-only account permissions.
- Her dashboard showed REQ-1056 and REQ-1060 as her two staffed projects. REQ-1060 details showed Tamar confirmed as POD Member for 20 hours, October 12–23, with Brenna Cooper as confirmed lead. No Close project or Open fitment action appeared in this request drawer.
- My Availability showed no recorded availability events, 25% weekly allocation, one active POD and the 85% policy limit.
- Her scoped Allocation Calendar showed only Tamar: 2 hours/day on October 12–16 and October 19–23, 25% in each week. October 26–30 showed 0 hours on every day and 0% allocation. Thus the approved 20 hours did not continue consuming capacity after the planned end, even though the project remained Staffed. This does not by itself test selection for a new later request.
- Reports showed 10 committed hours / 40 available hours for October 12–18, and My PODs correctly listed REQ-1060 as POD Member, 20h, Staffed, with Brenna and Tamar as the team. Her older REQ-1056 assignment remained as history without consuming current capacity.
- Administration and Agent Execution were locked. No new defect was identified in these checks. No project, availability or skill records were modified.
- Further request tests require a Captain or Administrator account: explicit exclusion for full-period leave or missing rated skills, capacity-limit boundaries and reuse of capacity for later requests.

## REQ-1064 policy boundary and one-day leave scenario

- Created Customer Story Messaging Review as Kristie for October 13 only: one lead, one member, 8 person-hours; GTM SME plus Comms Review required. Existing skills and availability were not edited.
- Automatic execution recommended Lucas as lead and Kristie as member for 4 hours each. Christine (on leave that day), Krista (full-week leave) and Maya (interest-only profile) were absent from the displayed recommendation and alternatives. This is consistent with exclusions but the UI does not disclose individual rejection reasons; it is not a conclusive isolated missing-skill test.
- The proposal counted Kristie's confirmed REQ-1063 work: 30% before and 80% after adding 4 hours on October 13, with 50% peak weekly allocation. Lucas showed 50% for the single request day and 10% for the week. Request-window and weekly percentages were correctly distinguished.
- Pallavi's alternative was limited to 2.8 hours, showing 50% before and exactly 85% after for October 13. Selecting it recalculated the full POD to Lucas 5.2 hours (65% request-day, 13% week) and Pallavi 2.8 hours (85% request-day, 57% week), preserving all 8 hours. This was a validated alternative, not a manual override.
- Approved that selection. The request became Staffed and both selected assignments became Approved. The saved calendar independently showed 5.2 hours for Lucas and 2.8 hours for Pallavi on October 13 only. Kristie remained at 40% weekly with only REQ-1063 work; the replaced original proposal was not also booked.
- Christine's and Krista's leave remained intact, and neither received REQ-1064 work. UI-005's SK-003 wording reproduced. No new functional defect was observed in this scenario.
- The Captain calendar showed Pallavi's 57% weekly total but only the 2.8-hour project entry. A subsequent report check identified the baseline as reported POD work, not an external commitment; see below. The calendar alone did not establish its source or an access-scope restriction.
- Missing-rated-skill exclusion and above-limit rejection still need isolated tests. The exact 85% boundary and effort redistribution passed; these do not prove every overload case.

### Pallavi account verification

- Signed in as pallavi.nadkarni@oracle.com. Her account profile is POD Captain, while REQ-1064 assigns her as POD Member.
- My Availability showed 57% for October 12–18, no recorded events (including when history was shown) and zero active PODs today. REQ-1064 starts October 13, so it is not yet an active POD on October 12.
- Reports > Capacity identified 40 available hours, 2.8 hours of POD work, 20 hours of reported POD work, zero external hours and zero leave hours. The weekly result is (20 + 2.8) / 40 = 57%, with 11.2 hours of headroom to the 85% weekly limit. Her existing 50% was therefore reported POD workload, not a hidden external event.
- Reports > My PODs listed Customer Story Messaging Review as POD Member, 2.8h, Staffed, October 13 only. Opening it showed Lucas confirmed as lead for 5.2 hours and Pallavi confirmed as member for 2.8 hours.
- The automatic recommendation/alternative calculation therefore accounted for reported workload as well as the approved projects and explicit external commitments verified in earlier scenarios. The 85% request-day figure and 57% weekly figure describe different periods, not a disagreement.
- No new defect was identified and no application data was modified during this account check. Missing-skill isolation and above-limit rejection remain outstanding.

## Exact capacity limit and later-date availability

- As Pallavi, created two normal Customer Story requests with Story Creation and mandatory GTM SME, one lead and zero members, on October 26 only. Neither used manual override.
- REQ-1065, Customer Adoption Story Draft, requested 6.81 hours. Automatic execution returned No feasible POD (NO_FEASIBLE_POD), with no Approve pod control. The completed-infeasible placeholder issue UI-004 reproduced.
- REQ-1066, Customer Value Story Draft, used matching schedule, staffing, deliverable and skill inputs but 6.8 hours. It returned a valid recommendation for Kristie as sole lead at 85% for the request day and 17% for the week. Christine and Indranie were valid alternatives at the same percentages.
- This paired comparison passed the exact boundary: 6.8 / 8 = 85% accepted; 6.81 / 8 = 85.125% rejected. Both runs completed without changing the existing workload between them.
- Kristie's earlier REQ-1063 assignment ends October 16. The October 26 proposal correctly showed 0% before the new work, demonstrating that an earlier approved assignment does not permanently consume capacity in later recommendations.
- REQ-1066 remains unapproved for the upcoming stale-proposal test: add leave for the proposed person's October 26 date, then verify approval revalidates the new availability. No capacity has been booked for these two requests.
- In the successful lead-only result, the zero-member section still says a validated recommendation will appear after fitment completes. This is another misleading empty-state case related to UI-004; the lead proposal itself is ready for review.

## Missing mandatory catalogue skill

- Team & Skills search for Portal SME returned zero people in Pallavi's 26-person directory scope. No profile or skill rating was modified.
- Created REQ-1067, Customer Story Portal Readiness, for October 26 only, one lead, zero members and 6.8 hours. It retained Story Creation and GTM SME, adding Portal SME through the existing catalogue selector, not an unverified Other value. The description and outcomes explicitly requested portal readiness review.
- The automatic agent completed with No feasible POD (NO_FEASIBLE_POD), no proposed person and no Approve pod control. The mapped requirement remained visible in the result.
- Compared with the successful 6.8-hour GTM SME request REQ-1066 on the same date, this is a passing UI scenario for an uncovered mandatory catalogue capability. The generic failure message does not disclose per-person reasons; it does not separately prove how interest-only ratings are handled for an individual candidate.
- REQ-1065 and REQ-1067 remain open and infeasible; REQ-1066 remains ready for review and unapproved. No assignments were created by these three tests. UI-004's stale waiting placeholders reproduced on the infeasible results.
- Next requires Kristie's sign-in to record October 26 leave after REQ-1066 was recommended. Approval revalidation, clarification revision and expired-date correction remain untested in this pass.

### Manual override scope observed

REQ-1062's manual override dialog explicitly stated a 100% POD-allocation limit and that manual choices bypass skill matching, leave and external commitments while enforcing roles, working hours and total effort. The dialog was inspected and cancelled without selecting people or calculating a preview. It cannot be used to prove automatic-agent exclusion rules. The user explicitly confirmed that this bypass behavior is intended; it is not a defect or an unresolved product decision.

## REQ-1066: availability changed after recommendation

- Signed in as Kristie and saved Annual leave for October 26, 2026, 8 hours. My Availability confirmed the saved date, total and Unavailable state. No previous event was modified.
- Without rerunning or recalculating first, opened the original Kristie 6.8-hour recommendation and submitted Confirm final assignment through normal approval, not manual override.
- Saving finished but the approval dialog remained open. No persistent rejection explanation was visible in the subsequent accessibility and DOM observations. After closing the dialog, request details explicitly showed No final assignment yet and Needs recommendation.
- Recalculate selection also completed without a persistent explanation or changed proposal visible. A fresh fitment run was then started to test the new leave evidence separately.
- The attempt created no final assignment, but the specific rejection cause was not exposed in the captured UI. Do not classify approval-time leave revalidation as conclusively passed without that evidence. Follow up on durable, actionable approval/recalculation failure feedback.
- The fresh run completed successfully and replaced Kristie with Indranie as the recommended sole lead for 6.8 hours (85% request-day, 17% week). Alternatives were Christine and Krista; Kristie was absent. This before/after test passes the automatic rerun scenario after newly recorded full-day leave. It does not establish the precise cause of the earlier approval failure.
- Left the replacement proposal unapproved and retained the new October 26 leave. No final assignment was created during this scenario; no code or SQL was changed.

## Clarification scenario and request date validation

- As Kristie, created REQ-1068, Customer Success Follow-up Pack, for November 2–6, 2026: Special Projects/ Ad Hoc, one lead and one member, 2 days converted to 16 person-hours, mandatory GTM SME and the request-specific deliverable Customer follow-up pack. Removed the default Research deliverable before saving.
- The description explicitly left the final format undecided between a written recap and a short recorded walkthrough. The agent nevertheless completed Ready for review, proposing Kristie as lead and Indranie as member for 8 hours each. It did not ask a clarification question. This establishes custom-deliverable submission and successful execution, not the Answer clarification/revision workflow. Whether this particular format ambiguity should block staffing needs a product expectation before classifying it as a defect.
- UI-005 reproduced with SK-002 in the explanation while the mapped requirement was shown as GTM SME. Left REQ-1068 unapproved.
- In a second request form, entered Customer Adoption Research Brief with October 5–9 dates, which were already past on October 12. Save was blocked by the Needed by date field: Value must be 12-10-2026 or later. Its minimum was October 12. No request was saved by this invalid submission.
- Corrected the same form to November 9–13 and saved successfully as REQ-1069: Special Projects/ Ad Hoc, Research, mandatory GTM SME, one lead and one member, 2 days/16 hours. This passes past-needed-date validation and recovery after correcting the form. It is not a revision of an existing expired request.
- REQ-1069 completed Ready for review with Kristie as lead and Christine as member, 8 hours each and 20% projected allocation each. The saved proposal used the corrected November dates. Left it unapproved; no staffing capacity was reserved by either new request.
- Answer clarification, creation of a new request revision from that answer, and correction of an already-saved expired request remain unverified. No code or SQL was changed.

## REQ-1069 selection safeguards and manual preview

- Selected Indranie as an alternative lead. Saved selection 1 retained Christine as member, 8 hours each, 16 total. Indranie disappeared from contributor alternatives, preventing her selection in both roles through the UI.
- Selected Kristie as an alternative member. Saved selection 2 retained Indranie as lead, with 8 hours each and 20% projected allocation each. Kristie was no longer offered as a lead alternative. The original recommendation remained identified separately. These UI selection safeguards and total-effort preservation passed; direct API duplicate submission was not tested.
- Opened Manual override. Calculate preview was disabled until a person changed or a manual flag was selected. Searching the member picker for the already-selected lead Indranie returned No matching people found, and the preview remained disabled with Choose a person for every POD role. Searching for Christine returned a valid choice; selecting her automatically marked that slot as manual.
- Calculate preview saved a Captain manual preview for Indranie as normally validated lead and Christine as manually overridden member, 8 hours each. The page explicitly said it was a saved draft, not an agent recommendation, and no capacity was reserved until approval. Christine had no AI fit score, a 100% POD-only cap, and explicit exception reporting. Indranie retained normal validation. The bypass therefore applies to marked individuals, not automatically to the entire POD.
- Inspected approval without submitting. It displayed both allocations and manual exceptions; the approval note was optional. Closed the dialog and checked request details: Needs recommendation and No final assignment yet.
- One initial accessibility-index click on the manual member picker closed the dialog unexpectedly. Reopening and using the named browser locator worked; this single observation is not yet a confirmed application defect.
- After explicit user confirmation, discarded the manual draft. The application confirmed Manual draft discarded and No assignments were created. REQ-1069 remained Needs recommendation and restored saved selection 2: Indranie as lead and Kristie as member, 8 hours each, with no capacity reserved. Only the manual preview was discarded; the request and earlier normal selection were retained. No final assignments, code changes or SQL changes were made in this scenario. The UI checks do not establish actual bypass of a nonzero leave/external conflict or the 100% boundary; this preview had zero leave/external hours in its request period.

## Ordered follow-up tests

### Clarification remains unverified

- Created REQ-1070, Regional Customer Enablement Sessions, as Kristie: November 16–20, Enablement / Prepare for Live Session, GTM SME, one lead and one member, 3 days / 24 hours.
- The description and outcomes explicitly left lead ownership unresolved: regional owners wanted a separate lead for each of two sessions, while the structured count specified one lead pending agreement on a shared lead.
- The agent completed Ready for review with Indranie as lead and Christine as member, 12 hours each, 30% allocation. It did not ask a clarification question. Left the request unapproved. Clarification answering, revision creation and automatic rerun remain unverified; investigate the intended treatment of conflicting narrative and structured staffing requirements.

### Approval revalidation after new leave

- Saved Kristie's Annual leave for November 9–13, 40 hours, after REQ-1069 saved selection 2 had proposed her for 8 hours as member alongside Indranie for 8 hours as lead.
- Submitted normal approval without recalculation or rerun. Captured the response: Decision not confirmed — Evidence or workload changed. Recalculate the selected POD, review the new figures and approve again.
- Request details remained Needs recommendation and explicitly showed No final assignment yet. This passes rejection of the stale selection after an availability change. The earlier REQ-1066 rejection message had not been captured; this retest establishes the revalidation response in a separate scenario.

### Manual preview with actual leave conflict

- For that same REQ-1069 selection, marked only Kristie's member slot as a manual override and calculated a preview. It succeeded with 8 hours each for Kristie and Indranie; no approval was submitted.
- Kristie's manual result showed 20% POD-only utilization, a 100% cap, 40.0 leave hours ignored and 0.0 external-work hours ignored. Normal overall workload correctly reported No available capacity for both request period and peak week. Indranie's unmarked lead retained normal rules.
- This passes leave-bypass behavior at preview stage with a real recorded conflict, not merely explanatory wording. The subsequent boundary checks are below; final manual persistence remains untested.
- After user confirmation, the first discard attempt returned Draft not discarded with Unexpected token '<', "<!DOCTYPE "... is not valid JSON. A refresh confirmed the manual draft still existed. One retry succeeded with Manual draft discarded / No assignments were created. The request and November 9–13 leave were retained. This transient response-format failure needs investigation if it recurs; its server or proxy cause is not established. No code or SQL was changed.

### Manual 100 percent boundary and external work

- Saved Kristie's Regional planning workshop external commitment for November 23 only, 4 hours. Created two Enablement / Prepare for Live Session requests on the same date, mandatory GTM SME, one lead and zero members, with matching descriptions, objectives and outcomes.
- REQ-1071, Customer Enablement Briefing, requested 1 day / 8 hours. REQ-1072, Customer Enablement Preparation, requested 8.01 hours. Both automatic executions returned No feasible POD, consistent with the normal 85% limit. UI-004's completed-result waiting placeholders remained visible.
- On REQ-1071, manually selected Kristie as the sole lead. Calculate preview succeeded for all 8 hours: 100% POD-only allocation in the request period and 20% peak weekly POD allocation. The exception panel explicitly showed 4.0 external-work hours ignored, 0.0 leave hours ignored, 150% overall request-period workload and 30% overall peak-week workload. Thus the preview preserved and disclosed the external commitment while applying the intended POD-only limit.
- On REQ-1072, selected the same person as manual lead on the same date. Calculate preview was rejected: Manual preview not saved — This exact team cannot fit the effort. Manual people remain capped at 100% including existing POD work; other people retain normal rules. Change people, dates or effort.
- This paired preview test passes exactly 100% (8/8) and rejects 100.125% (8.01/8), while demonstrating nonzero external-work bypass. REQ-1071 was not approved and therefore did not reserve capacity for the comparison. These tests do not yet establish final manual-assignment persistence or interaction with pre-existing approved POD hours at the boundary.
- After explicit user confirmation, discarded REQ-1071's manual draft successfully. The application confirmed No assignments were created and restored its prior No feasible POD result. REQ-1072 saved no manual preview. Both requests and the 4-hour external commitment remain; no final assignment, code change or SQL change was made.

### Skills eligibility baseline prepared

- Signed in as Maya Bennett, POD Member. Team & Skills showed 0 rated skills, average strength 0.0, GTM SME as Not rated / Interested, no deliverable experience and no role-based capabilities.
- Added catalogue Portal SME as Not rated — interest only, with the learning goal Learn to review customer portal pages for content readiness and publishing accuracy. Saved successfully. The profile displayed both interests and still had 0 rated skills; no proficiency or experience claim was added.
- Prepared Kristie's Captain sign-in for the next step: create a request needing GTM SME and Portal SME with a lead and a member, verify the interest-only baseline, then compare the same request after a valid rated-skill update. No eligibility conclusion has yet been drawn from this profile save.

### Skills eligibility request baseline

- Created REQ-1073, Customer Portal Story Review, as Kristie: November 30–December 4, 2026, Customer Story / Story Creation, mandatory GTM SME and Portal SME, one lead and one member, 2 days / 16 hours. The automatic execution completed No feasible POD (NO_FEASIBLE_POD), with no approval control or final assignment. This is the interest-only baseline; the rated-skill comparison remains pending.
- In Kristie's Team & Skills directory, searching Portal SME returned no people. Searching Maya found her profile, which showed 0 mapped skills and no capability evidence. The Captain view did not present Maya's interest as rated expertise. This is consistent with the baseline but does not alone establish the cause of infeasibility.

### Rated-skill comparison prepared

- As Maya, changed only Portal SME from interest-only to 4/5 and replaced its learning-goal text with explicitly labeled sample experience for the dummy profile: reviewing portal content accuracy, links, publishing readiness and presentation. Saved successfully; Team & Skills displayed 1 rated skill and average strength 4.0. GTM SME remained Not rated / Interested; deliverable experience and role-based capabilities remained empty.
- Reran the unchanged REQ-1073 as Kristie after the rated-skill update. The result changed from No feasible POD to Ready for review: Kristie as lead covering GTM SME and Maya as member covering Portal SME, 8 hours each, 20% request-period and peak-week allocation. This controlled comparison passes interest-only versus rated required-skill eligibility for this scenario.
- Approved the recommended POD to enable member-account visibility testing. Request details showed Staffed and confirmed final assignments for Kristie and Maya, 8 originally planned hours each, November 30–December 4. Maya's own-account visibility is the next check, not yet verified.
- Existing presentation issues recurred: UI-005 shows SK-005 instead of Portal SME in Maya's explanation; UI-001 still displays Recommended POD selected / No capacity is reserved until approval after the request is Staffed and its assignments are Approved. The request details correctly showed the confirmed assignments.

### Member-only account: approved assignment and scope

- Signed in as Maya after REQ-1073 approval. Command Center showed one staffed assigned request and My POD assignment linked to Customer Portal Story Review. The drawer showed Staffed, Maya's confirmed 8 originally planned hours and November 30–December 4 dates, plus Kristie as confirmed lead. No Close project, approval or fitment action was available in the member drawer.
- Maya's Requests screen contained only REQ-1073 and no create-request control. AI Fitment, Allocation Calendar, Agent Execution and Administration navigation were disabled. This passes the observed UI restrictions; no direct endpoint or backend authorization testing was performed.
- Current-week My Availability correctly remained 0% / 0 active pods because the new assignment starts in the future. This screen has no reporting-week selector. Reports was scoped to one visible person and one assigned project; selecting November 30 showed 8h committed / 40h available, 20% utilization and 26h headroom to the active 85% policy limit.
- My PODs showed REQ-1073, POD Member, 8h, Staffed, November 30–December 4. Personal assignment visibility and future reporting capacity pass. The previously logged SK-005 explanation wording also appears in the member dashboard and project drawer.

### Availability overlap to investigate

Indranie's calendar shows an existing 1.6-hour external commitment and 8-hour annual leave together on October 14 (9.6 hours displayed). This is not work created by REQ-1063. Confirm the intended external-work/leave overlap rule and whether the display represents an allowed recorded overlap or a validation gap before classifying it as a defect.
