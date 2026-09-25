# First-login direct access

First-login setup is a single transaction. The employee's skills, deliverable
experience, leave, external commitments, self-reported existing POD hours, and
capacity refresh are saved together. The onboarding row is then marked
`COMPLETE`, and the employee enters the workspace immediately.

There is no Captain review endpoint, review panel, or approval holding page.
Older database rows whose onboarding status is `REVIEW` are exposed as completed
setup so an earlier interrupted rollout cannot lock those employees out.

Self-reported existing POD hours count toward capacity, but they do not create a
request, assignment, approval, or active-POD count. The schema's historical
`PENDING` claim value is retained for compatibility and means only that the report
has not been linked to a separately imported genuine assignment.

After setup, employees with an explicit POD Lead or POD Member grant can edit
their own self-rated skills, evidence, interests, and deliverable experience from
Team & Skills. Permission checks aggregate their explicit grants, so a person's
higher display role does not hide the lower-role self-service permission.
