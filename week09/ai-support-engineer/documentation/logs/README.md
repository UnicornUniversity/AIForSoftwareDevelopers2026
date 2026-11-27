# Sample logs (sanitized)

These files are fictional, sanitized examples used by the `grep_logs` tool in the
AI Support Engineer demo. They contain no real customer data, host names or credentials.

Never copy production logs here. The tool reads every file in this folder, and this
repository is public.

| File              | What it shows                                              |
|-------------------|------------------------------------------------------------|
| `nginx-error.log` | `connection refused` upstreams, 502s after a reload         |
| `nginx-access.log`| Mixed 200/502 responses for the same endpoints             |
| `postgres.log`    | Failed WAL archiving and the resulting WAL gap             |
| `docker.log`      | `OOMKilled` containers, restart loops, a full disk          |
| `syslog.log`      | Kernel OOM killer, systemd restart counter                 |

Last verified: 2026-11-25.
