# Release 2.4 readiness review

> **Fictional teaching fixture.** All names, organizations, technical details, and numbers are fictional.

| Field | Value |
| --- | --- |
| Meeting ID | `sdlc-review-2026-11-12` |
| Language | en-US |
| Project | Atlas Procurement Portal (Brightline Components Ltd.), release 2.4 |
| Target duration | 3–5 minutes |
| Turns | 39 |

## Participants

| ID | Name | Role | Voice |
| --- | --- | --- | --- |
| `ANN` | Ann Smith | Project manager | female |
| `BOB` | Bob Hawkins | Senior software engineer | male |
| `GREG` | Greg Cox | Technical director | male |

## Script

### Status and integration

**1. ANN — Ann Smith** *(calm)*

> All right, let's start. The goal today is to decide whether we're ready to release 2.4 on Thursday, and to put every blocker on the record.

**2. BOB — Bob Hawkins** *(calm)*

> On functionality, the picture is this: the catalog, cart, and order history are done. What's left is notifications and the external API integration.

**3. ANN — Ann Smith** *(calm)*

> How ready is the integration?

**4. BOB — Bob Hawkins** *(thoughtful)*

> Of the twenty-two REST API endpoints, eighteen are stable. No, let me correct that: seventeen are stable, and five are still in progress.

**5. GREG — Greg Cox** *(firm)*

> "Still in progress" is not a status. What exactly isn't working?

**6. BOB — Bob Hawkins** *(thoughtful)*

> Authentication and token refresh. The main flow works, but the refresh token occasionally returns a 401 under load.

**7. GREG — Greg Cox** *(firm)*

> Is that a blocker?

**8. BOB — Bob Hawkins** *(calm)*

> Well, for external suppliers, yes. Internal users go through a session, so this issue doesn't affect them.

**9. ANN — Ann Smith** *(calm)*

> Then we can put the external integration behind a feature flag and turn it on after stabilization.

**10. GREG — Greg Cox** *(firm)*

> We can, but first find out whether the two big suppliers need the API on Thursday or just by the end of the month. If they need it Thursday, a flag won't save us.

**11. ANN — Ann Smith** *(calm)*

> Fine, I'll check with them today.

**12. BOB — Bob Hawkins** *(thoughtful)*

> One more thing: the contractor promised to finish refresh by Wednesday, but so far they've only sent a test environment.

**13. GREG — Greg Cox** *(firm)*

> So the risk isn't only technical, it's contractual. Keep that in the minutes.

### Database migration

**14. ANN — Ann Smith** *(calm)*

> We will. What about the database?

**15. BOB — Bob Hawkins** *(thoughtful)*

> The migration from MySQL to PostgreSQL is on track. We moved the reference data and orders, about 1.2 million records. Payments and audit are left.

**16. GREG — Greg Cox** *(firm)*

> How long did the transfer to staging take?

**17. BOB — Bob Hawkins** *(calm)*

> Last time... forty minutes. But the cache was cold, and on production it may take longer.

**18. ANN — Ann Smith** *(calm)*

> We need a full-volume rehearsal. Otherwise we'll discover the problem at four in the morning on Thursday.

**19. GREG — Greg Cox** *(firm)*

> Agreed. And a related question: do we have a rollback plan?

**20. BOB — Bob Hawkins** *(confident)*

> We do. The old database stays read-only, and we switch traffic back with a feature flag. We tested it twice on staging.

### Testing and risks

**21. ANN — Ann Smith** *(calm)*

> And regression testing?

**22. BOB — Bob Hawkins** *(thoughtful)*

> CI/CD doesn't pass everything. Of four hundred and twenty cases, seven fail.

**23. GREG — Greg Cox** *(firm)*

> Which ones? If it's payments or authentication, that's a different conversation.

**24. BOB — Bob Hawkins** *(thoughtful)*

> Two in notifications, three in reports, and two in export. Seven total. Payments and authentication are green.

**25. ANN — Ann Smith** *(calm)*

> So there are no blocking failures?

**26. BOB — Bob Hawkins** *(thoughtful)*

> In my assessment, no. But the reports are visible to accounting, and that will be noticed right after the release.

**27. GREG — Greg Cox** *(firm)*

> Visible is bad. I suggest we don't turn reports off, but document it in the release notes and schedule the fix for the first day after deployment.

**28. BOB — Bob Hawkins** *(thoughtful)*

> Then we need someone to check the export on Friday morning. Otherwise the task just sits there.

**29. GREG — Greg Cox** *(firm)*

> Agreed. Support can handle it, but the owner has to be from the team.

### Deployment and decision

**30. ANN — Ann Smith** *(calm)*

> I'll record that as a separate item. On deployment: we need a window with no load.

**31. BOB — Bob Hawkins** *(confident)*

> I suggest Thursday, from two to four in the morning. The Docker images are built and checked on staging. Well, assuming everything goes to plan.

**32. GREG — Greg Cox** *(firm)*

> Who's on duty?

**33. ANN — Ann Smith** *(calm)*

> I'll be available, along with the on-call engineer from the team and support.

**34. BOB — Bob Hawkins** *(thoughtful)*

> After deployment we run smoke tests and separately check authentication on production.

**35. GREG — Greg Cox** *(firm)*

> Good. I'm recording the decision: release on Thursday, external API behind the flag, reports fixed right after, migration rehearsed on Monday. Everything else goes into 2.4.1.

**36. ANN — Ann Smith** *(calm)*

> Agreed. I'll circulate the minutes and update the release checklist.

**37. BOB — Bob Hawkins** *(confident)*

> Then I'll close the refresh-token task today and send the contractor status.

**38. GREG — Greg Cox** *(firm)*

> Good. If it's quiet by Wednesday, we escalate.

**39. ANN — Ann Smith** *(calm)*

> All right, that's a wrap. Thank you.

---

This file is the readable view of `meeting_script.json`. The JSON files are the source of truth if anything differs.
