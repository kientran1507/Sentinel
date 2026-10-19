# Docker

Docker is a packaging target. [infrastructure/docker](../../infrastructure/docker) contains no Sentinel Dockerfile or Compose service; no image, volume contract, or tested container startup is supplied.

Use the [Python setup](../development/contributing.md) today. Future packaging must run the integrated process, provide environment secrets without baking in `.env`, persist the selected database, and allow router/provider access. ARP additionally needs local-link visibility and packet privileges; ordinary container networking may not provide them.

Use an explicit production backend selection and validate PostgreSQL before relying on it. See [storage](../architecture/persistent-storage.md). A container restart loses live presence and the live alert buffer even when SQL data survives.
