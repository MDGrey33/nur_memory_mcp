# Incident Post-Mortem: Payment Processing Outage

**Incident ID:** INC-2025-0042
**Date of Incident:** January 2, 2025 (14:23 - 16:47 UTC)
**Severity:** SEV-1 (Critical)
**Post-Mortem Date:** January 4, 2025
**Attendees:** Mike Chen (SRE Lead), Anna Kowalski (Backend Lead), James Wright (VP Engineering), Customer Success Team

## Incident Summary

Payment processing was unavailable for 2 hours 24 minutes, affecting approximately 12,000 transactions and an estimated $890,000 in failed payments.

## Timeline

- **14:23** - PagerDuty alert: Payment success rate dropped below 90%
- **14:28** - Mike acknowledged alert and began investigation
- **14:35** - Identified database connection pool exhaustion on payments-db-primary
- **14:42** - Anna joined the incident call
- **14:50** - Attempted connection pool increase from 100 to 200 - no improvement
- **15:15** - Root cause identified: Runaway query from analytics job locking critical tables
- **15:22** - James made the decision to kill the analytics job and restart the database
- **15:35** - Database restarted, but replication lag caused secondary failures
- **16:15** - Full cluster restored, payments processing resumed
- **16:47** - Confirmed all systems nominal, incident closed

## Root Cause

An analytics query deployed on January 1st contained a missing index hint, causing full table scans on the transactions table. During peak traffic on January 2nd, this query acquired row locks that blocked payment writes.

## Contributing Factors

1. The analytics job runs on the primary database instead of a read replica
2. No query timeout was configured for analytics workloads
3. The deployment on January 1st (a holiday) had reduced review coverage
4. Alerting thresholds detected the issue 8 minutes after it began

## Impact

- **Customer Impact:** 12,847 failed payment attempts
- **Revenue Impact:** $890,000 in failed transactions (estimated 60% recovered after retry)
- **Reputation:** 47 customer complaints, 3 social media mentions
- **SLA:** Breached 99.9% uptime commitment for January

## Decisions Made

1. **James decided** to implement a complete freeze on production deployments during holidays.
2. The team agreed to migrate all analytics workloads to read replicas within 2 weeks.
3. **Mike committed** to implementing query timeouts (30 second max) for non-critical workloads.
4. We will add database lock monitoring to our alerting stack.

## Action Items

| Owner | Action | Due Date |
|-------|--------|----------|
| Anna | Add missing index to transactions table | January 6 |
| Mike | Configure 30-second query timeout for analytics role | January 8 |
| Mike | Set up read replica for analytics workloads | January 17 |
| James | Document holiday deployment freeze policy | January 10 |
| Anna | Add pre-deployment query analysis to CI pipeline | January 15 |
| Customer Success | Send incident communication to affected customers | January 5 |

## Risk Assessment

- **High Risk:** Similar incidents could occur with other analytics queries. Full audit needed.
- **Medium Risk:** Read replica may have replication lag affecting analytics accuracy.
- **Low Risk:** Holiday freeze may slow feature velocity in Q1.

## Lessons Learned

1. Analytics and OLTP workloads must be physically separated
2. Holiday deployments require explicit VP approval and rollback plan
3. Our alerting detected the symptom (low success rate) but not the cause (lock contention)
4. The 15-minute delay in identifying root cause suggests we need better database observability

## Customer Communication

James approved sending a $50 credit to all customers with failed transactions. Anna will coordinate with Customer Success on the messaging.

## Follow-up Review

Scheduled for January 20th to verify all action items completed and review analytics migration progress.

## Attendee Sign-off

- Mike Chen: Approved
- Anna Kowalski: Approved
- James Wright: Approved
