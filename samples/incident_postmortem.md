# Postmortem: checkout latency increase on 12 March

## Summary

On 12 March, checkout latency increased for approximately 47 minutes. The issue was traced to a configuration change that was applied to the primary region. Rollback was completed manually after the on-call engineer identified the regression. No customer data was lost.

## Impact

Between 09:14 and 10:01, an estimated 18% of checkout attempts were affected. Requests were queued rather than rejected. Monitoring flagged the increase at 09:16. The incident was communicated to support at 09:31.

## Root cause

A deployment was rolled out to the primary region without the corresponding cache invalidation step being scheduled. The stale cache caused the service to fall back to the slower path for every request that touched product data. Because the fallback was implemented as a graceful degradation, latency increased gradually rather than spiking, which delayed detection.

## What went well

The rollback procedure was documented and was followed exactly. The dashboard that surfaced the symptom had been built during the previous quarter of work on reliability.

## What we will change

- The cache invalidation step will be added to the deployment pipeline.
- The graceful degradation path will emit a metric when it is active.
- Alerts will be reviewed quarterly by the on-call rotation.
