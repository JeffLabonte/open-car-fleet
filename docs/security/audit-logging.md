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

With `DEBUG=False`, the application sends only the `security` logger to the
host's `/dev/log` socket using the `local0` syslog facility. Production Compose
mounts that socket into the web container. Ansible configures systemd-journald
to persist records under `/var/log/journal`, retain them for up to 90 days, and
use at most 2 GB of journal storage. The system journal uses root and
`systemd-journal` group access; keep membership in that group limited to
authorized operators. The application container can submit events through the
socket but cannot modify the journal files. Sink errors are discarded without
printing the event or interrupting the request. Local and test configurations
continue to use the console handler.

Authorized operators can review the security facility with:

```bash
sudo journalctl SYSLOG_FACILITY=16 --since "24 hours ago"
```

Alert on repeated authentication failures, rate-limit spikes, and access
denials. Review security events at least daily, monitor journal disk usage so
the 2 GB cap does not shorten the 90-day window, and archive records to
restricted off-host storage before expiration. Restrict journal deletion and
retention changes to the smallest operator group; journal files are managed
append-only by journald and are not writable by the application process.
