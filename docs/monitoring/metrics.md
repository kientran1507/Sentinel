# Metrics

Sentinel currently tracks operational state in memory rather than exposing a metrics backend. Available runtime values include registry device counts, device status, `first_seen`, `last_seen`, missed-poll counters, monitor lifecycle state, event transitions, and bounded recent alert history.

There is no Prometheus endpoint, database retention, dashboard, or historical metrics API yet. Metrics export and retention are future work.
