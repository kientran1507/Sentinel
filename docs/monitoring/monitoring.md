# ZTE Monitoring

Sentinel's implemented continuous monitor targets the ZTE H3601P router.

```text
ZTE H3601P
    |
    v
ZTEH3601PClient authentication
    |
    v
ZTECollector
    +-- DHCP/LAN clients
    +-- mesh topology
    |
    v
ZTEDevice snapshots
    |
    v
PresenceTracker -> DeviceRegistry -> DeviceEvent
```

`ZTEH3601PClient` authenticates with the configured router URL, username, password, and optional RSA public key. `ZTECollector` fetches DHCP clients and mesh topology, normalizes MAC addresses, merges duplicate records, and preserves connection/interface/RSSI/parent information where available.

`ZTEMonitor` polls through `collector.collect()` at `poll_interval` seconds. The default is 30 seconds; the offline threshold default is 3 missed snapshots. A failed collection is treated as unknown network state and does not mark devices offline. `PresenceTracker` emits one discovery event for a new device, one offline event after the threshold, and one recovery event when an offline device returns. Repeated missing polls are deduplicated.

The monitor publishes events to the shared `EventBus`. `AlertEngine` maps discovery to `UNKNOWN_DEVICE`/`WARNING`, offline to `DEVICE_OFFLINE`/`WARNING`, and recovery to `DEVICE_RECOVERED`/`INFO`.

## Configuration

```text
ZTE_ROUTER_URL=
ZTE_USERNAME=
ZTE_PASSWORD=
ZTE_RSA_PUBLIC_KEY=
```

These values belong in a local `.env` file and must not be committed. The diagnostic script `python scripts/test_zte_monitor.py` can exercise the monitor stack, while `python -m scripts.sentinel start` runs the integrated monitor and command services.

The current implementation keeps runtime state in memory and does not persist metrics or device records to a database.
