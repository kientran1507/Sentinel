# Docker

Docker remains a repository packaging target. [infrastructure/docker](../../infrastructure/docker) contains no distributable Sentinel Dockerfile or Compose service. The owner's separately protected Pi deployment and pinned accepted images were used for [bounded acceptance](../development/milestone-3-pi-acceptance-20261117.md); those private resources are not generic deployment manifests supplied by this checkout.

Use the [Python setup](../development/contributing.md) today. Future packaging must run the integrated process, provide environment secrets without baking in `.env`, persist the selected database, and allow router/provider access. ARP additionally needs local-link visibility and packet privileges; ordinary container networking may not provide them.

Use an explicit production backend selection and validate PostgreSQL before relying on it. See [storage](../architecture/persistent-storage.md). A container restart loses live presence and the live alert buffer even when SQL data survives.
