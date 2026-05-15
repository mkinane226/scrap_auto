You are preparing a larger crawl run with recovery.

Goal:
- Execute a bigger batch safely and resumably.

Tasks:
1. Enable checkpoint/seen cache persistence.
2. Run medium-size crawl bounds and collect metrics.
3. Produce run summary:
   - total URLs fetched
   - status code distribution
   - total entities written by type
   - failure buckets

Acceptance:
- Re-running with same limits should skip already-seen URLs.
- No crash on intermittent 429/5xx.
- Run summary is printed at end.
