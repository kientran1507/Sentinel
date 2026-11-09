# ZTE Monitoring

The integrated monitor targets ZTE H3601P DHCP/LAN clients and mesh topology:

```text
ZTEH3601PClient -> ZTECollector -> persistence adapter
                                         |
                                         v
                          PresenceTracker -> DeviceRegistry
                                         |
                                         v
                            DeviceEvent -> EventBus -> alerts
```

The collector normalizes MACs, merges clients, and retains available interface, parent, connection, RSSI, and wireless metadata. The integrated client uses `sha256_concat` authentication and disables TLS verification.

Successful polls also preserve parsed DHCP/LAN and mesh observations separately from the merged snapshot. Persistence records the reported lease, parent, node, and signal details as canonical evidence after attempting inventory writes. Source differences remain visible; unknown response fields are not copied. Records without a MAC can remain evidence without creating inventory. Partial failed polls clear the transient evidence buffer and do not replay old observations. See [router evidence](../architecture/security-events.md#router-evidence).

## Presence Behavior

Defaults are a 30-second poll interval and 3 missed successful snapshots before offline. These are constructor settings, not integrated CLI/environment options.

The first successful snapshot establishes a baseline without discovery alerts. Later new devices generate discovery events. Missing devices generate one offline transition after the threshold; returning offline devices generate recovery. IP, hostname, and connection changes can also produce events. A failed collection does not count as a missing-device snapshot.

## Configuration and Persistence

The integrated ZTE monitor keeps completed/successful/failed poll counters, consecutive failures, last success/failure times, duration, and failure stage/class in `monitor.health.snapshot()`. A failed fetch does not mark devices offline. Recovery clears the failure streak but retains the previous failure timestamp for investigation. Counters belong to the live monitor instance; they are not restored from history.

Startup, polling-loop shutdown, failed polls, and recovery are recorded as canonical collector events through a separate best-effort callback. They generate no additional device alerts and include no raw exception text. Metrics measure the poll pipeline, not guaranteed storage or notification delivery. The bot `/status` response and external metrics interfaces are unchanged. See [collector health](../architecture/security-events.md#collector-health).

Stop waits up to five seconds; a still-alive worker prevents a second polling thread from starting. Blocked network I/O is not forcibly cancelled, and abrupt process exits cannot guarantee a stopped record.

Required: `ZTE_ROUTER_URL`, `ZTE_USERNAME`, `ZTE_PASSWORD`. Optional: `ZTE_RSA_PUBLIC_KEY`. See [setup](../development/contributing.md) for environment loading.

`python -m scripts.sentinel start` runs monitoring, persistence, alerts, and command adapters together. `python scripts/test_zte_monitor.py` is a live diagnostic and can contact the router.

The integrated runtime uses [structured JSON logs](logging.md) on stderr when it owns logging configuration. Error summaries classify failures without raw response/driver text; command output is separate. Embedding hosts must configure their own log handlers.

Snapshots and parsed source observations are persisted before presence processing, and transitions are stored separately. Source observations do not generate additional alerts; baseline presence behavior is unchanged. Durable records do not restore registry/debounce state at startup. Database status is not a replacement for current live presence. Write failures are isolated but writes are synchronous; see [storage](../architecture/persistent-storage.md) and [alerts](alerts.md).
