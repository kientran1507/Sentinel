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

## Presence Behavior

Defaults are a 30-second poll interval and 3 missed successful snapshots before offline. These are constructor settings, not integrated CLI/environment options.

The first successful snapshot establishes a baseline without discovery alerts. Later new devices generate discovery events. Missing devices generate one offline transition after the threshold; returning offline devices generate recovery. IP, hostname, and connection changes can also produce events. A failed collection does not count as a missing-device snapshot.

## Configuration and Persistence

Required: `ZTE_ROUTER_URL`, `ZTE_USERNAME`, `ZTE_PASSWORD`. Optional: `ZTE_RSA_PUBLIC_KEY`. See [setup](../development/contributing.md) for environment loading.

`python -m scripts.sentinel start` runs monitoring, persistence, alerts, and command adapters together. `python scripts/test_zte_monitor.py` is a live diagnostic and can contact the router.

Snapshots are persisted before presence processing, and transitions are stored separately. Durable records do not restore registry/debounce state at startup. Database status is not a replacement for current live presence. Write failures are isolated but writes are synchronous; see [storage](../architecture/persistent-storage.md) and [alerts](alerts.md).
