# Security audit events

The `security` logger records:

- Hanko authentication successes and failures, including disabled accounts and
  identity mismatches.
- Rate-limit violations.
- Access-control denials for fleet, car, and known-shop operations.
- Fleet membership role changes and removals.

Events use a stable event name and reason, with local database IDs and affected
resource IDs only where needed to correlate an access decision or membership
change. They must not include passwords, session tokens, Vault tokens,
AppRole credentials, provider identity subjects, email addresses, or raw
provider exception text. Rate-limit records intentionally omit client IP
addresses.

## Production operations

The application currently routes this logger to the console. The production
deployment does not yet configure a separate durable, access-restricted audit
destination. Do not treat Docker/container console output as the required
long-term security audit record.

Before relying on these events for incident response, route the logger to a
persistent append-only destination with restricted operator access, alert on
repeated authentication failures, rate-limit spikes, and access denials, and
review the events at least daily. Retain records for 90 days, archive them
outside the application host, and restrict deletion/retention changes to the
smallest operator group. Local and test environments should continue using the
console handler.
