# Metrics Status

Sentinel exposes operational state through commands and logs: live device counts/status, first/last seen values, missed-poll counters, monitor lifecycle, transitions, and recent alerts.

`monitor.health.snapshot()` provides immutable process-local ZTE poll counts, failure streak, last success/failure/completion times, latest duration, and error class/stage. A new monitor resets counters. Canonical lifecycle/error/recovery history does not provide continuous liveness or historical successful-poll samples. See [collector health](../architecture/security-events.md#collector-health).

SQL stores inventory observations, events, and alerts. It is not a metrics time-series backend. Canonical events support [explicit scoped retention](../architecture/security-events.md#explicit-retention), but no automatic cleanup is enabled. [JSON logs](logging.md) support optional numeric context without adding a metrics exporter.

No Prometheus endpoint/exporter, Grafana integration, dashboard, or historical metrics API is supplied. See [commands](../commands.md) and [storage](../architecture/persistent-storage.md) for available queries.
