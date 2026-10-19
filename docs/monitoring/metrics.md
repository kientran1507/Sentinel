# Metrics Status

Sentinel exposes operational state through commands and logs: live device counts/status, first/last seen values, missed-poll counters, monitor lifecycle, transitions, and recent alerts.

SQL stores inventory observations, events, and alerts. That persistence is not a metrics time-series backend, and no retention cleanup is implemented.

No Prometheus endpoint/exporter, Grafana integration, dashboard, or historical metrics API is supplied. See [commands](../commands.md) and [storage](../architecture/persistent-storage.md) for available queries.
