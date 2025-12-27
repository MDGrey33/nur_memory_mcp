# Project Phoenix - Post-Mortem Retrospective

**Date:** January 3, 2025
**Facilitator:** Amanda Foster (Scrum Master)
**Attendees:** Full Phoenix team (12 members)

## Project Overview

Project Phoenix was a 6-month initiative to rebuild our core data pipeline. Originally scheduled to complete November 15th, actual delivery was December 20th - 5 weeks late.

## What Went Well

- The new architecture handles 10x the throughput of the old system
- Zero data loss during migration despite processing 50TB
- Cross-team collaboration between Platform and Data Science was excellent
- Documentation is comprehensive - best we've ever produced

## What Didn't Go Well

### Timeline Slippage
The team identified that the original estimate was overly optimistic. We underestimated:
- Legacy system complexity (took 3 weeks longer than planned)
- Third-party vendor delays (Snowflake provisioning took 4 weeks instead of 1)
- Testing requirements for financial data accuracy

### Communication Issues
- Stakeholders weren't informed early enough when timeline slipped
- The weekly status reports didn't clearly communicate blockers
- Product team felt surprised by feature cuts made in October

### Technical Debt
- Rushed the final 2 sprints, accumulating debt in error handling
- Monitoring dashboards are incomplete
- Some edge cases have TODO comments instead of implementations

## Key Learnings

1. **Amanda noted:** We need buffer time built into estimates - suggest 20% padding.
2. **Derek (Tech Lead) committed** to implementing architecture review gates before major projects.
3. The team agreed that vendor dependencies should be started 2 months before code depends on them.
4. **Jessica (PM) decided** future projects will have weekly stakeholder demos, not just end-of-sprint.

## Action Items and Owners

- **Derek** will schedule 2 weeks of tech debt cleanup in January, focusing on error handling.
- **Amanda** will create a new estimation template that includes vendor lead times.
- **Jessica** committed to setting up a stakeholder communication plan template by January 10th.
- **Chris (Data Lead)** will document the migration playbook for future reference by January 15th.

## Risks Identified for Future

- The team is fatigued after the crunch. Two members mentioned considering time off.
- Similar estimation issues may recur on Project Atlas starting in February.
- The vendor management process needs formal review - we have 3 more major vendor integrations planned this year.

## Feedback from Stakeholders

> "The end result is excellent, but the journey was stressful. Better communication would have helped us plan around the delays." - Finance Director

> "Love the new system performance. Worth the wait." - Head of Analytics

## Process Changes Agreed

1. All projects over 3 months will require Architecture Review Board approval
2. Bi-weekly stakeholder syncs are now mandatory for Tier 1 projects
3. Vendor onboarding must start in Discovery phase, not Implementation

## Follow-up Meeting
Tech Debt Review scheduled for January 17th
Project Atlas kickoff on February 3rd - apply learnings!
