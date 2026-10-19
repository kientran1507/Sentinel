# K3s

K3s is a future deployment target. [infrastructure/kubernetes](../../infrastructure/kubernetes) contains no Sentinel workload, storage, secret, or ingress manifests.

The current application shares registry, presence, event bus, live alert history, and command state in one process. Separating monitor and command pods would lose that shared live view. SQLite also requires durable file storage; PostgreSQL requires a reachable configured database.

There is no Sentinel HTTP service to expose through Traefik. LAN discovery privileges, outbound connectivity, database lifecycle, secret wiring, restart semantics, and one Telegram poller per token all need validation before packaging. See [networking](../architecture/networking.md) and [storage](../architecture/persistent-storage.md).
